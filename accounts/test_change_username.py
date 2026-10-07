"""Changing the username: sign-up's rules, the current password, and the trail.

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


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def drew(db):
    return User.objects.create_user(
        username="drew", password="drew-pass-123", email="drew@example.com"
    )


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


def is_signed_in(client):
    response = client.get(reverse("accounts:account"))
    return response.status_code == HTTPStatus.OK


def rename(client, username, current=PASSWORD, **extra):
    return client.post(
        reverse("accounts:change_username"),
        {"current_password": current, "username": username},
        **extra,
    )


def errors(response):
    return response.context["form"].errors


# --- The page ----------------------------------------------------------------------


def test_the_page_requires_sign_in(client, db):
    response = client.get(reverse("accounts:change_username"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_the_page_asks_for_the_current_password_and_the_new_name(signed_in):
    form = signed_in.get(reverse("accounts:change_username")).context["form"]

    assert list(form.fields) == ["current_password", "username"]
    assert form.fields["current_password"].label == "Current password"
    assert form.fields["username"].label == "New username"


def test_the_hub_links_to_the_page(signed_in):
    page = signed_in.get(reverse("accounts:account")).content.decode()

    assert reverse("accounts:change_username") in page


# --- A valid rename ----------------------------------------------------------------


def test_a_valid_rename_takes_effect_and_keeps_the_user_signed_in(signed_in, casey):
    elsewhere = Client()
    elsewhere.force_login(casey)

    response = rename(signed_in, "casey_r")

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    casey.refresh_from_db()
    assert casey.username == "casey_r"
    assert is_signed_in(signed_in)
    assert is_signed_in(elsewhere)
    hub = signed_in.get(response.url).content.decode()
    assert "casey_r" in hub


def test_the_new_name_signs_in_and_the_old_one_does_not(signed_in, db):
    rename(signed_in, "casey_r")

    old, new = Client(), Client()
    old.post(reverse("accounts:login"), {"username": "casey", "password": PASSWORD})
    new.post(reverse("accounts:login"), {"username": "casey_r", "password": PASSWORD})
    assert "_auth_user_id" not in old.session
    assert "_auth_user_id" in new.session


def test_recapitalising_your_own_username_is_allowed(signed_in, casey):
    response = rename(signed_in, "Casey")

    assert response.status_code == HTTPStatus.FOUND
    casey.refresh_from_db()
    assert casey.username == "Casey"


# --- Sign-up's rules ---------------------------------------------------------------


@pytest.mark.parametrize("taken", ["drew", "Drew", "DREW"])
def test_a_name_another_account_has_is_refused_in_any_case(
    signed_in, casey, drew, taken
):
    response = rename(signed_in, taken)

    assert response.status_code == HTTPStatus.OK
    assert errors(response)["username"] == ["A user with that username already exists."]
    casey.refresh_from_db()
    assert casey.username == "casey"


def test_a_name_containing_an_at_sign_is_refused(signed_in, casey):
    response = rename(signed_in, "casey@home")

    assert "can't contain @" in errors(response)["username"][0]
    casey.refresh_from_db()
    assert casey.username == "casey"


def test_a_name_with_characters_usernames_cannot_have_is_refused(signed_in, casey):
    response = rename(signed_in, "casey monroe")

    assert errors(response)["username"]
    casey.refresh_from_db()
    assert casey.username == "casey"


def test_the_name_you_already_have_is_refused(signed_in):
    response = rename(signed_in, "casey")

    assert errors(response)["username"] == ["That's already your username."]
    assert not SecurityEvent.objects.filter(kind=Kind.USERNAME_CHANGED).exists()


def test_a_refused_name_does_not_leak_into_the_page(signed_in, drew):
    response = rename(signed_in, "drew")

    assert response.context["user"].username == "casey"


# --- The current password ----------------------------------------------------------


def test_a_wrong_current_password_refuses_the_change(signed_in, casey):
    response = rename(signed_in, "casey_r", current="not-my-password")

    assert response.status_code == HTTPStatus.OK
    assert errors(response)["current_password"] == ["That isn't your current password."]
    casey.refresh_from_db()
    assert casey.username == "casey"
    assert not SecurityEvent.objects.filter(kind=Kind.USERNAME_CHANGED).exists()
    assert mail.outbox == []


def test_a_wrong_current_password_counts_toward_the_cooldown(signed_in, casey):
    rename(signed_in, "casey_r", current="not-my-password")

    failure = SecurityEvent.objects.get(user=casey, kind=Kind.SIGN_IN_FAILED)
    assert failure.details == {"reauthentication": "change_username"}
    standing = security.sign_in_standing(casey)
    assert standing.attempts_left == security.COOLDOWN_THRESHOLD - 1


def test_while_paused_the_right_password_is_refused(signed_in, casey):
    for _ in range(security.COOLDOWN_THRESHOLD):
        rename(signed_in, "casey_r", current="not-my-password")
    assert security.is_cooling_down(casey)

    response = rename(signed_in, "casey_r")

    assert errors(response)["current_password"] == [
        "Too many failed attempts. Try again in 15 minutes."
    ]
    casey.refresh_from_db()
    assert casey.username == "casey"


# --- The trail ---------------------------------------------------------------------


def test_a_rename_is_recorded_with_the_old_and_new_names(signed_in, casey):
    rename(signed_in, "casey_r", REMOTE_ADDR="203.0.113.9")

    event = SecurityEvent.objects.get(kind=Kind.USERNAME_CHANGED)
    assert event.user == casey
    assert event.actor == casey
    assert event.details == {"old": "casey", "new": "casey_r"}
    assert event.username == "casey_r"
    assert event.ip_address == "203.0.113.9"


def test_a_rename_appears_in_the_activity_card(signed_in):
    response = rename(signed_in, "casey_r")

    events = signed_in.get(response.url).context["events"]
    assert events[0].kind == Kind.USERNAME_CHANGED
    assert not events[0].by_support


def test_a_rename_sends_one_alert(signed_in):
    rename(signed_in, "casey_r")

    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert "username" in alert.subject.lower()
    assert 'changed from "casey" to "casey_r"' in alert.body
    assert "This happened at" in alert.body
    assert alert.body.rstrip().splitlines()[-3] == "Wasn't you? Contact support."
    assert PASSWORD not in alert.body


def test_an_account_with_no_email_is_renamed_without_an_alert(client, customer):
    client.force_login(customer)

    response = rename(client, "customer_two", current="customer123")

    assert response.status_code == HTTPStatus.FOUND
    assert mail.outbox == []
    assert SecurityEvent.objects.filter(kind=Kind.USERNAME_CHANGED).exists()


def test_an_admin_rename_records_the_admin_as_actor(casey, db):
    admin = User.objects.create_superuser(username="root", password="x")
    casey.username = "casey_r"
    casey.save()

    security.username_changed(casey, "casey", actor=admin)

    event = SecurityEvent.objects.get(kind=Kind.USERNAME_CHANGED)
    assert event.actor == admin
    assert event.by_support
    assert event.details == {"old": "casey", "new": "casey_r"}
