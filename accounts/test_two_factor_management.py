"""Managing two-factor: a code in place of the password, new recovery codes, and off.

A two-factor user may prove it's them with a code instead of the password
on every re-authentication form, unless they asked for both on security
changes. Turning two-factor off always takes both, and superusers can't
at all. Codes are made with ``pyotp`` from the device's secret; the
one-step drift keeps the real clock safe across a step boundary.
"""

from datetime import timedelta
from http import HTTPStatus

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import RecoveryCode, SecurityEvent, TwoFactorDevice

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
ACCOUNT = reverse("accounts:account")
RENAME = reverse("accounts:change_username")
DISABLE = reverse("accounts:two_factor_disable")
RECOVERY = reverse("accounts:recovery_codes")
STEP = timedelta(seconds=30)


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def recovery_codes(casey):
    """Two-factor on for Casey; the ten recovery codes it was turned on with."""
    codes = security.enable_two_factor(security.pending_two_factor_device(casey))
    mail.outbox.clear()
    return codes


@pytest.fixture
def device(recovery_codes, casey):
    return TwoFactorDevice.objects.get(user=casey)


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


@pytest.fixture
def admin(db):
    admin = User.objects.create_superuser(
        username="admin", password=PASSWORD, email="admin@example.com"
    )
    security.enable_two_factor(security.pending_two_factor_device(admin))
    mail.outbox.clear()
    return admin


def code(device):
    return pyotp.TOTP(device.secret).now()


def wrong_code(device):
    """Six digits that no step within the drift window would accept."""
    totp = pyotp.TOTP(device.secret)
    now = timezone.now()
    nearby = {totp.at(now + n * STEP) for n in range(-2, 3)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in nearby)


def events(user, kind):
    return user.security_events.filter(kind=kind)


# --- A code in place of the password --------------------------------------------------


def test_a_two_factor_user_may_answer_with_a_code(signed_in, device):
    field = signed_in.get(RENAME).context["form"].fields["current_password"]

    assert field.label == "Current password or authenticator code"


def test_without_two_factor_the_field_takes_the_password_only(signed_in, casey):
    field = signed_in.get(RENAME).context["form"].fields["current_password"]

    assert field.label == "Current password"


def _username_changed(casey):
    casey.refresh_from_db()
    return casey.username == "casey_r"


def _email_change_requested(casey):
    return events(casey, Kind.EMAIL_CHANGE_REQUESTED).exists()


def _password_changed(casey):
    casey.refresh_from_db()
    return casey.check_password("fresh-pass-456")


def _others_signed_out(casey):
    return events(casey, Kind.OTHER_SESSIONS_ENDED).exists()


def _codes_regenerated(casey):
    return events(casey, Kind.RECOVERY_CODES_REGENERATED).exists()


REAUTH_FORMS = [
    pytest.param(RENAME, {"username": "casey_r"}, _username_changed, id="username"),
    pytest.param(
        reverse("accounts:change_email"),
        {"email": "casey.new@example.com"},
        _email_change_requested,
        id="email",
    ),
    pytest.param(
        reverse("accounts:password_change"),
        {"new_password1": "fresh-pass-456", "new_password2": "fresh-pass-456"},
        _password_changed,
        id="password",
    ),
    pytest.param(
        reverse("accounts:sign_out_others"), {}, _others_signed_out, id="sign-out"
    ),
    pytest.param(RECOVERY, {}, _codes_regenerated, id="recovery-codes"),
]


@pytest.mark.parametrize(("url", "data", "changed"), REAUTH_FORMS)
def test_each_form_accepts_a_code_in_place_of_the_password(
    signed_in, casey, device, url, data, changed
):
    signed_in.post(url, {"current_password": code(device), **data})

    assert changed(casey)
    assert not events(casey, Kind.TWO_FACTOR_CODE_FAILED).exists()


@pytest.mark.parametrize(("url", "data", "changed"), REAUTH_FORMS)
def test_each_form_still_accepts_the_password(
    signed_in, casey, device, url, data, changed
):
    signed_in.post(url, {"current_password": PASSWORD, **data})

    assert changed(casey)
    device.refresh_from_db()
    assert device.last_used_step is None


def test_a_recovery_code_is_refused(signed_in, casey, device, recovery_codes):
    response = signed_in.post(
        RENAME, {"current_password": recovery_codes[0], "username": "casey_r"}
    )

    assert response.context["form"].errors["current_password"] == [
        "That isn't your current password or a working code."
    ]
    assert not _username_changed(casey)
    assert casey.recovery_codes.unused().count() == security.RECOVERY_CODE_COUNT


def test_a_code_spent_at_sign_in_is_refused_in_the_same_step(client, casey, device):
    current = code(device)
    client.post(reverse("accounts:login"), {"username": "casey", "password": PASSWORD})
    client.post(reverse("accounts:login_verify"), {"code": current})
    assert "_auth_user_id" in client.session

    response = client.post(RENAME, {"current_password": current, "username": "casey_r"})

    assert "current_password" in response.context["form"].errors
    assert not _username_changed(casey)


