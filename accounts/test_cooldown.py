"""The sign-in cooldown: repeated failures pause sign-in, for longer each time.

Five failures in 15 minutes pause an account for 15 minutes. After a
pause, one more failure starts the next: 30 minutes, then 60, then 60
again. The clock is pinned by passing ``at``/``now``, so nothing here
sleeps.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent

Kind = SecurityEvent.Kind
User = get_user_model()

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
REFUSED = "Those details didn't work."


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password="casey-pass-123", email="casey@example.com"
    )


def fail(user, at, kind=Kind.SIGN_IN_FAILED):
    """A failure at a moment of the test's choosing; returns any pause it starts."""
    return security.record_failure(kind, user, at=at)


def trip(user, at):
    """Five failures ending at ``at``: the first pause starts then."""
    for seconds in (40, 30, 20, 10, 0):
        pause = fail(user, at - timedelta(seconds=seconds))
    return pause


def minutes(n):
    return timedelta(minutes=n)


def sign_in(client, identifier, password):
    return client.post(
        reverse("accounts:login"), {"username": identifier, "password": password}
    )


def signed_in(client):
    return "_auth_user_id" in client.session


def refusal(response):
    return response.context["form"].non_field_errors()


def status_line(response):
    standing = response.context["standing"]
    if standing.paused_until:
        return f"paused {standing.paused_minutes}"
    return f"{standing.attempts_left} left, then {standing.next_pause_minutes}"


# --- The first pause ------------------------------------------------------------


def test_four_failures_are_not_a_pause(casey):
    for n in range(4):
        assert fail(casey, NOW - minutes(3 - n)) is None

    standing = security.sign_in_standing(casey, now=NOW)
    assert standing.paused_until is None
    assert standing.attempts_left == 1
    assert standing.next_pause_minutes == 15


def test_the_fifth_failure_in_15_minutes_starts_a_15_minute_pause(casey):
    for n in (14, 10, 6, 2):
        fail(casey, NOW - minutes(n))

    pause = fail(casey, NOW)

    assert pause == security.Pause(NOW, 15)
    assert security.cooldown_ends_at(casey, now=NOW) == NOW + minutes(15)


def test_the_pause_ends_on_its_own(casey):
    trip(casey, NOW)

    assert security.is_cooling_down(casey, now=NOW + minutes(15) - timedelta(seconds=1))
    assert not security.is_cooling_down(casey, now=NOW + minutes(15))


def test_five_failures_spread_over_more_than_15_minutes_are_not_a_pause(casey):
    for n in (16, 10, 6, 2, 0):
        fail(casey, NOW - minutes(n))

    assert not security.is_cooling_down(casey, now=NOW)


def test_the_pause_is_recorded_once_with_its_length(casey):
    trip(casey, NOW)

    pause = SecurityEvent.objects.get(kind=Kind.COOLDOWN_STARTED)
    assert pause.user == casey
    assert pause.actor is None
    assert pause.created_at == NOW
    assert pause.details == {"minutes": 15}


def test_wrong_codes_count_toward_the_same_total(casey):
    for n in (4, 3, 2):
        fail(casey, NOW - minutes(n))
    fail(casey, NOW - minutes(1), Kind.TWO_FACTOR_CODE_FAILED)
    fail(casey, NOW, Kind.TWO_FACTOR_CODE_FAILED)

    assert security.is_cooling_down(casey, now=NOW)


def test_failures_are_counted_per_account(casey):
    dana = User.objects.create_user(username="dana", password="dana-pass-123")
    trip(dana, NOW)

    assert security.is_cooling_down(dana, now=NOW)
    assert not security.is_cooling_down(casey, now=NOW)


def test_failures_with_no_account_count_toward_nobody(casey):
    for n in range(10):
        assert fail(None, NOW - minutes(n)) is None

    assert not security.is_cooling_down(casey, now=NOW)
    assert not SecurityEvent.objects.filter(kind=Kind.COOLDOWN_STARTED).exists()


# --- The ladder -----------------------------------------------------------------


def test_after_a_pause_one_failure_starts_a_longer_one(casey):
    trip(casey, NOW)
    after_first = NOW + minutes(15)

    assert security.sign_in_standing(casey, now=after_first).attempts_left == 1
    second = fail(casey, after_first + minutes(1))

    assert second.minutes == 30
    assert security.is_cooling_down(casey, now=after_first + minutes(30))


def test_pauses_double_up_to_an_hour_and_stay_there(casey):
    lengths = [trip(casey, NOW).minutes]
    at = NOW
    for _ in range(4):
        at = security.cooldown_ends_at(casey, now=at) + minutes(1)
        lengths.append(fail(casey, at).minutes)

    assert lengths == [15, 30, 60, 60, 60]


