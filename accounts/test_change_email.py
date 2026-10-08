"""Changing the email address: the request, the link to the new address, the switch.

Asking changes nothing; following the link mailed to the new address
does. Tokens issued at a pinned moment stand in for waiting a day.
"""

import re
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
OLD = "casey@example.com"
NEW = "casey.r@example.com"
LINK = re.compile(r"https?://\S+(/accounts/email/confirm/\S+/)")


@pytest.fixture
def casey(db):
    return User.objects.create_user(username="casey", password=PASSWORD, email=OLD)


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


def ask(client, email, current=PASSWORD, **extra):
    return client.post(
        reverse("accounts:change_email"),
        {"current_password": current, "email": email},
        **extra,
    )


def link_in(message):
    match = LINK.search(message.body)
    assert match, message.body
    return match.group(1)


def confirm_url(user, new_email=NEW, **kwargs):
    return reverse(
        "accounts:confirm_email_change",
        args=[security.make_email_change_token(user, new_email, **kwargs)],
    )


def signs_in_with(identifier):
    client = Client()
    client.post(
        reverse("accounts:login"), {"username": identifier, "password": PASSWORD}
    )
    return "_auth_user_id" in client.session


def errors(response):
    return response.context["form"].errors


def confirmed_events(user):
    return user.security_events.filter(kind=Kind.EMAIL_CHANGE_CONFIRMED)


# --- The page ----------------------------------------------------------------------


