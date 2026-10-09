"""The admin's change page: editing an account directly.

A new username or email takes effect at once, under the same identity
rules as sign-up, and is recorded with the admin as actor; the email
counts as verified and the old address is told. Django's set-password
form is recorded and alerted. On a superuser's page, the acting admin's
own included, none of those can be changed.
"""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
NEW_PASSWORD = "fresh-pass-456"
SECURITY_KINDS = [
    Kind.USERNAME_CHANGED,
    Kind.EMAIL_CHANGE_CONFIRMED,
    Kind.PASSWORD_CHANGED,
    Kind.ACCOUNT_LOCKED,
    Kind.ACCOUNT_UNLOCKED,
]


@pytest.fixture
def admin_user(db, enrol_two_factor):
    admin = User.objects.create_superuser(
        username="ada_admin", password="ada-pass-123", email="ada@example.com"
    )
    enrol_two_factor(admin)
    return admin


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def as_admin(client, admin_user):
    client.force_login(admin_user)
    return client


def change_url(user):
    return reverse("admin:accounts_user_change", args=[user.pk])


def password_url(user):
    return reverse("admin:auth_user_password_change", args=[user.pk])


def edit(client, user, **changes):
    """Submit ``user``'s change page as it stands, with ``changes`` applied."""
    data = {
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "job_title": user.job_title or "",
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "date_joined_0": f"{user.date_joined:%Y-%m-%d}",
        "date_joined_1": f"{user.date_joined:%H:%M:%S}",
        **changes,
    }
    # An unticked checkbox is left out of the POST altogether.
    data = {name: value for name, value in data.items() if value is not False}
    return client.post(change_url(user), data)


def set_password(client, user, password=NEW_PASSWORD, confirm=None):
    return client.post(
        password_url(user),
        {
            "password1": password,
            "password2": confirm or password,
            "usable_password": "true",
        },
    )


def form_errors(response):
    return response.context["adminform"].form.errors


def only_event(user, kind):
    return user.security_events.filter(kind=kind).get()


def assert_nothing_recorded():
    assert not SecurityEvent.objects.filter(kind__in=SECURITY_KINDS).exists()
    assert not mail.outbox


# --- Email ---------------------------------------------------------------------------


def test_an_email_edit_takes_effect_verified_and_tells_the_old_address(
    as_admin, admin_user, casey
):
    response = edit(as_admin, casey, email="Casey.R@example.com")

    assert response.status_code == HTTPStatus.FOUND
    casey.refresh_from_db()
    assert casey.email == "Casey.R@example.com"
    assert casey.email_verified
    event = only_event(casey, Kind.EMAIL_CHANGE_CONFIRMED)
    assert event.actor == admin_user
    assert event.details == {"old": "casey@example.com", "new": "Casey.R@example.com"}
    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == ["casey@example.com"]
    assert "changed by ThoughtTronix support" in notice.body
    assert "ada_admin" not in notice.body


def test_the_new_email_signs_in_at_once(client, admin_user, casey):
    client.force_login(admin_user)
    edit(client, casey, email="casey.r@example.com")
    client.logout()

    client.post(
        reverse("accounts:login"),
        {"username": "casey.r@example.com", "password": PASSWORD},
    )

    assert "_auth_user_id" in client.session


def test_an_email_another_account_uses_is_refused_in_any_case(as_admin, casey):
    User.objects.create_user(
        username="jordan", password=PASSWORD, email="jordan@example.com"
    )

    response = edit(as_admin, casey, email="JORDAN@example.com")

    assert response.status_code == HTTPStatus.OK
    assert form_errors(response)
    casey.refresh_from_db()
    assert casey.email == "casey@example.com"
    assert_nothing_recorded()


def test_an_email_can_be_changed_but_not_removed(as_admin, casey):
    response = edit(as_admin, casey, email="")

    assert "email" in form_errors(response)
    casey.refresh_from_db()
    assert casey.email == "casey@example.com"
    assert_nothing_recorded()


def test_an_account_without_an_email_can_be_given_one(as_admin, admin_user, db):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)

    edit(as_admin, nobody, email="nobody@example.com")

    nobody.refresh_from_db()
    assert nobody.email == "nobody@example.com"
    assert nobody.email_verified
    assert only_event(nobody, Kind.EMAIL_CHANGE_CONFIRMED).actor == admin_user
    # There was no old address to tell.
    assert not mail.outbox


# --- Username ------------------------------------------------------------------------


def test_a_username_edit_records_old_and_new_and_alerts_the_owner(
    as_admin, admin_user, casey
):
    edit(as_admin, casey, username="casey_r")

    casey.refresh_from_db()
    assert casey.username == "casey_r"
    event = only_event(casey, Kind.USERNAME_CHANGED)
    assert event.actor == admin_user
    assert event.by_support
    assert event.details == {"old": "casey", "new": "casey_r"}
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert 'changed by ThoughtTronix support from "casey" to "casey_r"' in alert.body
    assert "ada_admin" not in alert.body


@pytest.mark.parametrize("username", ["casey@home", "JORDAN"])
def test_a_username_with_an_at_or_taken_in_any_case_is_refused(
    as_admin, casey, username
):
    User.objects.create_user(username="jordan", password=PASSWORD)

    response = edit(as_admin, casey, username=username)

    assert response.status_code == HTTPStatus.OK
    assert form_errors(response)
    casey.refresh_from_db()
    assert casey.username == "casey"
    assert_nothing_recorded()


