"""What superusers can see: the "User security" links and the user list's columns.

Superusers reach Django's user list from the Account page and the
back-office tab rail, and the list shows each account's email, two-factor
and sign-in state. Other staff see neither the links nor the columns.
"""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

USER_LIST = reverse("admin:accounts_user_changelist")
NOW = timezone.now().replace(microsecond=0)


@pytest.fixture
def admin_user(db, enrol_two_factor):
    admin = User.objects.create_superuser(
        username="ada", password="ada-pass-123", email="ada@example.com"
    )
    enrol_two_factor(admin)
    return admin


@pytest.fixture
def casey(db):
    """Verified, with two-factor on, free to sign in."""
    casey = User.objects.create_user(
        username="casey", password="casey-pass-123", email="casey@example.com"
    )
    security.mark_email_verified(casey)
    return casey


@pytest.fixture
def dana(db):
    """Unverified, no two-factor, and paused after five wrong passwords."""
    dana = User.objects.create_user(
        username="dana", password="dana-pass-123", email="dana@example.com"
    )
    pause(dana)
    return dana


@pytest.fixture
def lou(db):
    """No email at all, and locked."""
    return User.objects.create_user(
        username="lou", password="lou-pass-123", is_active=False
    )


def pause(user, at=None):
    at = at or timezone.now()
    for _ in range(security.COOLDOWN_THRESHOLD):
        security.record_failure(Kind.SIGN_IN_FAILED, user, at=at)


def listed(response):
    return {user.username for user in response.context["cl"].result_list}


def row(response, username):
    return next(
        user for user in response.context["cl"].result_list if user.username == username
    )


# --- The links -----------------------------------------------------------------------


def test_superusers_see_user_security_on_the_account_page(client, admin_user):
    client.force_login(admin_user)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "User security" in page
    assert USER_LIST in page


def test_superusers_see_user_security_in_the_tab_rail(client, admin_user):
    client.force_login(admin_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "User security" in page
    assert USER_LIST in page


def test_staff_see_neither_link(client, staff_user):
    client.force_login(staff_user)

    hub = client.get(reverse("accounts:account")).content.decode()
    rail = client.get(reverse("dashboard:index")).content.decode()

    assert "User security" not in hub
    assert "User security" not in rail
    assert USER_LIST not in hub + rail


def test_customers_dont_see_the_link(client, customer):
    client.force_login(customer)

    hub = client.get(reverse("accounts:account")).content.decode()

    assert "User security" not in hub
    assert USER_LIST not in hub


# --- Which accounts are paused -------------------------------------------------------


def test_paused_accounts_lists_each_pause_with_when_it_lifts(casey, db):
    pause(casey, at=NOW)

    assert security.paused_accounts(now=NOW) == {casey.pk: NOW + timedelta(minutes=15)}
    assert security.paused_accounts(now=NOW + timedelta(minutes=15)) == {}


def test_paused_accounts_leaves_out_a_cleared_cooldown(casey, db):
    pause(casey, at=NOW)
    security.record_event(Kind.COOLDOWN_CLEARED, casey, at=NOW + timedelta(minutes=1))

    assert security.paused_accounts(now=NOW + timedelta(minutes=2)) == {}


def test_failures_short_of_a_pause_are_not_a_pause(casey, db):
    for _ in range(security.COOLDOWN_THRESHOLD - 1):
        security.record_failure(Kind.SIGN_IN_FAILED, casey, at=NOW)

    assert security.paused_accounts(now=NOW) == {}


# --- The user list's columns ---------------------------------------------------------


def test_the_user_list_shows_each_accounts_security_state(
    client, admin_user, enrol_two_factor, casey, dana, lou
):
    enrol_two_factor(casey)
    client.force_login(admin_user)

    response = client.get(USER_LIST)

    model_admin = response.context["cl"].model_admin

    shown = {
        name: (
            model_admin.email_verified(row(response, name)),
            model_admin.two_factor(row(response, name)),
            model_admin.sign_in(row(response, name)),
        )
        for name in ("casey", "dana", "lou")
    }
    ends_at = timezone.localtime(security.cooldown_ends_at(dana))
    assert shown == {
        "casey": (True, True, None),
        "dana": (False, False, f"Paused until {ends_at:%H:%M}"),
        "lou": (False, False, "Locked"),
    }
    page = response.content.decode()
    for heading in ("Email verified", "Two-factor", "Sign-in"):
        assert heading in page
    assert f"Paused until {ends_at:%H:%M}" in page
    assert "Locked" in page


def test_a_setup_never_confirmed_is_not_two_factor_on(client, admin_user, casey):
    security.pending_two_factor_device(casey)
    client.force_login(admin_user)

    response = client.get(USER_LIST, {"two_factor": "yes"})

    assert "casey" not in listed(response)


# --- The user list's filters ---------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"email_verified": "yes"}, {"casey"}),
        ({"email_verified": "no"}, {"ada", "dana", "lou"}),
        ({"two_factor": "yes"}, {"ada", "casey"}),
        ({"two_factor": "no"}, {"dana", "lou"}),
        ({"sign_in": "locked"}, {"lou"}),
        ({"sign_in": "paused"}, {"dana"}),
        ({"sign_in": "allowed"}, {"ada", "casey"}),
    ],
)
def test_each_column_can_be_filtered(
    client, admin_user, enrol_two_factor, casey, dana, lou, query, expected
):
    enrol_two_factor(casey)
    client.force_login(admin_user)

    response = client.get(USER_LIST, query)

    assert response.status_code == HTTPStatus.OK
    assert listed(response) == expected


# --- Other staff ---------------------------------------------------------------------


def test_staff_who_can_view_users_see_no_security_columns_or_filters(
    client, casey, dana
):
    clerk = User.objects.create_user(
        username="clerk", password="clerk-pass-123", is_staff=True
    )
    clerk.user_permissions.set(Permission.objects.filter(codename="view_user"))
    client.force_login(clerk)

    response = client.get(USER_LIST)
    filtered = client.get(USER_LIST, {"sign_in": "paused"})

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    for heading in ("Email verified", "Two-factor", "Sign-in", "Paused until"):
        assert heading not in page
    # To them the filter doesn't exist, so the admin refuses it.
    assert filtered.status_code == HTTPStatus.FOUND
    assert filtered.url == f"{USER_LIST}?e=1"