def test_the_page_requires_sign_in(client, db):
    response = client.get(reverse("accounts:change_email"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_the_page_asks_for_the_current_password_and_the_new_address(signed_in):
    form = signed_in.get(reverse("accounts:change_email")).context["form"]

    assert list(form.fields) == ["current_password", "email"]
    assert form.fields["current_password"].label == "Current password"
    assert form.fields["email"].label == "New email address"


def test_the_hub_links_to_the_page(signed_in):
    page = signed_in.get(reverse("accounts:account")).content.decode()

    assert reverse("accounts:change_email") in page


def test_the_no_email_banner_links_to_the_page(client, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    client.force_login(nobody)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Add an email" in page
    assert reverse("accounts:change_email") in page


# --- Asking ------------------------------------------------------------------------


def test_asking_mails_a_link_to_the_new_address_and_changes_nothing(signed_in, casey):
    security.mark_email_verified(casey)

    response = ask(signed_in, NEW)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [NEW]
    assert "Confirm your new email" in mail.outbox[0].subject
    casey.refresh_from_db()
    assert casey.email == OLD
    assert casey.email_verified


def test_asking_is_recorded(signed_in, casey):
    ask(signed_in, NEW, REMOTE_ADDR="203.0.113.7")

    event = casey.security_events.get(kind=Kind.EMAIL_CHANGE_REQUESTED)
    assert event.actor == casey
    assert event.ip_address == "203.0.113.7"
    assert event.details == {"old": OLD, "new": NEW}


def test_the_message_says_the_old_address_stays(signed_in):
    response = ask(signed_in, NEW)

    hub = signed_in.get(response.url).content.decode()
    assert f"Your email stays {OLD}" in hub


def test_before_confirmation_the_old_address_still_signs_in_and_resets(
    signed_in, casey
):
    ask(signed_in, NEW)

    assert signs_in_with(OLD)
    assert not signs_in_with(NEW)
    assert list(PasswordResetForm().get_users(OLD)) == [casey]
    assert list(PasswordResetForm().get_users(NEW)) == []


def test_a_wrong_password_sends_nothing_and_counts_toward_the_cooldown(
    signed_in, casey
):
    response = ask(signed_in, NEW, current="wrong-pass")

    assert response.status_code == HTTPStatus.OK
    assert "current_password" in errors(response)
    assert not mail.outbox
    failure = casey.security_events.get(kind=Kind.SIGN_IN_FAILED)
    assert failure.details == {"reauthentication": "change_email"}
    assert not casey.security_events.filter(kind=Kind.EMAIL_CHANGE_REQUESTED).exists()


def test_an_address_another_account_uses_is_refused_in_any_case(signed_in, db):
    User.objects.create_user(
        username="drew", password="drew-pass-123", email="drew@example.com"
    )

    response = ask(signed_in, "Drew@Example.COM")

    assert errors(response)["email"] == [
        "An account with that email address already exists."
    ]
    assert not mail.outbox


def test_your_own_address_is_refused(signed_in):
    response = ask(signed_in, OLD)

    assert errors(response)["email"] == ["That's already your email address."]
    assert not mail.outbox


def test_recapitalising_your_own_address_is_allowed(signed_in, casey):
    ask(signed_in, "Casey@Example.com")

    assert mail.outbox[0].to == ["Casey@Example.com"]


def test_a_malformed_address_is_refused(signed_in):
    response = ask(signed_in, "not-an-email")

    assert "email" in errors(response)
    assert not mail.outbox


# --- Confirming --------------------------------------------------------------------


def test_the_mailed_link_switches_the_email_and_marks_it_verified(signed_in, casey):
    ask(signed_in, NEW)

    response = signed_in.post(link_in(mail.outbox[0]))

    assert response.url == reverse("accounts:account")
    casey.refresh_from_db()
    assert casey.email == NEW
    assert casey.email_verified
    assert signs_in_with(NEW)
    assert not signs_in_with(OLD)


def test_confirming_is_recorded_with_both_addresses(client, casey):
    client.post(confirm_url(casey), REMOTE_ADDR="203.0.113.7")

    event = confirmed_events(casey).get()
    assert event.actor == casey
    assert event.ip_address == "203.0.113.7"
    assert event.details == {"old": OLD, "new": NEW}


def test_confirming_tells_the_old_address(client, casey):
    client.post(confirm_url(casey))

    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == [OLD]
    assert "email address was changed" in notice.subject
    assert OLD in notice.body
    assert NEW in notice.body
    assert "Wasn't you? Contact support." in notice.body


def test_confirming_works_without_signing_in(client, casey):
    response = client.post(confirm_url(casey))

    assert response.url == reverse("accounts:login")
    casey.refresh_from_db()
    assert casey.email == NEW


def test_an_account_with_no_email_can_add_one_and_nobody_is_notified(client, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    client.force_login(nobody)

    ask(client, "nobody@example.com")
    client.post(link_in(mail.outbox[0]))

    nobody.refresh_from_db()
    assert nobody.email == "nobody@example.com"
    assert nobody.email_verified
    assert len(mail.outbox) == 1


def test_get_on_the_link_changes_nothing(client, casey):
    response = client.get(confirm_url(casey))

    assert response.status_code == HTTPStatus.OK
    assert NEW in response.content.decode()
    casey.refresh_from_db()
    assert casey.email == OLD
    assert not confirmed_events(casey).exists()
    assert not mail.outbox


def test_an_address_taken_in_the_meantime_is_refused(client, casey):
    url = confirm_url(casey)
    User.objects.create_user(
        username="drew", password="drew-pass-123", email="Casey.R@example.com"
    )

    page = client.get(url)
    response = client.post(url)

    assert "That address is taken" in page.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "That address is taken" in response.content.decode()
    casey.refresh_from_db()
    assert casey.email == OLD
    assert not confirmed_events(casey).exists()
    assert not mail.outbox


def test_the_switch_itself_rechecks_uniqueness(casey):
    User.objects.create_user(
        username="drew", password="drew-pass-123", email=NEW.upper()
    )

    assert security.change_email(casey, NEW) is False
    casey.refresh_from_db()
    assert casey.email == OLD


def test_a_link_works_until_24_hours_old(client, casey):
    url = confirm_url(casey, at=timezone.now() - timedelta(hours=23, minutes=59))

    client.post(url)

    casey.refresh_from_db()
    assert casey.email == NEW


def test_a_link_older_than_24_hours_is_refused(client, casey):
    url = confirm_url(casey, at=timezone.now() - timedelta(hours=24, minutes=1))

    page = client.get(url)
    client.post(url)

    assert page.context["change"] is None
    assert "doesn't work" in page.content.decode()
    casey.refresh_from_db()
    assert casey.email == OLD


def test_the_age_is_checked_against_the_clock(casey):
    # Tokens are stamped to the second.
    issued = timezone.now().replace(microsecond=0)
    token = security.make_email_change_token(casey, NEW, at=issued)

    on_time = issued + security.EMAIL_CHANGE_MAX_AGE
    late = on_time + timedelta(seconds=1)

    assert security.email_change_for_token(token, now=on_time).user == casey
    assert security.email_change_for_token(token, now=late) is None


def test_a_link_is_refused_once_the_email_has_changed_since(client, casey):
    url = confirm_url(casey)
    casey.email = "casey.other@example.com"
    casey.save()

    client.post(url)

    casey.refresh_from_db()
    assert casey.email == "casey.other@example.com"
    assert not confirmed_events(casey).exists()


def test_confirming_one_link_kills_the_others(client, casey):
    first = confirm_url(casey, "first@example.com")
    second = confirm_url(casey, "second@example.com")

    client.post(first)
    client.post(second)

    casey.refresh_from_db()
    assert casey.email == "first@example.com"


def test_a_link_works_once(client, casey):
    url = confirm_url(casey)

    client.post(url)
    client.post(url)

    assert confirmed_events(casey).count() == 1


def test_a_tampered_link_is_refused(client, casey):
    token = security.make_email_change_token(casey, NEW)

    response = client.post(
        reverse("accounts:confirm_email_change", args=[token[:-1] + "x"])
    )

    assert response.context["change"] is None
    casey.refresh_from_db()
    assert casey.email == OLD


def test_a_verification_link_for_the_old_address_dies_with_it(client, casey):
    verify = reverse(
        "accounts:verify_email", args=[security.make_verification_token(casey)]
    )

    client.post(confirm_url(casey))

    assert client.get(verify).context["target"] is None


def test_the_token_carries_no_password_or_secret(casey):
    token = security.make_email_change_token(casey, NEW)

    assert PASSWORD not in token
    assert casey.password not in token


def test_the_activity_card_lists_the_change(client, casey):
    client.post(confirm_url(casey))
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Email changed" in page
