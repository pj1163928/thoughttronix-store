"""Resetting a forgotten password by an emailed link.

The pages are Django's own reset views, restyled; these tests pin down
what the PRD adds on top: one answer for every address, an hour's life,
every session ended, and the audit trail. "A session elsewhere" is a
second test client signed in as the same user.
"""

import re
from datetime import datetime, timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client
from django.urls import resolve, reverse

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
NEW_PASSWORD = "synaptic-velvet-42"
EMAIL = "casey@example.com"
LINK = re.compile(r"https?://\S+(/accounts/password/reset/[^/\s]+/[^/\s]+/)")
CSRF = re.compile(r'("X-CSRFToken": "|name="csrfmiddlewaretoken" value=")[^"]+')


@pytest.fixture
def casey(db):
    return User.objects.create_user(username="casey", password=PASSWORD, email=EMAIL)


@pytest.fixture
def clock(monkeypatch):
    """Pins the reset tokens' clock; move it by setting ``clock.now``.

    Django's token generator reads naive local time through ``_now``,
    which it provides for exactly this.
    """

    class Clock:
        now = datetime(2026, 10, 7, 12, 0)

    pinned = Clock()
    monkeypatch.setattr(default_token_generator, "_now", lambda: pinned.now)
    return pinned


def request_reset(client, email=EMAIL):
    return client.post(reverse("accounts:password_reset"), {"email": email})


def emailed_link(client=None, email=EMAIL):
    """Ask for a reset and return the path of the link that was mailed."""
    mail.outbox.clear()
    request_reset(client or Client(), email)
    assert len(mail.outbox) == 1
    match = LINK.search(mail.outbox[0].body)
    assert match, mail.outbox[0].body
    mail.outbox.clear()
    return match.group(1)


def set_new_password(client, link, password=NEW_PASSWORD, again=None):
    """Follow a reset link as a browser does, then submit the new password."""
    landing = client.get(link)
    if landing.status_code != HTTPStatus.FOUND:
        return landing
    return client.post(
        landing.url,
        {
            "new_password1": password,
            "new_password2": again if again is not None else password,
        },
    )


def is_signed_in(client):
    return client.get(reverse("accounts:account")).status_code == HTTPStatus.OK


def signs_in_with(password, identifier="casey"):
    client = Client()
    client.post(
        reverse("accounts:login"), {"username": identifier, "password": password}
    )
    return "_auth_user_id" in client.session


def link_is_valid(link):
    """Whether a fresh browser opening ``link`` would be shown the form."""
    return Client().get(link).status_code == HTTPStatus.FOUND


def without_csrf(response):
    return CSRF.sub(r"\1…", response.content.decode())


# --- Asking for a link ---------------------------------------------------------------


def test_the_request_page_needs_no_sign_in(client, db):
    response = client.get(reverse("accounts:password_reset"))

    assert response.status_code == HTTPStatus.OK
    assert list(response.context["form"].fields) == ["email"]


def test_the_sign_in_page_links_to_it(client, db):
    page = client.get(reverse("accounts:login")).content.decode()

    assert reverse("accounts:password_reset") in page
    assert "Forgot your password?" in page


def test_the_change_password_page_links_to_it(client, casey):
    client.force_login(casey)

    page = client.get(reverse("accounts:password_change")).content.decode()

    assert reverse("accounts:password_reset") in page


def test_a_known_and_an_unknown_address_get_the_same_answer(casey):
    known = request_reset(Client(), EMAIL)
    unknown = request_reset(Client(), "nobody@example.com")

    assert known.status_code == unknown.status_code == HTTPStatus.FOUND
    assert known.url == unknown.url == reverse("accounts:password_reset_done")
    assert without_csrf(Client().get(known.url)) == without_csrf(
        Client().get(unknown.url)
    )
    assert [message.to for message in mail.outbox] == [[EMAIL]]


def test_a_locked_account_gets_no_link_and_the_same_answer(casey):
    casey.is_active = False
    casey.save()

    response = request_reset(Client())

    assert response.url == reverse("accounts:password_reset_done")
    assert not mail.outbox
    assert not casey.security_events.filter(kind=Kind.PASSWORD_RESET_REQUESTED).exists()


def test_the_address_matches_in_any_case_and_need_not_be_verified(casey):
    assert not casey.email_verified

    request_reset(Client(), "CASEY@Example.COM")

    assert [message.to for message in mail.outbox] == [[EMAIL]]


def test_a_request_is_logged_only_when_an_account_matched(casey):
    request_reset(Client(), EMAIL)
    event = SecurityEvent.objects.get()
    assert event.kind == Kind.PASSWORD_RESET_REQUESTED
    assert event.user == casey
    assert event.actor is None
    assert event.ip_address == "127.0.0.1"

    request_reset(Client(), "nobody@example.com")

    assert SecurityEvent.objects.count() == 1


def test_the_email_links_to_the_namespaced_confirm_page_and_says_an_hour(casey):
    request_reset(Client())

    message = mail.outbox[0]
    assert message.subject == "ThoughtTronix: Reset your password"
    assert "for 1 hour." in message.body
    link = LINK.search(message.body).group(1)
    assert resolve(link).view_name == "accounts:password_reset_confirm"