def test_editing_both_records_both(as_admin, casey):
    edit(as_admin, casey, username="casey_r", email="casey.r@example.com")

    kinds = set(casey.security_events.values_list("kind", flat=True))
    assert kinds == {Kind.USERNAME_CHANGED, Kind.EMAIL_CHANGE_CONFIRMED}


def test_saving_without_a_security_change_records_nothing(as_admin, casey):
    edit(as_admin, casey, first_name="Casey", job_title="Buyer")

    casey.refresh_from_db()
    assert casey.first_name == "Casey"
    assert_nothing_recorded()


# --- Active --------------------------------------------------------------------------


def test_unticking_active_locks_the_account(as_admin, admin_user, casey):
    caseys_browser = Client()
    caseys_browser.force_login(casey)

    edit(as_admin, casey, is_active=False)

    casey.refresh_from_db()
    assert not casey.is_active
    assert only_event(casey, Kind.ACCOUNT_LOCKED).actor == admin_user
    assert [message.subject for message in mail.outbox] == [
        "ThoughtTronix: Your account was locked"
    ]
    page = caseys_browser.get(reverse("accounts:account"))
    assert page.status_code == HTTPStatus.FOUND


def test_ticking_active_unlocks_the_account(as_admin, admin_user, casey):
    casey.is_active = False
    casey.save(update_fields=["is_active"])

    edit(as_admin, casey, is_active=True)

    casey.refresh_from_db()
    assert casey.is_active
    assert only_event(casey, Kind.ACCOUNT_UNLOCKED).actor == admin_user


# --- Setting a password --------------------------------------------------------------


def test_setting_a_password_records_it_and_alerts_the_owner(
    as_admin, admin_user, casey
):
    caseys_browser = Client()
    caseys_browser.force_login(casey)

    response = set_password(as_admin, casey)

    assert response.status_code == HTTPStatus.FOUND
    casey.refresh_from_db()
    assert casey.check_password(NEW_PASSWORD)
    assert only_event(casey, Kind.PASSWORD_CHANGED).actor == admin_user
    assert casey.password_last_changed is not None
    assert not casey.user_sessions.exists()
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.to == ["casey@example.com"]
    assert "Your password was changed" in alert.subject
    assert "ThoughtTronix support changed the password" in alert.body
    assert NEW_PASSWORD not in alert.body
    assert "ada_admin" not in alert.body
    page = caseys_browser.get(reverse("accounts:account"))
    assert page.status_code == HTTPStatus.FOUND


def test_a_set_password_form_that_doesnt_save_records_nothing(as_admin, casey):
    response = set_password(as_admin, casey, confirm="something-else-789")

    assert response.status_code == HTTPStatus.OK
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)
    assert_nothing_recorded()


def test_the_owner_sees_the_set_password_as_support(client, admin_user, casey):
    client.force_login(admin_user)
    set_password(client, casey)
    casey.refresh_from_db()
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Password changed" in page
    assert "by ThoughtTronix support" in page
    assert "ada_admin" not in page


# --- A superuser's change page ---------------------------------------------------------


@pytest.fixture
def grace(db, enrol_two_factor):
    grace = User.objects.create_superuser(
        username="grace", password="grace-pass-123", email="grace@example.com"
    )
    enrol_two_factor(grace)
    return grace


@pytest.fixture(params=["grace", "admin_user"], ids=["another", "own"])
def superuser(request):
    """Another superuser, and the acting admin's own account."""
    return request.getfixturevalue(request.param)


def test_a_superusers_identity_fields_are_read_only(as_admin, superuser):
    page = as_admin.get(change_url(superuser))

    form = page.context["adminform"].form
    for field in ["username", "email", "is_active"]:
        assert field not in form.fields
    html = page.content.decode()
    assert "Superusers change their own password" in html
    assert "../password/" not in html
    assert superuser.password not in html


def test_a_superusers_identity_fields_ignore_a_post(as_admin, superuser):
    original = (superuser.username, superuser.email)

    edit(as_admin, superuser, username="taken_over", email="evil@example.com")
    edit(as_admin, superuser, is_active=False)

    superuser.refresh_from_db()
    assert (superuser.username, superuser.email) == original
    assert superuser.is_active
    assert_nothing_recorded()


def test_a_superusers_other_fields_can_still_be_edited(as_admin, grace):
    edit(as_admin, grace, job_title="Founder")

    grace.refresh_from_db()
    assert grace.job_title == "Founder"


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_set_password_form_refuses_a_superuser(as_admin, superuser, method):
    if method == "get":
        response = as_admin.get(password_url(superuser))
    else:
        response = set_password(as_admin, superuser)

    assert response.status_code == HTTPStatus.FORBIDDEN
    superuser.refresh_from_db()
    assert not superuser.check_password(NEW_PASSWORD)
    assert_nothing_recorded()


def test_staff_who_can_edit_users_cannot_set_a_superusers_password(client, grace):
    clerk = User.objects.create_user(
        username="clerk", password="clerk-pass-123", is_staff=True
    )
    clerk.user_permissions.set(
        Permission.objects.filter(codename__in=["view_user", "change_user"])
    )
    client.force_login(clerk)

    response = set_password(client, grace)

    assert response.status_code == HTTPStatus.FORBIDDEN
    grace.refresh_from_db()
    assert not grace.check_password(NEW_PASSWORD)
