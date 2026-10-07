"""Changing the password, signing out other devices, and the re-auth behind both.

"A second session" is a second test client signed in as the same user:
it stands for the laptop left signed in somewhere else.
"""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
NEW_PASSWORD = "synaptic-velvet-42"


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


@pytest.fixture
def elsewhere(casey):
    """A second session for the same account, on another device."""
    other = Client()
    other.force_login(casey)
    return other


def is_signed_in(client):
    response = client.get(reverse("accounts:account"))
    return response.status_code == HTTPStatus.OK


def change_password(client, current, new=NEW_PASSWORD, again=None):
    return client.post(
        reverse("accounts:password_change"),
        {
            "current_password": current,
            "new_password1": new,
            "new_password2": again if again is not None else new,
        },
    )


def sign_out_others(client, current):
    return client.post(
        reverse("accounts:sign_out_others"), {"current_password": current}
    )


def reauth_failures(user):
    return SecurityEvent.objects.filter(
        user=user, kind=Kind.SIGN_IN_FAILED, details__has_key="reauthentication"
    )


# --- The session key -----------------------------------------------------------


def test_rotating_the_session_key_changes_the_session_hash(casey):
    before = casey.get_session_auth_hash()

    casey.rotate_session_key()

    assert casey.get_session_auth_hash() != before
    casey.refresh_from_db()
    assert casey.session_key
    assert casey.check_password(PASSWORD)


def test_the_session_hash_still_covers_the_password(casey):
    before = casey.get_session_auth_hash()

    casey.set_password(NEW_PASSWORD)

    assert casey.get_session_auth_hash() != before


# --- Changing the password ------------------------------------------------------


def test_the_change_password_page_requires_sign_in(client, db):
    response = client.get(reverse("accounts:password_change"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_the_page_asks_for_the_current_password_first(signed_in):
    form = signed_in.get(reverse("accounts:password_change")).context["form"]

    assert list(form.fields) == ["current_password", "new_password1", "new_password2"]
    assert form.fields["current_password"].label == "Current password"


def test_changing_the_password_keeps_this_session_and_ends_the_other(
    signed_in, elsewhere, casey
):
    response = change_password(signed_in, PASSWORD)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    casey.refresh_from_db()
    assert casey.check_password(NEW_PASSWORD)
    assert is_signed_in(signed_in)
    assert not is_signed_in(elsewhere)


def test_a_wrong_current_password_changes_nothing(signed_in, elsewhere, casey):
    response = change_password(signed_in, "not-my-password")

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors["current_password"] == [
        "That isn't your current password."
    ]
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)
    assert is_signed_in(elsewhere)
    assert not SecurityEvent.objects.filter(kind=Kind.PASSWORD_CHANGED).exists()


def test_the_new_password_must_be_typed_twice_alike(signed_in, casey):
    response = change_password(signed_in, PASSWORD, again="something-else-77")

    assert "new_password2" in response.context["form"].errors
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)


def test_the_new_password_goes_through_the_validators(signed_in, casey):
    response = change_password(signed_in, PASSWORD, new="123")

    assert "new_password2" in response.context["form"].errors
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)


def test_a_password_change_is_recorded(signed_in, casey):
    signed_in.post(
        reverse("accounts:password_change"),
        {
            "current_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
        REMOTE_ADDR="203.0.113.9",
    )

    event = SecurityEvent.objects.get(kind=Kind.PASSWORD_CHANGED)
    assert event.user == casey
    assert event.actor == casey
    assert event.ip_address == "203.0.113.9"
    assert event.details == {}


def test_a_password_change_sends_one_alert(signed_in, casey):
    change_password(signed_in, PASSWORD)

    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert "password" in alert.subject.lower()
    assert "password for your ThoughtTronix account was changed" in alert.body
    assert "This happened at" in alert.body
    assert alert.body.rstrip().splitlines()[-3] == "Wasn't you? Contact support."
    assert NEW_PASSWORD not in alert.body


def test_an_account_with_no_email_changes_its_password_without_an_alert(
    client, customer
):
    client.force_login(customer)

    response = change_password(client, "customer123")

    assert response.status_code == HTTPStatus.FOUND
    assert mail.outbox == []
    assert SecurityEvent.objects.filter(kind=Kind.PASSWORD_CHANGED).exists()


def test_the_hub_shows_the_new_last_changed_time(signed_in, casey):
    assert (
        "Never changed" in signed_in.get(reverse("accounts:account")).content.decode()
    )

    response = change_password(signed_in, PASSWORD)
    hub = signed_in.get(response.url)

    changed = SecurityEvent.objects.get(kind=Kind.PASSWORD_CHANGED).created_at
    assert hub.context["password_last_changed"] == changed
    page = hub.content.decode()
    assert "Last changed" in page
    assert "Never changed" not in page
    assert "Every other device has been signed out" in page


# --- Signing out other devices -------------------------------------------------


def test_the_hub_offers_sign_out_of_other_devices(signed_in):
    page = signed_in.get(reverse("accounts:account")).content.decode()

    assert reverse("accounts:sign_out_others") in page
    assert "Sign out of all other devices" in page


def test_sign_out_others_ends_the_other_session_and_not_this_one(
    signed_in, elsewhere, casey
):
    response = sign_out_others(signed_in, PASSWORD)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    assert is_signed_in(signed_in)
    assert not is_signed_in(elsewhere)


def test_sign_out_others_leaves_the_password_alone(signed_in, casey):
    sign_out_others(signed_in, PASSWORD)

    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)
    assert not SecurityEvent.objects.filter(kind=Kind.PASSWORD_CHANGED).exists()


