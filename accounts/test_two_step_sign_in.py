"""Signing in with two-factor on: the password, then a code, and nothing between.

The rules are tested against ``accounts.security`` with a pinned clock
(``at=``/``now=``), so nothing sleeps. The page tests use the real clock,
which the one-step drift makes safe across a step boundary. Codes are made
with ``pyotp`` from the device's own secret.
"""

import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from importlib import import_module

import pyotp
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
LOGIN = reverse("accounts:login")
VERIFY = reverse("accounts:login_verify")
STEP = timedelta(seconds=30)
# The start of a time step, so ``NOW + n * STEP`` is n steps on exactly.
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
RESET_LINK = re.compile(r"https?://\S+(/accounts/password/reset/[^/\s]+/[^/\s]+/)")


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def device(casey):
    return security.pending_two_factor_device(casey)


@pytest.fixture
def recovery_codes(device):
    """Two-factor on for Casey; the ten recovery codes it was turned on with."""
    codes = security.enable_two_factor(device, at=NOW - timedelta(days=1))
    mail.outbox.clear()
    return codes


@pytest.fixture
def two_factor(recovery_codes, device):
    device.refresh_from_db()
    return device


@pytest.fixture
def request_(db):
    """A bare request with a session of its own, for the module's functions."""
    request = RequestFactory().post("/", REMOTE_ADDR="198.51.100.7")
    request.session = import_module(settings.SESSION_ENGINE).SessionStore()
    return request


def code_at(device, moment):
    return pyotp.TOTP(device.secret).at(moment)


def current_code(device):
    return pyotp.TOTP(device.secret).now()


def wrong_code(device, moment=None):
    """Six digits that no step within the drift window would accept."""
    moment = moment or timezone.now()
    nearby = {code_at(device, moment + n * STEP) for n in range(-2, 3)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in nearby)


def sign_in(client, identifier="casey", password=PASSWORD, *, follow=False, **data):
    return client.post(
        LOGIN, {"username": identifier, "password": password, **data}, follow=follow
    )


def enter_code(client, code, *, follow=False, **data):
    return client.post(VERIFY, {"code": code, **data}, follow=follow)


def signed_in(client):
    return "_auth_user_id" in client.session


def failures(user):
    return user.security_events.filter(kind=Kind.TWO_FACTOR_CODE_FAILED)


# --- The half-finished sign-in -----------------------------------------------------


def test_a_pending_sign_in_names_its_account(request_, casey, two_factor):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    assert security.pending_sign_in_user(request_.session, now=NOW) == casey


def test_the_pending_sign_in_stores_no_identifier_or_secret(
    request_, casey, two_factor
):
    security.begin_two_factor_sign_in(
        request_.session, casey, "Casey@Example.com", at=NOW
    )

    stored = str(dict(request_.session))
    assert "casey@example.com" not in stored.lower()
    assert two_factor.secret not in stored
    assert "_auth_user_id" not in request_.session


def test_the_pending_sign_in_lasts_five_minutes(request_, casey, two_factor):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    later = NOW + security.PENDING_SIGN_IN_MAX_AGE
    assert security.pending_sign_in_user(request_.session, now=later) == casey

    too_late = later + timedelta(seconds=1)
    assert security.pending_sign_in_user(request_.session, now=too_late) is None
    # Gone for good, not only refused this once.
    assert security.PENDING_SIGN_IN_KEY not in request_.session
    assert security.pending_sign_in_user(request_.session, now=NOW) is None


@pytest.mark.parametrize(
    "change",
    [
        lambda user: (user.set_password("changed-pass-456"), user.save()),
        lambda user: user.rotate_session_key(),
        lambda user: User.objects.filter(pk=user.pk).update(is_active=False),
        lambda user: user.two_factor_device.delete(),
        lambda user: user.delete(),
    ],
    ids=["password changed", "others signed out", "locked", "2fa removed", "deleted"],
)
def test_the_pending_sign_in_dies_when_the_account_changes(
    request_, casey, two_factor, change
):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    change(casey)

    assert security.pending_sign_in_user(request_.session, now=NOW) is None


def test_no_pending_sign_in_means_no_one(request_):
    assert security.pending_sign_in_user(request_.session) is None
    assert security.check_sign_in_code(request_, "123456") is None


# --- Checking a code at step 2 -----------------------------------------------------


def test_an_authenticator_code_completes_the_sign_in(request_, casey, two_factor):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    user = security.check_sign_in_code(request_, code_at(two_factor, NOW), at=NOW)

    assert user == casey
    assert security.pending_sign_in_user(request_.session, now=NOW) is None
    assert not failures(casey).exists()