def test_a_code_works_once_on_the_forms_too(signed_in, casey, device):
    current = code(device)
    signed_in.post(RENAME, {"current_password": current, "username": "casey_r"})

    response = signed_in.post(
        RENAME, {"current_password": current, "username": "casey_q"}
    )

    assert "current_password" in response.context["form"].errors
    casey.refresh_from_db()
    assert casey.username == "casey_r"


def test_a_wrong_code_is_recorded_as_a_code_failure(signed_in, casey, device):
    signed_in.post(RENAME, {"current_password": wrong_code(device), "username": "x"})

    failure = events(casey, Kind.TWO_FACTOR_CODE_FAILED).get()
    assert failure.details == {"reauthentication": "change_username"}
    assert not events(casey, Kind.SIGN_IN_FAILED).exists()


def test_a_wrong_password_is_still_recorded_as_a_sign_in_failure(
    signed_in, casey, device
):
    signed_in.post(RENAME, {"current_password": "nope-nope", "username": "x"})

    assert events(casey, Kind.SIGN_IN_FAILED).count() == 1
    assert not events(casey, Kind.TWO_FACTOR_CODE_FAILED).exists()


def test_wrong_codes_count_toward_the_cooldown(signed_in, casey, device):
    for _ in range(security.COOLDOWN_THRESHOLD):
        signed_in.post(
            RENAME, {"current_password": wrong_code(device), "username": "casey_r"}
        )
    assert security.is_cooling_down(casey)

    response = signed_in.post(
        RENAME, {"current_password": code(device), "username": "casey_r"}
    )

    assert response.context["form"].has_error("current_password", "paused")
    assert not _username_changed(casey)
    device.refresh_from_db()
    assert device.last_used_step is None


def test_a_mistake_elsewhere_on_the_form_spends_no_code(signed_in, casey, device):
    response = signed_in.post(
        RENAME, {"current_password": code(device), "username": "casey@home"}
    )

    form = response.context["form"]
    assert "username" in form.errors
    assert "current_password" not in form.errors
    device.refresh_from_db()
    assert device.last_used_step is None
    assert not events(casey, Kind.TWO_FACTOR_CODE_FAILED).exists()


def test_with_both_asked_for_a_code_cannot_stand_in_for_the_password(
    signed_in, casey, device
):
    device.ask_for_security_changes = True
    device.save()
    form = signed_in.get(RENAME).context["form"]
    assert form.fields["current_password"].label == "Current password"

    response = signed_in.post(
        RENAME,
        {
            "current_password": code(device),
            "two_factor_code": code(device),
            "username": "casey_r",
        },
    )

    assert "current_password" in response.context["form"].errors
    assert not _username_changed(casey)


def test_confirm_identity_takes_a_code_only_when_asked_to(casey, device):
    assert not security.confirm_identity(casey, code(device), purpose="test")
    assert security.confirm_identity(
        casey, code(device), purpose="test", accept_code=True
    )


# --- Turning two-factor off -----------------------------------------------------------


def disable(client, current="", two_factor_code=""):
    return client.post(
        DISABLE, {"current_password": current, "two_factor_code": two_factor_code}
    )


def test_the_disable_page_requires_sign_in(client, db):
    response = client.get(DISABLE)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_the_disable_page_needs_two_factor_on(signed_in):
    response = signed_in.get(DISABLE)

    assert response.url == ACCOUNT


def test_the_disable_page_asks_for_the_password_and_a_code(signed_in, device):
    form = signed_in.get(DISABLE).context["form"]

    assert list(form.fields) == ["current_password", "two_factor_code"]
    assert form.fields["current_password"].label == "Current password"


def test_the_password_alone_does_not_turn_it_off(signed_in, casey, device):
    response = disable(signed_in, current=PASSWORD)

    assert "two_factor_code" in response.context["form"].errors
    assert casey.two_factor_enabled


def test_the_code_alone_does_not_turn_it_off(signed_in, casey, device):
    response = disable(signed_in, two_factor_code=code(device))

    assert "current_password" in response.context["form"].errors
    assert casey.two_factor_enabled


def test_a_code_in_the_password_field_does_not_turn_it_off(signed_in, casey, device):
    response = disable(signed_in, current=code(device))

    assert "current_password" in response.context["form"].errors
    assert casey.two_factor_enabled


def test_a_wrong_code_does_not_turn_it_off(signed_in, casey, device):
    response = disable(signed_in, current=PASSWORD, two_factor_code=wrong_code(device))

    assert "two_factor_code" in response.context["form"].errors
    assert casey.two_factor_enabled
    failure = events(casey, Kind.TWO_FACTOR_CODE_FAILED).get()
    assert failure.details == {"reauthentication": "two_factor_disable"}