def test_sign_out_others_is_recorded(signed_in, casey):
    sign_out_others(signed_in, PASSWORD)

    event = SecurityEvent.objects.get(kind=Kind.OTHER_SESSIONS_ENDED)
    assert event.user == casey
    assert event.actor == casey


def test_sign_out_others_with_a_wrong_password_reshows_the_hub(
    signed_in, elsewhere, casey
):
    response = sign_out_others(signed_in, "not-my-password")

    assert response.status_code == HTTPStatus.OK
    assert "accounts/account.html" in [t.name for t in response.templates]
    assert response.context["form"].errors["current_password"] == [
        "That isn't your current password."
    ]
    # The rest of the page is all there too.
    assert "Recent security activity" in response.content.decode()
    assert is_signed_in(elsewhere)
    assert not SecurityEvent.objects.filter(kind=Kind.OTHER_SESSIONS_ENDED).exists()


def test_sign_out_others_is_post_only(signed_in):
    response = signed_in.get(reverse("accounts:sign_out_others"))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_the_hub_itself_takes_no_posts(signed_in, elsewhere):
    response = signed_in.post(
        reverse("accounts:account"), {"current_password": PASSWORD}
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert is_signed_in(elsewhere)


def test_sign_out_others_requires_sign_in(client, db):
    response = sign_out_others(client, PASSWORD)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


# --- Wrong answers count toward the cooldown ------------------------------------


@pytest.mark.parametrize(
    ("submit", "purpose"),
    [(change_password, "password_change"), (sign_out_others, "sign_out_others")],
)
def test_a_wrong_current_password_counts_toward_the_cooldown(
    signed_in, casey, submit, purpose
):
    submit(signed_in, "not-my-password")

    failure = reauth_failures(casey).get()
    assert failure.details == {"reauthentication": purpose}
    assert failure.actor is None
    standing = security.sign_in_standing(casey)
    assert standing.attempts_left == security.COOLDOWN_THRESHOLD - 1


def test_five_wrong_answers_pause_sign_in_for_the_account(signed_in, casey):
    for submit in [change_password, sign_out_others] * 2 + [change_password]:
        submit(signed_in, "not-my-password")

    assert security.is_cooling_down(casey)
    # The pause is the account's, so the sign-in page refuses too.
    other = Client()
    other.post(reverse("accounts:login"), {"username": "casey", "password": PASSWORD})
    assert "_auth_user_id" not in other.session


def test_while_paused_the_right_password_is_refused_unchecked(signed_in, casey):
    for _ in range(security.COOLDOWN_THRESHOLD):
        change_password(signed_in, "not-my-password")
    recorded = reauth_failures(casey).count()

    response = change_password(signed_in, PASSWORD)

    assert response.context["form"].errors["current_password"] == [
        "Too many failed attempts. Try again in 15 minutes."
    ]
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)
    # Refused attempts during a pause are never recorded.
    assert reauth_failures(casey).count() == recorded


def test_a_right_answer_does_not_record_a_failure(signed_in, casey):
    sign_out_others(signed_in, PASSWORD)
    change_password(signed_in, PASSWORD)

    assert not reauth_failures(casey).exists()
