"""Turning two-factor on: a pending device, a working code, recovery codes once.

Codes are made with ``pyotp`` from the device's own secret. Tests of the
drift window pin the clock with ``at=``; the page tests use the real one,
which the one-step drift makes safe across a step boundary.
"""

import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from accounts import security
from accounts.models import RecoveryCode, SecurityEvent, TwoFactorDevice

Kind = SecurityEvent.Kind
User = get_user_model()

SETUP = reverse("accounts:two_factor_setup")
STEP = timedelta(seconds=30)
# The start of a time step, so ``NOW ± n * STEP`` is n steps away exactly.
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
RECOVERY_CODE = re.compile(r"\b[a-z2-9]{5}-[a-z2-9]{5}\b")


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password="casey-pass-123", email="casey@example.com"
    )


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


@pytest.fixture
def device(casey):
    return security.pending_two_factor_device(casey)


def code_at(device, moment):
    return pyotp.TOTP(device.secret).at(moment)


def current_code(device):
    return pyotp.TOTP(device.secret).now()


def stored_codes_match(user, codes):
    hashes = set(user.recovery_codes.values_list("code_hash", flat=True))
    return hashes == {security._hash_recovery_code(code) for code in codes}


# --- The pending device ------------------------------------------------------------


def test_a_pending_device_has_a_secret_and_is_not_on(casey, device):
    assert device.user == casey
    assert len(device.secret) == 32
    assert device.confirmed_at is None
    assert not casey.two_factor_enabled


def test_the_pending_device_keeps_its_secret_until_confirmed(casey, device):
    again = security.pending_two_factor_device(casey)

    assert again.pk == device.pk
    assert again.secret == device.secret
    assert TwoFactorDevice.objects.filter(user=casey).count() == 1


def test_there_is_nothing_to_set_up_once_two_factor_is_on(casey, device):
    security.enable_two_factor(device)

    assert casey.two_factor_enabled
    assert security.pending_two_factor_device(casey) is None


def test_the_provisioning_uri_names_the_store_and_the_account(device):
    uri = security.provisioning_uri(device)

    assert uri.startswith("otpauth://totp/ThoughtTronix:casey?")
    assert f"secret={device.secret}" in uri
    assert "issuer=ThoughtTronix" in uri


def test_the_qr_code_is_inline_svg_with_a_title(device):
    svg = security.provisioning_qr_svg(device)

    assert svg.startswith("<svg")
    assert "<title>QR code for setting up two-factor authentication</title>" in svg
    # The secret travels inside the drawing, never as readable text.
    assert device.secret not in svg


def test_the_setup_key_is_the_secret_in_groups_of_four(device):
    key = security.setup_key(device)

    assert key.replace(" ", "") == device.secret
    assert all(len(group) == 4 for group in key.split(" "))


# --- Checking a code ---------------------------------------------------------------


def test_the_code_for_now_is_accepted(device):
    assert security.verify_code(device, code_at(device, NOW), at=NOW)


@pytest.mark.parametrize("steps", [-1, 1])
def test_a_code_one_step_early_or_late_is_accepted(device, steps):
    assert security.verify_code(device, code_at(device, NOW + steps * STEP), at=NOW)


@pytest.mark.parametrize("steps", [-2, 2])
def test_a_code_two_steps_off_is_refused(device, steps):
    code = code_at(device, NOW + steps * STEP)
    # Guard against the one-in-a-million chance the codes coincide.
    assert all(code != code_at(device, NOW + s * STEP) for s in (-1, 0, 1))

    assert not security.verify_code(device, code, at=NOW)


def test_a_code_works_only_once(device):
    code = code_at(device, NOW)

    assert security.verify_code(device, code, at=NOW)
    assert not security.verify_code(device, code, at=NOW)
    assert not security.verify_code(device, code, at=NOW + STEP)


def test_a_code_older_than_the_last_one_used_is_refused(device):
    assert security.verify_code(device, code_at(device, NOW), at=NOW)

    earlier = code_at(device, NOW - STEP)
    assert not security.verify_code(device, earlier, at=NOW)


