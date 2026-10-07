"""The Account page: what it shows, and whose history it shows."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind


@pytest.fixture
def superuser(db):
    # A name that appears nowhere else on the page, so its absence means
    # something.
    return get_user_model().objects.create_superuser(
        username="overseer-quill", password="admin123", email="quill@example.com"
    )


@pytest.fixture
def other_customer(db):
    return get_user_model().objects.create_user(
        username="someone-else", password="someone123", email="else@example.com"
    )


def hub(client):
    return client.get(reverse("accounts:account"))


# --- Access and navigation ---------------------------------------------------


def test_anonymous_visitors_are_sent_to_sign_in(client, db):
    response = hub(client)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == (
        f"{reverse('accounts:login')}?next={reverse('accounts:account')}"
    )


def test_signed_in_user_sees_their_account(client, customer):
    client.force_login(customer)

    response = hub(client)

    assert response.status_code == HTTPStatus.OK
    assert "customer" in response.content.decode()


def test_navbar_links_to_account_instead_of_addresses(client, customer):
    client.force_login(customer)

    page = client.get(reverse("products:catalog")).content.decode()

    assert f'href="{reverse("accounts:account")}"' in page
    assert ">Account<" in page
    assert reverse("accounts:addresses") not in page
    assert "Addresses" not in page


def test_addresses_card_links_to_the_address_book(client, customer, address):
    client.force_login(customer)

    page = hub(client).content.decode()

    assert reverse("accounts:addresses") in page
    assert "1 saved address," in page


# --- Profile and the no-email banner ------------------------------------------


def test_profile_shows_username_and_email(client, other_customer):
    client.force_login(other_customer)

    page = hub(client).content.decode()

    assert "someone-else" in page
    assert "else@example.com" in page


def test_an_account_with_no_email_sees_the_add_email_banner(client, customer):
    assert customer.email == ""
    client.force_login(customer)

    assert "Your account has no email address" in hub(client).content.decode()


def test_an_account_with_an_email_sees_no_banner(client, other_customer):
    client.force_login(other_customer)

    assert "Your account has no email address" not in hub(client).content.decode()


# --- The Password card -------------------------------------------------------


def test_password_card_reads_never_changed_without_a_qualifying_event(client, customer):
    # Plenty of history, none of it a password change.
    security.record_event(Kind.SIGN_UP, customer, actor=customer)
    security.record_event(Kind.SIGN_IN_FAILED, customer)
    client.force_login(customer)

    response = hub(client)

    assert response.context["password_last_changed"] is None
    assert "Never changed" in response.content.decode()


@pytest.mark.parametrize("kind", [Kind.PASSWORD_CHANGED, Kind.PASSWORD_RESET_COMPLETED])
def test_password_last_changed_is_the_newest_change_or_reset(customer, kind):
    now = timezone.now()
    security.record_event(Kind.PASSWORD_CHANGED, customer, at=now - timedelta(days=30))
    security.record_event(kind, customer, at=now - timedelta(days=2))
    # Newer, but not a password change.
    security.record_event(Kind.SIGN_IN_SUCCEEDED, customer, at=now)

    assert customer.password_last_changed == now - timedelta(days=2)


def test_password_last_changed_ignores_other_accounts(customer, other_customer):
    security.record_event(Kind.PASSWORD_CHANGED, other_customer)

    assert customer.password_last_changed is None


def test_password_card_shows_the_last_change(client, customer):
    changed = timezone.now().replace(year=2026, month=3, day=14, hour=9, minute=26)
    security.record_event(Kind.PASSWORD_CHANGED, customer, at=changed)
    client.force_login(customer)

    page = hub(client).content.decode()

    assert "Last changed" in page
    assert "14 Mar 2026, 09:26" in page
    assert "Never changed" not in page


# --- Recent security activity -------------------------------------------------


def test_activity_shows_only_the_users_own_events(client, customer, other_customer):
    security.record_event(Kind.USERNAME_CHANGED, other_customer, actor=other_customer)
    client.force_login(customer)

    events = list(hub(client).context["events"])

    assert events
    assert all(event.user == customer for event in events)
    assert Kind.USERNAME_CHANGED not in {event.kind for event in events}


def test_activity_is_newest_first_and_capped_at_ten(client, customer):
    start = timezone.now() - timedelta(days=1)
    recorded = [
        security.record_event(
            Kind.SIGN_IN_FAILED, customer, at=start + timedelta(minutes=n)
        )
        for n in range(12)
    ]
    client.force_login(customer)  # One more event: the sign-in, newest of all.

    events = list(hub(client).context["events"])

    assert len(events) == 10
    assert events[0].kind == Kind.SIGN_IN_SUCCEEDED
    assert events[1:] == recorded[::-1][:9]
    times = [event.created_at for event in events]
    assert times == sorted(times, reverse=True)


def test_activity_shows_what_when_and_from_where(client, customer):
    security.record_event(
        Kind.SIGN_IN_FAILED,
        customer,
        at=timezone.now().replace(year=2026, month=9, day=1, hour=8, minute=5),
    )
    event = SecurityEvent.objects.get(kind=Kind.SIGN_IN_FAILED)
    event.ip_address = "203.0.113.7"
    event.save()
    client.force_login(customer)

    page = hub(client).content.decode()

    assert "Sign-in failed" in page
    assert "1 Sep 2026, 08:05" in page
    assert "203.0.113.7" in page


def test_an_admins_event_reads_by_support_and_never_names_the_admin(
    client, customer, superuser
):
    security.record_event(Kind.COOLDOWN_CLEARED, customer, actor=superuser)
    client.force_login(customer)

    page = hub(client).content.decode()

    assert "Sign-in cooldown cleared" in page
    assert "by ThoughtTronix support" in page
    assert "overseer-quill" not in page
    assert "quill@example.com" not in page


def test_the_owners_own_events_are_not_attributed_to_support(client, customer):
    security.record_event(Kind.PASSWORD_CHANGED, customer, actor=customer)
    security.record_event(Kind.SIGN_IN_FAILED, customer)  # No actor at all.
    client.force_login(customer)

    assert "by ThoughtTronix support" not in hub(client).content.decode()


def test_by_support_is_true_only_for_someone_else_acting(customer, superuser):
    own = security.record_event(Kind.PASSWORD_CHANGED, customer, actor=customer)
    nobody = security.record_event(Kind.SIGN_IN_FAILED, customer)
    override = security.record_event(Kind.ACCOUNT_LOCKED, customer, actor=superuser)

    assert not own.by_support
    assert not nobody.by_support
    assert override.by_support