def test_reset_links_last_an_hour(settings):
    assert settings.PASSWORD_RESET_TIMEOUT == 3600


# --- Following the link --------------------------------------------------------------


def test_opening_the_link_changes_nothing(casey):
    link = emailed_link()
    client = Client()

    landing = client.get(link)
    form_page = client.get(landing.url)

    assert landing.status_code == HTTPStatus.FOUND
    assert form_page.context["validlink"]
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)
    assert not casey.security_events.filter(kind=Kind.PASSWORD_RESET_COMPLETED).exists()


def test_the_link_sets_a_new_password_and_signs_nobody_in(casey):
    client = Client()

    response = set_new_password(client, emailed_link())

    assert response.url == reverse("accounts:password_reset_complete")
    assert "_auth_user_id" not in client.session
    assert signs_in_with(NEW_PASSWORD)
    assert not signs_in_with(PASSWORD)


def test_the_link_works_only_once(casey):
    link = emailed_link()
    set_new_password(Client(), link)

    response = set_new_password(Client(), link, password="another-secret-77")

    assert response.status_code == HTTPStatus.OK
    assert not response.context["validlink"]
    assert "This link doesn't work" in response.content.decode()
    assert signs_in_with(NEW_PASSWORD)


def test_the_link_expires_after_an_hour(casey, clock):
    issued = clock.now
    link = emailed_link()

    clock.now = issued + timedelta(minutes=59)
    assert link_is_valid(link)

    clock.now = issued + timedelta(hours=1, seconds=1)
    assert not link_is_valid(link)


def test_the_link_dies_if_the_password_changes_first(casey):
    link = emailed_link()
    casey.set_password("changed-meanwhile-9")
    casey.save()

    assert not link_is_valid(link)


def test_a_tampered_link_is_refused(client, casey):
    link = emailed_link()
    tampered = link[:-2] + ("a" if link[-2] != "a" else "b") + "/"

    response = client.get(tampered)

    assert response.status_code == HTTPStatus.OK
    assert not response.context["validlink"]


def test_mismatched_new_passwords_change_nothing(casey):
    response = set_new_password(Client(), emailed_link(), again="something-else-1")

    assert response.status_code == HTTPStatus.OK
    assert "new_password2" in response.context["form"].errors
    assert signs_in_with(PASSWORD)
    assert not mail.outbox
    assert not casey.security_events.filter(kind=Kind.PASSWORD_RESET_COMPLETED).exists()


# --- After the reset ---------------------------------------------------------------


def test_completing_a_reset_signs_out_every_session(casey):
    laptop, phone = Client(), Client()
    laptop.force_login(casey)
    phone.force_login(casey)
    assert casey.user_sessions.count() == 2

    set_new_password(Client(), emailed_link())

    assert not is_signed_in(laptop)
    assert not is_signed_in(phone)
    assert not casey.user_sessions.exists()


def test_resetting_from_a_signed_in_browser_leaves_it_signed_out(client, casey):
    client.force_login(casey)

    set_new_password(client, emailed_link(client))

    assert not is_signed_in(client)


def test_a_completed_reset_is_logged_and_alerted(casey):
    set_new_password(Client(), emailed_link())

    event = casey.security_events.get(kind=Kind.PASSWORD_RESET_COMPLETED)
    assert event.actor == casey
    assert event.ip_address == "127.0.0.1"
    [alert] = mail.outbox
    assert alert.to == [EMAIL]
    assert alert.subject == "ThoughtTronix: Your password was reset"
    assert "every device signed in to it was signed out" in alert.body
    assert alert.body.rstrip().endswith(
        "Wasn't you? Contact support.\n\n— The ThoughtTronix Store"
    )


def test_the_hub_counts_a_reset_as_the_password_last_changing(client, casey):
    set_new_password(Client(), emailed_link())
    event = casey.security_events.get(kind=Kind.PASSWORD_RESET_COMPLETED)
    # The new password is in the database, not yet on this instance.
    casey.refresh_from_db()
    client.force_login(casey)

    response = client.get(reverse("accounts:account"))

    assert response.context["password_last_changed"] == event.created_at
    assert "Never changed" not in response.content.decode()


def test_a_completed_reset_alerts_nobody_on_an_account_without_email(db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)

    security.password_reset_completed(nobody)

    assert not mail.outbox
    assert nobody.security_events.filter(kind=Kind.PASSWORD_RESET_COMPLETED).exists()


# --- Every step stays inside the namespace -------------------------------------------


def test_no_reset_step_redirects_to_an_unnamespaced_url(casey):
    client = Client()

    asked = request_reset(client)
    assert asked.url == reverse("accounts:password_reset_done")

    link = LINK.search(mail.outbox[0].body).group(1)
    landing = client.get(link)
    assert resolve(landing.url).view_name == "accounts:password_reset_confirm"

    done = client.post(
        landing.url,
        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert done.url == reverse("accounts:password_reset_complete")

    complete = client.get(done.url)
    assert complete.status_code == HTTPStatus.OK
    assert complete.context["login_url"] == reverse("accounts:login")