def test_a_code_from_a_step_already_used_is_refused(request_, casey, two_factor):
    code = code_at(two_factor, NOW)
    assert security.verify_code(two_factor, code, at=NOW)
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    assert security.check_sign_in_code(request_, code, at=NOW) is None
    assert failures(casey).count() == 1


def test_a_wrong_code_is_a_failure_and_keeps_the_sign_in_pending(
    request_, casey, two_factor
):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    result = security.check_sign_in_code(request_, wrong_code(two_factor, NOW), at=NOW)

    assert result is None
    event = failures(casey).get()
    assert event.ip_address == "198.51.100.7"
    assert event.details == {}
    assert security.pending_sign_in_user(request_.session, now=NOW) == casey


def test_wrong_codes_and_wrong_passwords_share_one_total(request_, casey, two_factor):
    for n in range(3):
        security.record_failure(Kind.SIGN_IN_FAILED, casey, at=NOW - (3 - n) * STEP)
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    for _ in range(2):
        security.check_sign_in_code(request_, wrong_code(two_factor, NOW), at=NOW)

    assert security.is_cooling_down(casey, now=NOW)
    # The account is paused, so the half-finished sign-in is no use.
    assert security.pending_sign_in_user(request_.session, now=NOW) is None


def test_five_wrong_codes_discard_the_sign_in_and_pause_the_account(
    request_, casey, two_factor
):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)
    wrong = wrong_code(two_factor, NOW)

    for n in range(security.SIGN_IN_CODE_ATTEMPTS - 1):
        security.check_sign_in_code(request_, wrong, at=NOW + n * timedelta(seconds=5))
        assert security.pending_sign_in_user(request_.session, now=NOW) == casey

    security.check_sign_in_code(request_, wrong, at=NOW + timedelta(seconds=30))

    assert security.pending_sign_in_user(request_.session, now=NOW) is None
    assert security.is_cooling_down(casey, now=NOW + timedelta(seconds=30))


def test_no_code_is_checked_or_recorded_while_the_account_is_paused(
    request_, casey, two_factor
):
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)
    for n in range(5):
        security.record_failure(Kind.SIGN_IN_FAILED, casey, at=NOW + n * STEP / 10)
    later = NOW + STEP
    before = casey.security_events.count()

    assert (
        security.check_sign_in_code(request_, code_at(two_factor, later), at=later)
        is None
    )

    assert casey.security_events.count() == before
    two_factor.refresh_from_db()
    assert two_factor.last_used_step is None
    assert security.pending_sign_in_user(request_.session, now=later) is None


def test_wrong_codes_count_in_the_browsers_history_against_what_was_typed(
    request_, casey, two_factor
):
    security.begin_two_factor_sign_in(request_.session, casey, "Casey", at=NOW)
    for _ in range(security.SIGN_IN_CODE_ATTEMPTS):
        security.check_sign_in_code(request_, wrong_code(two_factor, NOW), at=NOW)

    # Back at the password, the page's own line already reads "paused".
    standing = security.note_refused_sign_in(request_.session, "casey", now=NOW)
    assert standing.paused_until is not None


# --- Recovery codes ----------------------------------------------------------------


def test_a_recovery_code_completes_the_sign_in_once(request_, casey, recovery_codes):
    code = recovery_codes[0]
    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)

    assert security.check_sign_in_code(request_, code, at=NOW) == casey

    security.begin_two_factor_sign_in(request_.session, casey, "casey", at=NOW)
    assert security.check_sign_in_code(request_, code, at=NOW) is None
    assert failures(casey).count() == 1


def test_a_recovery_code_is_marked_used_and_the_rest_still_work(casey, recovery_codes):
    assert security.use_recovery_code(casey, recovery_codes[0], at=NOW)

    used = casey.recovery_codes.filter(used_at__isnull=False).get()
    assert used.used_at == NOW
    assert used.code_hash == security._hash_recovery_code(recovery_codes[0])
    assert security.use_recovery_code(casey, recovery_codes[1], at=NOW)


def test_a_recovery_code_ignores_case_and_the_dash(casey, recovery_codes):
    typed = recovery_codes[0].upper().replace("-", "")

    assert security.use_recovery_code(casey, typed)


def test_using_a_recovery_code_records_how_many_are_left_and_alerts(
    request_, casey, recovery_codes
):
    security.use_recovery_code(casey, recovery_codes[0], request=request_, at=NOW)

    event = casey.security_events.get(kind=Kind.RECOVERY_CODE_USED)
    assert event.actor == casey
    assert event.details == {"remaining": 9}
    assert event.ip_address == "198.51.100.7"
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert alert.subject == "ThoughtTronix: A recovery code was used to sign in"
    assert "9 of your recovery codes are left" in alert.body
    assert "Wasn't you? Contact support." in alert.body
    assert recovery_codes[0] not in alert.body