def test_the_next_steps_code_is_accepted_after_this_ones(device):
    assert security.verify_code(device, code_at(device, NOW), at=NOW)

    later = NOW + STEP
    assert security.verify_code(device, code_at(device, later), at=later)


def test_spaces_are_ignored_and_anything_but_six_digits_is_refused(device):
    code = code_at(device, NOW)

    assert not security.verify_code(device, code[:5], at=NOW)
    assert not security.verify_code(device, "abcdef", at=NOW)
    assert not security.verify_code(device, "", at=NOW)
    assert security.verify_code(device, f" {code[:3]} {code[3:]} ", at=NOW)


def test_a_wrong_code_records_nothing(device):
    code = code_at(device, NOW + 5 * STEP)

    assert not security.verify_code(device, code, at=NOW)
    device.refresh_from_db()
    assert device.last_used_step is None


# --- Recovery codes ----------------------------------------------------------------


def test_ten_distinct_recovery_codes_are_made_and_only_hashes_kept(casey):
    codes = security.generate_recovery_codes(casey)

    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(RECOVERY_CODE.fullmatch(code) for code in codes)
    assert stored_codes_match(casey, codes)
    stored = list(RecoveryCode.objects.values_list("code_hash", flat=True))
    assert not any(code in value for code in codes for value in stored)
    assert all(len(value) == 64 for value in stored)


def test_regenerating_replaces_the_whole_set(casey):
    old = security.generate_recovery_codes(casey)
    new = security.generate_recovery_codes(casey)

    assert RecoveryCode.objects.filter(user=casey).count() == 10
    assert stored_codes_match(casey, new)
    assert not set(old) & set(new)


# --- Enabling ----------------------------------------------------------------------


def test_enabling_confirms_the_device_records_the_event_and_alerts(casey, device):
    codes = security.enable_two_factor(device, at=NOW)

    device.refresh_from_db()
    assert device.confirmed_at == NOW
    assert casey.two_factor_enabled
    assert stored_codes_match(casey, codes)
    event = casey.security_events.get(kind=Kind.TWO_FACTOR_ENABLED)
    assert event.actor == casey
    assert event.details == {}
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert alert.subject == ("ThoughtTronix: Two-factor authentication was turned on")
    assert "Wasn't you? Contact support." in alert.body
    assert not any(code in alert.body for code in codes)


def test_enabling_without_an_email_sends_nothing(casey, device):
    casey.email = ""
    casey.save()

    security.enable_two_factor(device)

    assert casey.two_factor_enabled
    assert mail.outbox == []


# --- The setup page ----------------------------------------------------------------


def test_the_page_requires_sign_in(client, db):
    response = client.get(SETUP)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))
    assert not TwoFactorDevice.objects.exists()


def test_visiting_setup_creates_an_unconfirmed_device(signed_in, casey):
    response = signed_in.get(SETUP)

    assert response.status_code == HTTPStatus.OK
    device = TwoFactorDevice.objects.get(user=casey)
    assert device.confirmed_at is None
    assert not casey.two_factor_enabled


def test_the_page_shows_the_qr_code_and_the_setup_key(signed_in, casey):
    page = signed_in.get(SETUP).content.decode()

    device = TwoFactorDevice.objects.get(user=casey)
    assert "<svg" in page
    assert "QR code for setting up two-factor authentication" in page
    assert security.setup_key(device) in page


def test_reloading_the_page_keeps_the_same_secret(signed_in, casey):
    signed_in.get(SETUP)
    first = TwoFactorDevice.objects.get(user=casey).secret
    signed_in.get(SETUP)

    assert TwoFactorDevice.objects.get(user=casey).secret == first


def test_the_page_asks_for_a_code_and_no_password(signed_in):
    form = signed_in.get(SETUP).context["form"]

    assert list(form.fields) == ["code"]


def test_the_page_is_never_cached(signed_in):
    response = signed_in.get(SETUP)

    assert "no-store" in response["Cache-Control"]


