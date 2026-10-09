"""Verifying an email address: the link, the button behind it, and the hub's prompt.

A link is a signed token carrying the account and the address it was sent
to. Tokens issued at a pinned moment stand in for waiting a day.
"""

import re
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
LINK = re.compile(r"https?://\S+(/accounts/email/verify/\S+/)")


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


def link_in(message):
    match = LINK.search(message.body)
    assert match, message.body
    return match.group(1)


def verify_url(user, **kwargs):
    return reverse(
        "accounts:verify_email",
        args=[security.make_verification_token(user, **kwargs)],
    )


def verified_events(user):
    return user.security_events.filter(kind=Kind.EMAIL_VERIFIED)


# --- Sign-up -----------------------------------------------------------------


def test_signup_emails_a_verification_link_and_the_account_works_at_once(client, db):
    response = client.post(
        reverse("accounts:signup"),
        {
            "username": "drew",
            "email": "Drew@Example.com",
            "password1": "a-long-passphrase-42",
            "password2": "a-long-passphrase-42",
        },
    )
    assert response.status_code == HTTPStatus.FOUND

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["Drew@Example.com"]
    assert "Confirm your email" in message.subject
    assert link_in(message).startswith("/accounts/email/verify/")

    drew = User.objects.get(username="drew")
    assert not drew.email_verified
    signed_in = client.post(
        reverse("accounts:login"),
        {"username": "drew", "password": "a-long-passphrase-42"},
    )
    assert signed_in.status_code == HTTPStatus.FOUND
    assert client.get(reverse("accounts:account")).status_code == HTTPStatus.OK


def test_the_emailed_link_verifies_the_account(client, db):
    client.post(
        reverse("accounts:signup"),
        {
            "username": "drew",
            "email": "drew@example.com",
            "password1": "a-long-passphrase-42",
            "password2": "a-long-passphrase-42",
        },
    )
    client.post(link_in(mail.outbox[0]))

    assert User.objects.get(username="drew").email_verified


def test_the_link_printed_to_the_console_can_be_copied_and_used(
    client, casey, settings, capsys
):
    # ``mail.outbox`` holds messages before they're encoded, which is how
    # a console link broken up by quoted-printable once slipped past.
    settings.EMAIL_BACKEND = "config.mail.ConsoleEmailBackend"
    security.send_verification_email(casey, RequestFactory().get("/"))
    printed = capsys.readouterr().out

    assert "Content-Transfer-Encoding: 8bit" in printed
    client.post(LINK.search(printed).group(1))

    casey.refresh_from_db()
    assert casey.email_verified


# --- The link ------------------------------------------------------------------


def test_get_on_a_link_changes_nothing(client, casey):
    response = client.get(verify_url(casey))

    assert response.status_code == HTTPStatus.OK
    assert "casey@example.com" in response.content.decode()
    casey.refresh_from_db()
    assert casey.email_verified_at is None
    assert not verified_events(casey).exists()


def test_post_verifies_without_signing_in(client, casey):
    response = client.post(verify_url(casey), REMOTE_ADDR="203.0.113.7")

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:login")
    casey.refresh_from_db()
    assert casey.email_verified
    event = verified_events(casey).get()
    assert event.actor == casey
    assert event.ip_address == "203.0.113.7"
    assert event.details == {"email": "casey@example.com"}


def test_a_signed_in_owner_goes_back_to_the_account_page(client, casey):
    client.force_login(casey)

    response = client.post(verify_url(casey))

    assert response.url == reverse("accounts:account")


def test_a_link_works_until_24_hours_old(client, casey):
    url = verify_url(casey, at=timezone.now() - timedelta(hours=23, minutes=59))

    client.post(url)

    casey.refresh_from_db()
    assert casey.email_verified


def test_a_link_older_than_24_hours_is_refused(client, casey):
    url = verify_url(casey, at=timezone.now() - timedelta(hours=24, minutes=1))

    page = client.get(url)
    client.post(url)

    assert page.context["target"] is None
    assert "doesn't work" in page.content.decode()
    casey.refresh_from_db()
    assert casey.email_verified_at is None
    assert not verified_events(casey).exists()


def test_the_age_is_checked_against_the_clock(casey):
    # Tokens are stamped to the second.
    issued = timezone.now().replace(microsecond=0)
    token = security.make_verification_token(casey, at=issued)

    on_time = issued + security.EMAIL_VERIFICATION_MAX_AGE
    late = on_time + timedelta(seconds=1)

    assert security.user_for_verification_token(token, now=on_time) == casey
    assert security.user_for_verification_token(token, now=late) is None


def test_a_link_for_an_email_the_account_no_longer_has_is_refused(client, casey):
    url = verify_url(casey)
    casey.email = "casey.new@example.com"
    casey.save()

    client.post(url)

    casey.refresh_from_db()
    assert casey.email_verified_at is None


def test_a_tampered_link_is_refused(client, casey):
    token = security.make_verification_token(casey)

    response = client.post(
        reverse("accounts:verify_email", args=[token[:-1] + "x"]),
    )

    assert response.context["target"] is None
    casey.refresh_from_db()
    assert casey.email_verified_at is None


def test_a_link_for_a_deleted_account_is_refused(client, casey):
    url = verify_url(casey)
    casey.delete()

    assert client.get(url).context["target"] is None


def test_verifying_twice_records_one_event(client, casey):
    url = verify_url(casey)

    client.post(url)
    client.post(url)

    assert verified_events(casey).count() == 1