def test_the_last_recovery_code_says_so(casey, recovery_codes):
    for code in recovery_codes[:-2]:
        security.use_recovery_code(casey, code)
    mail.outbox.clear()

    security.use_recovery_code(casey, recovery_codes[-2])

    assert "1 of your recovery codes is left" in mail.outbox[0].body


def test_a_recovery_code_without_an_email_alerts_nobody(casey, recovery_codes):
    casey.email = ""
    casey.save()

    assert security.use_recovery_code(casey, recovery_codes[0])
    assert mail.outbox == []


def test_another_accounts_recovery_code_is_refused(casey, recovery_codes):
    dana = User.objects.create_user(username="dana", password="dana-pass-123")

    assert not security.use_recovery_code(dana, recovery_codes[0])
    assert casey.recovery_codes.filter(used_at__isnull=True).count() == 10


# --- Step 1 on the page ------------------------------------------------------------


def test_a_correct_password_signs_a_two_factor_user_in_nowhere(
    client, casey, two_factor, product
):
    response = sign_in(client)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == VERIFY
    assert not signed_in(client)
    assert not casey.security_events.filter(kind=Kind.SIGN_IN_SUCCEEDED).exists()
    assert not casey.user_sessions.exists()
    # Not on the storefront, the account pages or the admin.
    for url in (
        reverse("products:catalog"),
        product.get_absolute_url(),
        reverse("orders:cart"),
    ):
        assert client.get(url).wsgi_request.user.is_anonymous
    assert client.get(reverse("accounts:account")).url.startswith(LOGIN)
    assert client.get(reverse("admin:index")).status_code == HTTPStatus.FOUND


def test_a_wrong_password_never_reaches_step_2(client, casey, two_factor):
    response = sign_in(client, password="wrong")

    assert response.status_code == HTTPStatus.OK
    assert security.PENDING_SIGN_IN_KEY not in client.session


def test_users_without_two_factor_sign_in_as_before(client, casey):
    response = sign_in(client)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse(settings.LOGIN_REDIRECT_URL)
    assert signed_in(client)
    assert security.PENDING_SIGN_IN_KEY not in client.session


def test_an_unfinished_setup_does_not_ask_for_a_code(client, casey, device):
    sign_in(client)

    assert signed_in(client)


# --- Step 2 on the page ------------------------------------------------------------


def test_step_2_without_a_password_first_goes_back_to_sign_in(client, db):
    response = client.get(VERIFY, follow=True)

    assert response.redirect_chain == [(LOGIN, HTTPStatus.FOUND)]
    assert not signed_in(client)


def test_the_page_asks_for_one_code_and_is_never_cached(client, casey, two_factor):
    sign_in(client)

    response = client.get(VERIFY)

    assert response.status_code == HTTPStatus.OK
    assert list(response.context["form"].fields) == ["code"]
    assert "no-store" in response["Cache-Control"]
    assert "recovery codes" in response.content.decode()


def test_a_current_code_signs_in(client, casey, two_factor):
    sign_in(client)

    response = enter_code(client, current_code(two_factor))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse(settings.LOGIN_REDIRECT_URL)
    assert int(client.session["_auth_user_id"]) == casey.pk
    assert security.PENDING_SIGN_IN_KEY not in client.session
    assert casey.security_events.filter(kind=Kind.SIGN_IN_SUCCEEDED).count() == 1
    assert casey.user_sessions.count() == 1
    assert client.get(reverse("accounts:account")).status_code == HTTPStatus.OK


def test_a_code_already_used_is_refused_at_the_next_sign_in(client, casey, two_factor):
    code = current_code(two_factor)
    sign_in(client)
    enter_code(client, code)
    client.post(reverse("accounts:logout"))

    sign_in(client)
    response = enter_code(client, code)

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors["code"] == ["That code didn't work."]
    assert not signed_in(client)


def test_a_wrong_code_is_refused_and_says_what_is_left(client, casey, two_factor):
    sign_in(client)

    response = enter_code(client, wrong_code(two_factor))

    assert response.status_code == HTTPStatus.OK
    assert not signed_in(client)
    assert failures(casey).count() == 1
    page = response.content.decode()
    assert "That code didn&#x27;t work." in page
    assert "4 attempts left before sign-in pauses for 15 minutes." in page