@pytest.mark.parametrize("reset", [Kind.SIGN_IN_SUCCEEDED, Kind.COOLDOWN_CLEARED])
def test_a_reset_point_starts_the_ladder_again(casey, reset):
    trip(casey, NOW)
    security.record_event(reset, casey, at=NOW + minutes(20))

    assert fail(casey, NOW + minutes(21)) is None
    standing = security.sign_in_standing(casey, now=NOW + minutes(21))
    assert standing.attempts_left == 4
    assert standing.next_pause_minutes == 15


def test_a_cleared_cooldown_ends_a_pause_at_once(casey):
    trip(casey, NOW)
    security.record_event(Kind.COOLDOWN_CLEARED, casey, at=NOW + minutes(1))

    assert not security.is_cooling_down(casey, now=NOW + minutes(1))


def test_the_ladder_forgets_a_pause_after_24_hours(casey):
    trip(casey, NOW)
    next_day = NOW + timedelta(hours=24, minutes=1)

    assert fail(casey, next_day) is None
    for n in range(1, 4):
        fail(casey, next_day + minutes(n))
    assert fail(casey, next_day + minutes(4)).minutes == 15


def test_attempts_refused_during_a_pause_are_never_counted(casey, client):
    trip(casey, timezone.now())
    ends_at = security.cooldown_ends_at(casey)

    for password in ("wrong", "casey-pass-123", "also-wrong"):
        sign_in(client, "casey", password)

    assert SecurityEvent.objects.filter(kind=Kind.SIGN_IN_FAILED).count() == 5
    assert SecurityEvent.objects.filter(kind=Kind.COOLDOWN_STARTED).count() == 1
    assert security.cooldown_ends_at(casey) == ends_at


# --- The alert email --------------------------------------------------------------


def test_starting_a_pause_emails_the_owner_once(casey):
    trip(casey, NOW)

    [email] = mail.outbox
    assert email.to == ["casey@example.com"]
    assert "paused" in email.subject
    assert "paused for 15 minutes" in email.body
    assert "12:15 UTC on 7 October 2026" in email.body
    assert "This happened at 12:00 UTC on 7 October 2026." in email.body
    assert email.body.rstrip().splitlines()[-3] == "Wasn't you? Contact support."


def test_failures_that_start_no_pause_send_no_email(casey):
    for n in range(4):
        fail(casey, NOW - minutes(n))
    fail(None, NOW)

    assert mail.outbox == []


def test_each_pause_on_the_ladder_sends_its_own_email(casey):
    trip(casey, NOW)
    fail(casey, NOW + minutes(16))

    assert len(mail.outbox) == 2
    assert "paused for 30 minutes" in mail.outbox[1].body


def test_an_account_with_no_email_is_paused_without_an_email(db):
    legacy = User.objects.create_user(username="legacy", password="legacy-pass-1")

    assert trip(legacy, NOW).minutes == 15
    assert mail.outbox == []


# --- What one browser is told -----------------------------------------------------


def test_the_browser_counts_down_then_pauses():
    session = {}
    seen = [
        security.note_refused_sign_in(session, "casey", now=NOW + minutes(n))
        for n in range(6)
    ]

    assert [s.attempts_left for s in seen[:4]] == [4, 3, 2, 1]
    assert seen[4].paused_until == NOW + minutes(4) + minutes(15)
    assert seen[4].paused_minutes == 15
    assert seen[5].paused_minutes == 14


def test_the_browser_follows_the_ladder_too():
    session = {}
    for n in range(5):
        security.note_refused_sign_in(session, "casey", now=NOW + timedelta(seconds=n))
    after = NOW + minutes(16)

    standing = security.note_refused_sign_in(session, "casey", now=after)

    assert standing.paused_minutes == 30


def test_the_browser_counts_each_identifier_separately():
    session = {}
    for _ in range(3):
        security.note_refused_sign_in(session, "casey", now=NOW)

    assert security.note_refused_sign_in(session, "dana", now=NOW).attempts_left == 4


def test_the_browser_never_keeps_what_was_typed():
    session = {}
    security.note_refused_sign_in(session, "hunter2-my-real-password", now=NOW)

    assert "hunter2" not in str(session)


def test_the_browser_remembers_a_bounded_number_of_identifiers():
    session = {}
    for n in range(50):
        security.note_refused_sign_in(session, f"guess-{n}", now=NOW)

    assert len(session[security.SESSION_KEY]) == security.SESSION_IDENTIFIERS


def test_forgetting_clears_the_browser_history():
    session = {}
    security.note_refused_sign_in(session, "casey", now=NOW)

    security.forget_sign_in_attempts(session)

    assert security.note_refused_sign_in(session, "casey", now=NOW).attempts_left == 4


# --- Through the sign-in page ---------------------------------------------------


def test_after_five_wrong_passwords_the_correct_one_is_refused(client, casey):
    for _ in range(5):
        sign_in(client, "casey", "wrong")

    response = sign_in(client, "casey", "casey-pass-123")

    assert response.status_code == 200
    assert not signed_in(client)