def test_the_password_and_a_code_turn_it_off(signed_in, casey, device):
    device.ask_at_checkout = True
    device.save()

    response = disable(signed_in, current=PASSWORD, two_factor_code=code(device))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == ACCOUNT
    assert not casey.two_factor_enabled
    assert not TwoFactorDevice.objects.filter(user=casey).exists()
    assert not RecoveryCode.objects.filter(user=casey).exists()
    assert not security.code_required(casey, "checkout")
    event = events(casey, Kind.TWO_FACTOR_DISABLED).get()
    assert event.actor == casey
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.subject == "ThoughtTronix: Two-factor authentication was turned off"
    assert "Wasn't you? Contact support." in alert.body


def test_once_off_the_hub_offers_setup_again(signed_in, device):
    disable(signed_in, current=PASSWORD, two_factor_code=code(device))

    page = signed_in.get(ACCOUNT).content.decode()

    assert reverse("accounts:two_factor_setup") in page
    assert DISABLE not in page


def test_a_superuser_cannot_open_the_disable_page(client, admin):
    client.force_login(admin)

    response = client.get(DISABLE, follow=True)

    assert response.redirect_chain == [(ACCOUNT, HTTPStatus.FOUND)]
    assert "required for administrator accounts" in response.content.decode()


def test_a_superuser_cannot_post_to_it_either(client, admin):
    client.force_login(admin)
    device = admin.two_factor_device

    response = disable(client, current=PASSWORD, two_factor_code=code(device))

    assert response.url == ACCOUNT
    assert admin.two_factor_enabled
    assert not events(admin, Kind.TWO_FACTOR_DISABLED).exists()
    device.refresh_from_db()
    assert device.last_used_step is None


def test_the_module_refuses_a_superuser_too(admin):
    assert not security.disable_two_factor(admin)
    assert admin.two_factor_enabled


def test_the_hub_offers_turning_off_to_everyone_but_superusers(
    client, signed_in, device, admin
):
    assert DISABLE in signed_in.get(ACCOUNT).content.decode()

    client.force_login(admin)
    page = client.get(ACCOUNT).content.decode()
    assert DISABLE not in page
    assert "Required for administrator accounts." in page


# --- New recovery codes ---------------------------------------------------------------


def test_the_recovery_codes_page_requires_sign_in(client, db):
    response = client.get(RECOVERY)

    assert response.url.startswith(reverse("accounts:login"))


def test_the_recovery_codes_page_needs_two_factor_on(signed_in):
    response = signed_in.get(RECOVERY)

    assert response.url == ACCOUNT


def test_opening_the_page_changes_nothing(signed_in, casey, device, recovery_codes):
    security.use_recovery_code(casey, recovery_codes[0])

    response = signed_in.get(RECOVERY)

    assert "You have 9 unused recovery codes left." in response.content.decode()
    assert RecoveryCode.objects.filter(user=casey).count() == 10
    assert not events(casey, Kind.RECOVERY_CODES_REGENERATED).exists()


def test_regenerating_replaces_every_code_and_shows_ten_once(
    signed_in, casey, device, recovery_codes
):
    response = signed_in.post(RECOVERY, {"current_password": PASSWORD})

    assert response.status_code == HTTPStatus.OK
    assert "no-store" in response["Cache-Control"]
    new_codes = response.context["codes"]
    assert len(new_codes) == security.RECOVERY_CODE_COUNT
    assert len(set(new_codes)) == security.RECOVERY_CODE_COUNT
    page = response.content.decode()
    assert all(new in page for new in new_codes)
    assert "Your old recovery codes no longer work." in page
    # Only hashes are kept.
    stored = set(casey.recovery_codes.values_list("code_hash", flat=True))
    assert len(stored) == security.RECOVERY_CODE_COUNT
    assert not stored & set(new_codes)
    # Every old code is dead; the new ones work.
    assert not any(security.use_recovery_code(casey, old) for old in recovery_codes)
    assert security.use_recovery_code(casey, new_codes[0])
    # And they are never shown again.
    again = signed_in.get(RECOVERY).content.decode()
    assert not any(new in again for new in new_codes)


def test_regenerating_records_the_event_and_alerts(signed_in, casey, device):
    signed_in.post(RECOVERY, {"current_password": PASSWORD})

    assert events(casey, Kind.RECOVERY_CODES_REGENERATED).get().actor == casey
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.subject == "ThoughtTronix: Your recovery codes were replaced"
    assert "Wasn't you? Contact support." in alert.body


def test_a_wrong_password_keeps_the_old_codes(signed_in, casey, device, recovery_codes):
    response = signed_in.post(RECOVERY, {"current_password": "nope-nope"})

    assert "current_password" in response.context["form"].errors
    assert not events(casey, Kind.RECOVERY_CODES_REGENERATED).exists()
    assert security.use_recovery_code(casey, recovery_codes[0])


def test_the_hub_shows_codes_left_and_links_to_both_pages(
    signed_in, casey, device, recovery_codes
):
    security.use_recovery_code(casey, recovery_codes[0])

    page = signed_in.get(ACCOUNT).content.decode()

    assert "9 unused recovery codes left" in page
    assert RECOVERY in page
    assert DISABLE in page
