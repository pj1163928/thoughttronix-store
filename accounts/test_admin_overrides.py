"""The superuser overrides: the user list's actions on other people's accounts.

Each action changes the account, records its event with the admin as
actor and emails the owner. None of them touches the acting admin or any
other superuser, and nobody but a superuser can run them. "Mark email
verified" was built earlier and is tested in ``test_email_verification``;
it appears here only where every action is checked alike.
"""

import re
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import RecoveryCode, SecurityEvent, TwoFactorDevice

Kind = SecurityEvent.Kind
User = get_user_model()

USER_LIST = reverse("admin:accounts_user_changelist")
PASSWORD = "casey-pass-123"
REFUSED = "Those details didn't work."
RESET_LINK = re.compile(r"https?://\S+(/accounts/password/reset/\S+/\S+/)")
SKIPPED = "Skipped"

ACTIONS = [
    "mark_email_verified",
    "reset_two_factor",
    "clear_cooldown",
    "lock_account",
    "unlock_account",
    "send_password_reset",
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


def run(client, action, *users):
    return client.post(
        USER_LIST,
        {"action": action, "_selected_action": [user.pk for user in users]},
        follow=True,
    )


def admin_messages(response):
    return [str(message) for message in response.context["messages"]]


def only_event(user, kind):
    return user.security_events.filter(kind=kind).get()


def pause(user):
    for _ in range(security.COOLDOWN_THRESHOLD):
        security.record_failure(Kind.SIGN_IN_FAILED, user)


def sign_in(client, identifier, password):
    return client.post(
        reverse("accounts:login"), {"username": identifier, "password": password}
    )


def signed_in(client):
    return "_auth_user_id" in client.session


def assert_alerted(user, subject_words):
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [user.email]
    assert subject_words in message.subject
    assert "ThoughtTronix support" in message.body
    # The admin is never named to the owner.
    assert "ada_admin" not in message.body


# --- Reset two-factor ----------------------------------------------------------------


def test_reset_two_factor_removes_the_device_and_recovery_codes(
    as_admin, admin_user, casey, enrol_two_factor
):
    enrol_two_factor(casey)
    security.generate_recovery_codes(casey)

    response = run(as_admin, "reset_two_factor", casey)

    assert not casey.two_factor_enabled
    assert not TwoFactorDevice.objects.filter(user=casey).exists()
    assert not RecoveryCode.objects.filter(user=casey).exists()
    assert only_event(casey, Kind.TWO_FACTOR_RESET).actor == admin_user
    assert "Two-factor reset: casey." in admin_messages(response)
    assert_alerted(casey, "Two-factor authentication was reset")


def test_after_a_reset_the_password_alone_signs_in(
    client, admin_user, casey, enrol_two_factor
):
    enrol_two_factor(casey)
    client.force_login(admin_user)
    run(client, "reset_two_factor", casey)
    client.logout()

    sign_in(client, "casey", PASSWORD)

    assert signed_in(client)


def test_reset_two_factor_leaves_an_account_without_it_alone(as_admin, casey):
    response = run(as_admin, "reset_two_factor", casey)

    assert not casey.security_events.filter(kind=Kind.TWO_FACTOR_RESET).exists()
    assert not mail.outbox
    assert "Two-factor wasn't on, so left alone: casey." in admin_messages(response)


# --- Clear sign-in cooldown ------------------------------------------------------------


def test_clearing_a_cooldown_lets_the_user_sign_in_at_once(client, admin_user, casey):
    pause(casey)
    assert security.is_cooling_down(casey)
    mail.outbox.clear()  # the pause's own email
    client.force_login(admin_user)

    response = run(client, "clear_cooldown", casey)
    client.logout()

    assert not security.is_cooling_down(casey)
    assert only_event(casey, Kind.COOLDOWN_CLEARED).actor == admin_user
    assert "Cooldown cleared: casey." in admin_messages(response)
    assert_alerted(casey, "Sign-in to your account was unpaused")
    sign_in(client, "casey", PASSWORD)
    assert signed_in(client)


def test_after_clearing_earlier_failures_no_longer_count(as_admin, casey):
    pause(casey)
    run(as_admin, "clear_cooldown", casey)

    for _ in range(security.COOLDOWN_THRESHOLD - 1):
        security.record_failure(Kind.SIGN_IN_FAILED, casey)

    standing = security.sign_in_standing(casey)
    assert standing.paused_until is None
    assert standing.attempts_left == 1
    # The ladder starts again, too.
    assert standing.next_pause_minutes == security.PAUSE_MINUTES[0]


def test_failures_short_of_a_pause_can_be_cleared(as_admin, casey):
    security.record_failure(Kind.SIGN_IN_FAILED, casey)

    run(as_admin, "clear_cooldown", casey)

    assert security.sign_in_standing(casey).attempts_left == (
        security.COOLDOWN_THRESHOLD
    )
    assert casey.security_events.filter(kind=Kind.COOLDOWN_CLEARED).exists()


def test_clear_cooldown_leaves_an_account_with_no_failures_alone(as_admin, casey):
    response = run(as_admin, "clear_cooldown", casey)

    assert not casey.security_events.filter(kind=Kind.COOLDOWN_CLEARED).exists()
    assert not mail.outbox
    assert "No failed sign-ins to clear, so left alone: casey." in admin_messages(
        response
    )


def test_a_cleared_account_drops_out_of_the_paused_filter(as_admin, casey):
    pause(casey)

    run(as_admin, "clear_cooldown", casey)
    changelist = as_admin.get(USER_LIST, {"sign_in": "paused"})

    assert casey not in changelist.context["cl"].result_list


# --- Lock and unlock -----------------------------------------------------------------


def test_locking_signs_out_an_existing_session(client, admin_user, casey):
    caseys_browser = Client()
    caseys_browser.force_login(casey)
    assert caseys_browser.get(reverse("accounts:account")).status_code == HTTPStatus.OK
    client.force_login(admin_user)

    response = run(client, "lock_account", casey)

    casey.refresh_from_db()
    assert not casey.is_active
    assert not casey.user_sessions.exists()
    assert only_event(casey, Kind.ACCOUNT_LOCKED).actor == admin_user
    assert "Locked: casey." in admin_messages(response)
    assert_alerted(casey, "Your account was locked")
    page = caseys_browser.get(reverse("accounts:account"))
    assert page.status_code == HTTPStatus.FOUND
    assert page.url.startswith(reverse("accounts:login"))


def test_a_locked_account_is_refused_with_the_generic_message(
    client, admin_user, casey
):
    client.force_login(admin_user)
    run(client, "lock_account", casey)
    client.logout()

    unknown = sign_in(client, "nobody-here", PASSWORD)
    locked = sign_in(client, "casey", PASSWORD)

    assert not signed_in(client)
    assert list(locked.context["form"].non_field_errors()) == [REFUSED]
    assert list(unknown.context["form"].non_field_errors()) == [REFUSED]


def test_unlocking_restores_access(client, admin_user, casey):
    client.force_login(admin_user)
    run(client, "lock_account", casey)
    mail.outbox.clear()

    response = run(client, "unlock_account", casey)
    client.logout()

    casey.refresh_from_db()
    assert casey.is_active
    assert only_event(casey, Kind.ACCOUNT_UNLOCKED).actor == admin_user
    assert "Unlocked: casey." in admin_messages(response)
    assert_alerted(casey, "Your account was unlocked")
    sign_in(client, "casey", PASSWORD)
    assert signed_in(client)


def test_a_session_from_before_the_lock_stays_signed_out_after_unlock(
    client, admin_user, casey
):
    caseys_browser = Client()
    caseys_browser.force_login(casey)
    client.force_login(admin_user)
    run(client, "lock_account", casey)
    run(client, "unlock_account", casey)

    page = caseys_browser.get(reverse("accounts:account"))

    assert page.status_code == HTTPStatus.FOUND
    assert page.url.startswith(reverse("accounts:login"))


def test_lock_and_unlock_leave_accounts_already_that_way_alone(as_admin, casey):
    locked = User.objects.create_user(
        username="lou", password=PASSWORD, email="lou@example.com", is_active=False
    )

    lock = run(as_admin, "lock_account", locked)
    unlock = run(as_admin, "unlock_account", casey)

    assert "Already locked, so left alone: lou." in admin_messages(lock)
    assert "Not locked, so left alone: casey." in admin_messages(unlock)
    assert not SecurityEvent.objects.filter(
        kind__in=[Kind.ACCOUNT_LOCKED, Kind.ACCOUNT_UNLOCKED]
    ).exists()
    assert not mail.outbox


# --- Send password reset link ----------------------------------------------------------


def test_the_admin_sends_a_working_reset_link(client, admin_user, casey):
    client.force_login(admin_user)

    response = run(client, "send_password_reset", casey)
    client.logout()

    assert only_event(casey, Kind.PASSWORD_RESET_REQUESTED).actor == admin_user
    assert "Reset link sent: casey." in admin_messages(response)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["casey@example.com"]
    assert message.subject == "ThoughtTronix: Reset your password"
    assert "ThoughtTronix support sent you this link" in message.body
    assert "ada_admin" not in message.body

    link = RESET_LINK.search(message.body).group(1)
    form_page = client.get(link, follow=True)
    client.post(
        form_page.redirect_chain[-1][0],
        {"new_password1": "fresh-pass-456", "new_password2": "fresh-pass-456"},
    )
    casey.refresh_from_db()
    assert casey.check_password("fresh-pass-456")


def test_the_reset_page_still_sends_its_own_wording(client, casey):
    client.post(reverse("accounts:password_reset"), {"email": "casey@example.com"})

    assert "Someone asked to reset the password" in mail.outbox[0].body
    assert "ThoughtTronix support" not in mail.outbox[0].body


def test_no_reset_link_for_a_locked_account(as_admin, db):
    locked = User.objects.create_user(
        username="lou", password=PASSWORD, email="lou@example.com", is_active=False
    )

    response = run(as_admin, "send_password_reset", locked)

    assert not mail.outbox
    assert not locked.security_events.filter(
        kind=Kind.PASSWORD_RESET_REQUESTED
    ).exists()
    assert "No email or locked, so no link sent: lou." in admin_messages(response)


# --- Every action alike --------------------------------------------------------------


@pytest.fixture
def ready_for(casey, enrol_two_factor):
    """Put ``casey`` in a state where ``action`` has something to change."""

    def prepare(action, user=casey):
        match action:
            case "reset_two_factor":
                enrol_two_factor(user)
            case "clear_cooldown":
                pause(user)
            case "unlock_account":
                user.is_active = False
                user.save(update_fields=["is_active"])
        mail.outbox.clear()
        return user

    return prepare


EVENT_FOR = {
    "mark_email_verified": Kind.EMAIL_VERIFIED,
    "reset_two_factor": Kind.TWO_FACTOR_RESET,
    "clear_cooldown": Kind.COOLDOWN_CLEARED,
    "lock_account": Kind.ACCOUNT_LOCKED,
    "unlock_account": Kind.ACCOUNT_UNLOCKED,
    "send_password_reset": Kind.PASSWORD_RESET_REQUESTED,
}


@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_records_the_admin_as_actor_and_emails_the_owner(
    as_admin, admin_user, ready_for, action
):
    casey = ready_for(action)

    run(as_admin, action, casey)

    event = only_event(casey, EVENT_FOR[action])
    assert event.actor == admin_user
    assert event.by_support
    assert [message.to for message in mail.outbox] == [["casey@example.com"]]


@pytest.mark.parametrize(
    "action", ["reset_two_factor", "clear_cooldown", "lock_account", "unlock_account"]
)
def test_an_email_less_owner_is_changed_but_not_emailed(
    as_admin, admin_user, ready_for, action
):
    nobody = User.objects.create_user(username="nobody", password=PASSWORD)
    ready_for(action, nobody)

    response = run(as_admin, action, nobody)

    assert response.status_code == HTTPStatus.OK
    assert only_event(nobody, EVENT_FOR[action]).actor == admin_user
    assert not mail.outbox


@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_skips_yourself_and_other_superusers_by_name(
    as_admin, admin_user, enrol_two_factor, action
):
    grace = User.objects.create_superuser(
        username="grace", password="grace-pass-123", email="grace@example.com"
    )
    enrol_two_factor(grace)
    pause(grace)
    mail.outbox.clear()
    before = SecurityEvent.objects.filter(kind=EVENT_FOR[action]).count()

    response = run(as_admin, action, admin_user, grace)

    warning = next(m for m in admin_messages(response) if m.startswith(SKIPPED))
    assert "ada_admin" in warning
    assert "grace" in warning
    assert SecurityEvent.objects.filter(kind=EVENT_FOR[action]).count() == before
    assert not mail.outbox
    grace.refresh_from_db()
    assert grace.is_active
    assert grace.two_factor_enabled
    assert security.is_cooling_down(grace)


def test_one_run_reports_changed_left_alone_and_skipped_together(
    as_admin, admin_user, casey
):
    lou = User.objects.create_user(
        username="lou", password=PASSWORD, email="lou@example.com", is_active=False
    )

    response = run(as_admin, "lock_account", admin_user, casey, lou)

    shown = admin_messages(response)
    assert "Locked: casey." in shown
    assert "Already locked, so left alone: lou." in shown
    assert any(m.startswith(SKIPPED) and "ada_admin" in m for m in shown)


@pytest.mark.parametrize("action", ACTIONS)
def test_staff_who_can_edit_users_cannot_run_any_action(client, ready_for, action):
    casey = ready_for(action)
    clerk = User.objects.create_user(
        username="clerk", password="clerk-pass-123", is_staff=True
    )
    clerk.user_permissions.set(
        Permission.objects.filter(codename__in=["view_user", "change_user"])
    )
    client.force_login(clerk)

    changelist = client.get(USER_LIST)
    run(client, action, casey)

    assert changelist.status_code == HTTPStatus.OK
    assert f'value="{action}"' not in changelist.content.decode()
    assert not casey.security_events.filter(kind=EVENT_FOR[action]).exists()
    assert not mail.outbox


def test_superusers_see_every_action(as_admin):
    page = as_admin.get(USER_LIST).content.decode()

    for action in ACTIONS:
        assert f'value="{action}"' in page


# --- The owner's view ------------------------------------------------------------------


def test_the_activity_card_credits_support_without_naming_the_admin(
    client, admin_user, casey
):
    pause(casey)
    client.force_login(admin_user)
    run(client, "clear_cooldown", casey)
    client.force_login(casey)

    page = client.get(reverse("accounts:account")).content.decode()

    assert "Sign-in cooldown cleared" in page
    assert "by ThoughtTronix support" in page
    assert "ada_admin" not in page


def test_the_override_functions_work_outside_the_admin(casey, enrol_two_factor):
    """The break-glass command will call ``reset_two_factor`` with no actor."""
    enrol_two_factor(casey)

    assert security.reset_two_factor(casey, at=timezone.now())

    event = only_event(casey, Kind.TWO_FACTOR_RESET)
    assert event.actor is None
    assert not event.by_support