def test_the_token_carries_no_password_or_secret(casey):
    token = security.make_verification_token(casey)

    assert PASSWORD not in token
    assert casey.password not in token


# --- Resending -------------------------------------------------------------------


def test_resend_sends_a_fresh_link(client, casey):
    client.force_login(casey)

    response = client.post(reverse("accounts:send_verification"))

    assert response.url == reverse("accounts:account")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["casey@example.com"]
    client.post(link_in(mail.outbox[0]))
    casey.refresh_from_db()
    assert casey.email_verified


def test_resend_is_post_only(client, casey):
    client.force_login(casey)

    response = client.get(reverse("accounts:send_verification"))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert not mail.outbox


def test_resend_requires_sign_in(client, casey):
    response = client.post(reverse("accounts:send_verification"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))
    assert not mail.outbox


def test_resend_sends_nothing_once_verified(client, casey):
    security.mark_email_verified(casey)
    client.force_login(casey)

    client.post(reverse("accounts:send_verification"))

    assert not mail.outbox


def test_resend_sends_nothing_without_an_email(client, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    client.force_login(nobody)

    response = client.post(reverse("accounts:send_verification"))

    assert response.status_code == HTTPStatus.FOUND
    assert not mail.outbox


# --- The Account page --------------------------------------------------------------


def test_the_hub_offers_a_resend_for_an_unverified_email(client, casey):
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Email not verified" in page
    assert reverse("accounts:send_verification") in page
    assert ">Verified<" not in page


def test_the_hub_shows_the_verified_badge_once_verified(client, casey):
    security.mark_email_verified(casey)
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert ">Verified<" in page
    assert "Email not verified" not in page
    assert reverse("accounts:send_verification") not in page


def test_the_hub_shows_neither_without_an_email(client, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    client.force_login(nobody)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Email not verified" not in page
    assert ">Verified<" not in page


def test_the_activity_card_lists_the_verification(client, casey):
    client.post(verify_url(casey))
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Email verified" in page


# --- The seed --------------------------------------------------------------------


def test_seed_verifies_admin_and_employee_but_not_customer(db):
    call_command("seed")

    assert User.objects.get(username="admin").email_verified
    assert User.objects.get(username="employee").email_verified
    assert not User.objects.get(username="customer").email_verified


# --- The admin's shortcut ------------------------------------------------------------


@pytest.fixture
def admin_user(db, enrol_two_factor):
    admin = User.objects.create_superuser(
        username="ada", password="ada-pass-123", email="ada@example.com"
    )
    enrol_two_factor(admin)
    return admin


def run_mark_verified(client, *users):
    return client.post(
        reverse("admin:accounts_user_changelist"),
        {
            "action": "mark_email_verified",
            "_selected_action": [user.pk for user in users],
        },
        follow=True,
    )


def admin_messages(response):
    return [str(message) for message in response.context["messages"]]


def test_the_admin_marks_an_email_verified(client, admin_user, casey):
    client.force_login(admin_user)

    response = run_mark_verified(client, casey)

    casey.refresh_from_db()
    assert casey.email_verified
    event = verified_events(casey).get()
    assert event.actor == admin_user
    assert "Marked verified: casey." in admin_messages(response)


def test_the_owner_is_told_about_the_admin_verifying(client, admin_user, casey):
    client.force_login(admin_user)

    run_mark_verified(client, casey)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["casey@example.com"]
    assert "ThoughtTronix support" in mail.outbox[0].body
    assert "ada" not in mail.outbox[0].body


def test_the_admin_skips_their_own_account_and_other_superusers(
    client, admin_user, casey
):
    other = User.objects.create_superuser(
        username="grace", password="grace-pass-123", email="grace@example.com"
    )
    client.force_login(admin_user)

    response = run_mark_verified(client, admin_user, other, casey)

    admin_user.refresh_from_db()
    other.refresh_from_db()
    assert not admin_user.email_verified
    assert not other.email_verified
    warning = next(m for m in admin_messages(response) if m.startswith("Skipped"))
    assert "ada" in warning
    assert "grace" in warning
    casey.refresh_from_db()
    assert casey.email_verified


def test_the_admin_leaves_an_email_less_account_alone(client, admin_user, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    client.force_login(admin_user)

    run_mark_verified(client, nobody)

    nobody.refresh_from_db()
    assert nobody.email_verified_at is None
    assert not verified_events(nobody).exists()
    assert not mail.outbox


def test_staff_who_can_edit_users_still_cannot_mark_verified(client, casey):
    from django.contrib.auth.models import Permission

    clerk = User.objects.create_user(
        username="clerk", password="clerk-pass-123", is_staff=True
    )
    clerk.user_permissions.set(
        Permission.objects.filter(codename__in=["view_user", "change_user"])
    )
    client.force_login(clerk)

    changelist = client.get(reverse("admin:accounts_user_changelist"))
    run_mark_verified(client, casey)

    assert changelist.status_code == HTTPStatus.OK
    assert "mark_email_verified" not in changelist.content.decode()
    casey.refresh_from_db()
    assert casey.email_verified_at is None


def test_the_user_list_shows_whether_each_email_is_verified(client, admin_user, casey):
    security.mark_email_verified(casey)
    client.force_login(admin_user)

    changelist = client.get(reverse("admin:accounts_user_changelist"))

    assert "Email verified" in changelist.content.decode()