def test_a_wrong_code_leaves_setup_pending(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)
    wrong = code_at(device, datetime.now(UTC) + 10 * STEP)

    response = signed_in.post(SETUP, {"code": wrong})

    assert response.status_code == HTTPStatus.OK
    assert "code" in response.context["form"].errors
    device.refresh_from_db()
    assert device.confirmed_at is None
    assert not casey.two_factor_enabled
    assert not RecoveryCode.objects.exists()
    assert not casey.security_events.filter(kind=Kind.TWO_FACTOR_ENABLED).exists()
    assert mail.outbox == []
    # The QR code is still there to try again.
    assert security.setup_key(device) in response.content.decode()


def test_a_wrong_code_does_not_count_toward_the_cooldown(signed_in, casey):
    signed_in.get(SETUP)

    for _ in range(security.COOLDOWN_THRESHOLD):
        signed_in.post(SETUP, {"code": "000000"})

    assert not security.is_cooling_down(casey)


def test_a_working_code_turns_two_factor_on(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)

    response = signed_in.post(SETUP, {"code": current_code(device)})

    assert response.status_code == HTTPStatus.OK
    assert casey.two_factor_enabled
    assert casey.security_events.filter(kind=Kind.TWO_FACTOR_ENABLED).count() == 1
    assert len(mail.outbox) == 1


def test_ten_recovery_codes_are_shown_once_and_only_hashes_are_stored(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)

    response = signed_in.post(SETUP, {"code": current_code(device)})

    assert "accounts/recovery_codes_issued.html" in [t.name for t in response.templates]
    assert "no-store" in response["Cache-Control"]
    codes = RECOVERY_CODE.findall(response.content.decode())
    assert len(codes) == 10
    assert stored_codes_match(casey, codes)

    # Never again: not on the hub, and setup sends the user away.
    hub = signed_in.get(reverse("accounts:account")).content.decode()
    again = signed_in.get(SETUP, follow=True).content.decode()
    for page in (hub, again):
        assert not any(code in page for code in codes)


def test_the_code_used_for_setup_cannot_be_used_again(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)
    code = current_code(device)
    signed_in.post(SETUP, {"code": code})

    device.refresh_from_db()
    assert not security.verify_code(device, code)


def test_once_on_setup_shows_neither_qr_code_nor_key(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)
    signed_in.post(SETUP, {"code": current_code(device)})

    response = signed_in.get(SETUP)
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")

    page = signed_in.get(SETUP, follow=True).content.decode()
    assert "Two-factor authentication is already on." in page
    assert "<svg viewBox" not in page
    assert security.setup_key(device) not in page
    assert device.secret not in page


def test_a_post_after_setup_is_confirmed_changes_nothing(signed_in, casey):
    signed_in.get(SETUP)
    device = TwoFactorDevice.objects.get(user=casey)
    signed_in.post(SETUP, {"code": current_code(device)})
    hashes = set(casey.recovery_codes.values_list("code_hash", flat=True))

    response = signed_in.post(SETUP, {"code": "123456"})

    assert response.status_code == HTTPStatus.FOUND
    assert set(casey.recovery_codes.values_list("code_hash", flat=True)) == hashes
    assert casey.security_events.filter(kind=Kind.TWO_FACTOR_ENABLED).count() == 1


# --- The Account page --------------------------------------------------------------


def test_the_hub_shows_two_factor_off_with_a_setup_link(signed_in):
    page = signed_in.get(reverse("accounts:account")).content.decode()

    assert "Two-factor" in page
    assert ">Off<" in page
    assert SETUP in page


def test_an_abandoned_setup_still_reads_off(signed_in):
    signed_in.get(SETUP)

    response = signed_in.get(reverse("accounts:account"))
    assert response.context["two_factor_device"] is None
    assert SETUP in response.content.decode()


def test_the_hub_shows_two_factor_on_without_a_setup_link(signed_in, casey):
    security.enable_two_factor(security.pending_two_factor_device(casey))

    response = signed_in.get(reverse("accounts:account"))
    page = response.content.decode()
    assert response.context["two_factor_device"].user == casey
    assert "<span>On</span>" in page
    assert SETUP not in page