def test_a_recovery_code_signs_in_once_and_alerts(client, casey, recovery_codes):
    sign_in(client)
    enter_code(client, recovery_codes[3])

    assert signed_in(client)
    assert len(mail.outbox) == 1
    assert "recovery code" in mail.outbox[0].subject

    client.post(reverse("accounts:logout"))
    sign_in(client)
    response = enter_code(client, recovery_codes[3])

    assert response.status_code == HTTPStatus.OK
    assert not signed_in(client)


def test_five_wrong_codes_send_you_back_paused(client, casey, two_factor):
    sign_in(client)
    wrong = wrong_code(two_factor)
    for _ in range(security.SIGN_IN_CODE_ATTEMPTS - 1):
        enter_code(client, wrong)

    response = enter_code(client, wrong, follow=True)

    assert response.redirect_chain == [(LOGIN, HTTPStatus.FOUND)]
    assert "Sign-in is paused" in response.content.decode()
    assert security.PENDING_SIGN_IN_KEY not in client.session
    assert security.is_cooling_down(casey)

    # Back at step 1 the right password is refused, as for any pause.
    again = sign_in(client)
    assert again.status_code == HTTPStatus.OK
    assert again.context["standing"].paused_until is not None
    assert not signed_in(client)
    assert client.get(VERIFY).status_code == HTTPStatus.FOUND


def test_an_expired_sign_in_goes_back_to_the_password(client, casey, two_factor):
    session = client.session
    security.begin_two_factor_sign_in(
        session, casey, "casey", at=timezone.now() - timedelta(minutes=6)
    )
    session.save()

    response = enter_code(client, current_code(two_factor), follow=True)

    assert response.redirect_chain == [(LOGIN, HTTPStatus.FOUND)]
    assert "timed out" in response.content.decode()
    assert not signed_in(client)
    two_factor.refresh_from_db()
    assert two_factor.last_used_step is None


def test_next_survives_both_steps(client, casey, two_factor):
    addresses = reverse("accounts:addresses")

    first = sign_in(client, next=addresses)
    assert first.url == f"{VERIFY}?next={addresses}"
    assert client.get(first.url).context["next"] == addresses

    second = enter_code(client, current_code(two_factor), next=addresses)
    assert second.url == addresses


def test_an_unsafe_next_is_dropped(client, casey, two_factor):
    first = sign_in(client, next="https://evil.example/")
    assert first.url == VERIFY

    second = enter_code(client, current_code(two_factor), next="https://evil.example/")
    assert second.url == reverse(settings.LOGIN_REDIRECT_URL)


def test_start_again_keeps_next(client, casey, two_factor):
    addresses = reverse("accounts:addresses")
    sign_in(client, next=addresses)

    page = client.get(f"{VERIFY}?next={addresses}")

    assert page.context["password_url"] == f"{LOGIN}?next={addresses}"


def test_signing_in_as_someone_else_drops_the_pending_sign_in(
    client, casey, two_factor
):
    User.objects.create_user(username="dana", password="dana-pass-123")
    sign_in(client)

    sign_in(client, "dana", "dana-pass-123")

    assert security.PENDING_SIGN_IN_KEY not in client.session
    assert client.get(VERIFY).status_code == HTTPStatus.FOUND


def test_the_admin_asks_for_a_code_too(client, two_factor):
    casey = two_factor.user
    casey.is_staff = casey.is_superuser = True
    casey.save()
    admin_index = reverse("admin:index")

    first = sign_in(client, next=admin_index)
    assert not signed_in(client)
    assert client.get(admin_index).status_code == HTTPStatus.FOUND

    second = enter_code(client, current_code(two_factor), next=admin_index)
    assert first.url == f"{VERIFY}?next={admin_index}"
    assert second.url == admin_index
    assert client.get(admin_index).status_code == HTTPStatus.OK


# --- After a password reset --------------------------------------------------------


def test_a_password_reset_leaves_two_factor_in_force(casey, two_factor):
    client = Client()
    client.post(reverse("accounts:password_reset"), {"email": "casey@example.com"})
    link = RESET_LINK.search(mail.outbox[-1].body).group(1)
    landing = client.get(link)
    client.post(
        landing.url,
        {"new_password1": "synaptic-velvet-42", "new_password2": "synaptic-velvet-42"},
    )
    assert casey.security_events.filter(kind=Kind.PASSWORD_RESET_COMPLETED).exists()

    response = sign_in(client, password="synaptic-velvet-42")

    assert response.url == VERIFY
    assert not signed_in(client)
    enter_code(client, current_code(two_factor))
    assert signed_in(client)