def test_failures_by_username_and_by_email_add_up(client, casey):
    for identifier in ("casey", "CASEY", "casey@example.com", "Casey", "casey"):
        sign_in(client, identifier, "wrong")

    sign_in(client, "casey@example.com", "casey-pass-123")

    assert not signed_in(client)


def test_a_finished_pause_lets_the_right_password_in(client, casey):
    trip(casey, timezone.now() - minutes(16))

    sign_in(client, "casey", "casey-pass-123")

    assert signed_in(client)


def test_a_successful_sign_in_resets_the_count(client, casey):
    for _ in range(4):
        sign_in(client, "casey", "wrong")
    sign_in(client, "casey", "casey-pass-123")
    client.post(reverse("accounts:logout"))

    for _ in range(4):
        sign_in(client, "casey", "wrong")
    sign_in(client, "casey", "casey-pass-123")

    assert signed_in(client)


def test_the_cooldown_applies_to_the_admin_sign_in_too(client, db):
    User.objects.create_superuser(username="admin", password="admin-pass-123")
    for _ in range(5):
        client.post(reverse("admin:login"), {"username": "admin", "password": "x"})

    client.post(
        reverse("admin:login"), {"username": "admin", "password": "admin-pass-123"}
    )

    assert not signed_in(client)


def test_a_pause_on_one_account_leaves_others_alone(client, casey):
    User.objects.create_user(username="dana", password="dana-pass-123")
    for _ in range(5):
        sign_in(client, "casey", "wrong")

    sign_in(client, "dana", "dana-pass-123")

    assert signed_in(client)


def test_the_page_counts_down_and_then_says_it_is_paused(client, casey):
    first = sign_in(client, "casey", "wrong")
    for _ in range(3):
        sign_in(client, "casey", "wrong")
    fifth = sign_in(client, "casey", "wrong")

    assert "4 attempts left before sign-in pauses for 15 minutes." in (
        first.content.decode()
    )
    assert "Sign-in is paused — try again in 15 minutes." in fifth.content.decode()


def test_a_known_and_an_unknown_account_count_down_identically(client, casey):
    known = [status_line(sign_in(client, "casey", "wrong")) for _ in range(5)]
    # The right password during the pause reads like any other attempt.
    known.append(status_line(sign_in(client, "casey", "casey-pass-123")))
    unknown = [status_line(sign_in(client, "nobody", "wrong")) for _ in range(6)]

    assert known == unknown
    assert known[-1] == "paused 15"


def test_a_successful_sign_in_clears_the_page_count(client, casey):
    for _ in range(3):
        sign_in(client, "casey", "wrong")
    sign_in(client, "casey", "casey-pass-123")
    client.post(reverse("accounts:logout"))

    response = sign_in(client, "casey", "wrong")

    assert response.context["standing"].attempts_left == 4


def test_an_empty_form_shows_no_count(client, db):
    response = client.post(reverse("accounts:login"), {"username": "casey"})

    assert response.context["standing"] is None


# --- One message for every refusal ----------------------------------------------


def test_wrong_password_unknown_account_and_pause_read_the_same(client, casey):
    wrong = sign_in(client, "casey", "wrong")
    unknown = sign_in(client, "nobody", "casey-pass-123")
    for _ in range(4):
        sign_in(client, "casey", "wrong")
    paused = sign_in(client, "casey", "casey-pass-123")

    assert security.is_cooling_down(casey)
    assert refusal(wrong) == refusal(unknown) == refusal(paused) == [REFUSED]
    for response in (wrong, unknown, paused):
        assert "Those details didn&#x27;t work." in response.content.decode()


def test_a_locked_account_reads_the_same_too(client, casey):
    casey.is_active = False
    casey.save()

    response = sign_in(client, "casey", "casey-pass-123")

    assert refusal(response) == [REFUSED]


# --- What is and isn't kept -----------------------------------------------------


def test_an_unknown_identifier_leaves_no_trace_of_itself(client, db):
    identifier = "hunter2-my-real-password"
    sign_in(client, identifier, "whatever")

    event = SecurityEvent.objects.get(kind=Kind.SIGN_IN_FAILED)
    assert event.user is None
    assert event.actor is None
    assert event.ip_address == "127.0.0.1"
    row = SecurityEvent.objects.filter(pk=event.pk).values().get()
    assert not any(identifier in str(value) for value in row.values())
    assert identifier not in str(dict(client.session))


def test_failed_sign_ins_email_only_when_a_pause_starts(client, casey):
    for _ in range(4):
        sign_in(client, "casey", "wrong")
    sign_in(client, "nobody@example.com", "wrong")
    assert mail.outbox == []

    sign_in(client, "casey", "wrong")
    for _ in range(3):
        sign_in(client, "casey", "wrong")

    assert len(mail.outbox) == 1
