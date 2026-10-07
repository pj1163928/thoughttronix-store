"""Account security — the codebase's fourth deliberate deep module.

Everything that decides whether an account is safe lives here, so that
views, forms, the admin, middleware and management commands only ever
call in and contain no security logic of their own. The PRD
(``prd/account-security.md``) gives this module two-factor codes,
recovery codes, the sign-in cooldown and alert emails; they arrive phase
by phase. What it holds today is the foundation the rest is built on,
recording a ``SecurityEvent``, the sign-in cooldown built on top of it,
the alert email, "prove it's you": the current-password check that
guards every sensitive change, with the password change, the username
change and "sign out of all other devices" it guards, and the list of
signed-in devices that
lets one be signed out at a time.

The audit log is the source of truth for more than the admin's history
page. The cooldown counts failures from it, the Account page's activity
card reads it, and "password last changed" is derived from it, so every
security-relevant thing that happens to an account must pass through
``record_event``.
"""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.contrib.auth import logout, update_session_auth_hash
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import SecurityEvent, UserSession

if TYPE_CHECKING:
    from django.contrib.sessions.backends.base import SessionBase
    from django.http import HttpRequest

    from .models import User

Kind = SecurityEvent.Kind

# --- The sign-in cooldown -------------------------------------------------------
#
# Five failures within 15 minutes pause sign-in for 15 minutes. Once a
# pause has ended, a single further failure starts the next one, each
# twice as long as the last until it reaches an hour, where it stays. The
# ladder starts again after a successful sign-in, a cleared cooldown, or
# 24 hours without a pause starting.
#
# One rule runs against two histories. The account's history is the
# audit log, and it decides whether a sign-in is allowed: there is no
# counter column, only rows counted when asked. The browser's history is
# kept in its session against a hash of whatever was typed, and it decides
# only what the sign-in page *says*. That text is built from nothing but
# what this browser did, so it reads the same for an account that exists
# and one that doesn't, and gives nothing away.

COOLDOWN_THRESHOLD = 5
COOLDOWN_WINDOW = timedelta(minutes=15)
PAUSE_MINUTES = (15, 30, 60)
LADDER_MEMORY = timedelta(hours=24)

# A wrong password and a wrong two-factor code share one total, so going
# back to the password step never buys fresh code guesses.
FAILURE_KINDS = (Kind.SIGN_IN_FAILED, Kind.TWO_FACTOR_CODE_FAILED)
# Failures and pauses from before the latest of these no longer count.
RESET_KINDS = (Kind.SIGN_IN_SUCCEEDED, Kind.COOLDOWN_CLEARED)

SESSION_KEY = "sign_in_attempts"
# How many typed identifiers one browser's session remembers at most.
SESSION_IDENTIFIERS = 20


@dataclass(frozen=True)
class Pause:
    """One sign-in pause: when it started and how many minutes it lasts."""

    start: datetime
    minutes: int

    @property
    def ends_at(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)


@dataclass(frozen=True)
class Standing:
    """Where a run of failed sign-ins stands at one moment.

    While sign-in is paused, ``paused_until`` is set and
    ``paused_minutes`` says how many minutes are left, rounded up.
    Otherwise ``attempts_left`` more failures start a pause of
    ``next_pause_minutes``.
    """

    paused_until: datetime | None
    paused_minutes: int
    attempts_left: int
    next_pause_minutes: int


def record_event(
    kind: SecurityEvent.Kind,
    user: User | None,
    *,
    actor: User | None = None,
    request: HttpRequest | None = None,
    details: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> SecurityEvent:
    """Write one line to the audit log and return it.

    ``user`` is the account the event happened to, or ``None`` when no
    account matched (a sign-in attempt with an unknown identifier).
    ``actor`` is who did it, and is stored exactly as given: the owner for
    something they did to their own account, a superuser for an override,
    ``None`` when nobody identifiable acted (a failed sign-in, a
    server-side command). ``request`` supplies the IP address and may be
    omitted outside a request, as in the seed.

    ``details`` holds small, non-secret context such as
    ``{"old": "casey", "new": "casey_r"}``. Callers must never put a
    password, code, token or secret in it.

    ``at`` stamps the event with a given moment instead of now; tests use
    it to pin the clock.
    """
    return SecurityEvent.objects.create(
        kind=kind,
        user=user,
        actor=actor,
        username=user.get_username() if user is not None else "",
        ip_address=client_ip(request),
        details=details or {},
        created_at=at or timezone.now(),
    )


def client_ip(request: HttpRequest | None) -> str | None:
    """The address the request came from, or ``None`` if there isn't a usable one.

    Reads ``REMOTE_ADDR`` and nothing else. ``X-Forwarded-For`` and its
    relatives are set by the client unless a known proxy rewrites them, so
    trusting them would let anyone write any IP into the audit log. A
    value that isn't a valid IPv4 or IPv6 address (a Unix socket, an
    empty test request) is recorded as unknown rather than stored as is.
    """
    if request is None:
        return None
    address = request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        return None


# --- The cooldown, on an account --------------------------------------------------


def sign_in_standing(user: User, *, now: datetime | None = None) -> Standing:
    """Where ``user``'s failed sign-ins stand at ``now``.

    This is the account's real position, read from the audit log, and it
    is what decides whether a sign-in is allowed. It must never be shown
    on the sign-in page, where it would tell a stranger the account
    exists; ``note_refused_sign_in`` gives the page its text instead.

    ``now`` defaults to the current time; tests pass a fixed one.
    """
    now = now or timezone.now()
    return _standing(*_account_history(user, now), now)


def cooldown_ends_at(user: User, *, now: datetime | None = None) -> datetime | None:
    """When ``user``'s sign-in pause lifts, or ``None`` if there isn't one.

    A pause ends on its own, at the time it was given when it started.
    Attempts refused during a pause are never recorded (see
    ``is_cooling_down``), so they can't push the end back.
    """
    return sign_in_standing(user, now=now).paused_until


def is_cooling_down(user: User, *, now: datetime | None = None) -> bool:
    """Whether sign-in is paused for ``user`` right now.

    While it is, an attempt must be refused *without* checking the
    password and *without* calling ``record_failure``. Checking would let
    a guesser carry on during the pause, and recording would let a
    stranger keep an account paused indefinitely.
    """
    return cooldown_ends_at(user, now=now) is not None


def record_failure(
    kind: SecurityEvent.Kind,
    user: User | None,
    *,
    request: HttpRequest | None = None,
    at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> Pause | None:
    """Record a wrong password or code, and start a pause if it has earned one.

    ``kind`` is one of ``FAILURE_KINDS``. ``user`` is the account the
    attempt named, or ``None`` for an identifier that matched nobody;
    those are logged but count toward no one. Must not be called while
    the account is paused (see ``is_cooling_down``). ``details`` is
    stored on the failure's event, as for ``record_event``.

    When this failure starts a pause, a "sign-in paused" event is
    recorded with the pause's length in ``details`` and the owner is
    emailed. That happens once per pause, which is what keeps a stranger
    from filling the owner's inbox. Returns the new pause, or ``None``.
    """
    at = at or timezone.now()
    record_event(kind, user, request=request, at=at, details=details)
    if user is None:
        return None
    pause = _pause_earned(*_account_history(user, at), at)
    if pause is not None:
        record_event(
            Kind.COOLDOWN_STARTED,
            user,
            request=request,
            at=at,
            details={"minutes": pause.minutes},
        )
        send_alert(
            user,
            "Sign-in to your account is paused",
            (
                f"After repeated failed attempts to sign in, sign-in to your "
                f"account has been paused for {pause.minutes} minutes. You can "
                f"sign in again from {_format_time(pause.ends_at)}. Your "
                f"password has not been changed."
            ),
            at=at,
        )
    return pause


def _account_history(user: User, now: datetime) -> tuple[list[datetime], list[Pause]]:
    """The account's failures and pauses that still matter, newest first."""
    since = now - LADDER_MEMORY
    last_reset = (
        SecurityEvent.objects.filter(
            user=user, kind__in=RESET_KINDS, created_at__lte=now
        )
        .values_list("created_at", flat=True)
        .first()
    )
    if last_reset is not None and last_reset > since:
        since = last_reset
    rows = SecurityEvent.objects.filter(
        user=user,
        kind__in=(*FAILURE_KINDS, Kind.COOLDOWN_STARTED),
        created_at__gt=since,
        created_at__lte=now,
    ).values_list("kind", "created_at", "details")
    failures = [at for kind, at, _ in rows if kind != Kind.COOLDOWN_STARTED]
    pauses = [
        Pause(at, details["minutes"])
        for kind, at, details in rows
        if kind == Kind.COOLDOWN_STARTED
    ]
    return failures, pauses


# --- The cooldown, as one browser has seen it ---------------------------------------


def note_refused_sign_in(
    session: SessionBase, identifier: str, *, now: datetime | None = None
) -> Standing:
    """Count a refused sign-in in this browser, and say where it now stands.

    The sign-in page shows the result ("3 attempts left", "paused, try
    again in 14 minutes"). It runs the account's rule against a history
    kept in ``session`` for whatever was typed, so an unknown username
    counts down exactly as a real one does. It is only ever a
    description: whether a sign-in is allowed is decided by the account's
    own history, which can differ when attempts came from elsewhere.

    The identifier is kept only as a keyed hash, because people type
    their password into the username box.
    """
    now = now or timezone.now()
    log = dict(session.get(SESSION_KEY, {}))
    key = _identifier_key(identifier)
    entry = log.pop(key, {"failures": [], "pauses": []})
    failures = [datetime.fromisoformat(at) for at in entry["failures"]]
    pauses = [Pause(datetime.fromisoformat(at), m) for at, m in entry["pauses"]]

    if _standing(failures, pauses, now).paused_until is None:
        failures.insert(0, now)
        pause = _pause_earned(failures, pauses, now)
        if pause is not None:
            pauses.insert(0, pause)

    cutoff = now - LADDER_MEMORY
    log[key] = {
        "failures": [at.isoformat() for at in failures if at > cutoff],
        "pauses": [
            [p.start.isoformat(), p.minutes] for p in pauses if p.start > cutoff
        ],
    }
    # Newest last, so the oldest identifier is the one forgotten first.
    session[SESSION_KEY] = dict(list(log.items())[-SESSION_IDENTIFIERS:])
    return _standing(failures, pauses, now)


def forget_sign_in_attempts(session: SessionBase) -> None:
    """Clear this browser's sign-in history, as a successful sign-in does."""
    session.pop(SESSION_KEY, None)


def _identifier_key(identifier: str) -> str:
    return salted_hmac(
        "accounts.security.sign_in_attempts", identifier.casefold()
    ).hexdigest()


# --- The rule itself ---------------------------------------------------------------
#
# Pure functions of a history, newest first, so the account and the
# browser can't disagree about what the rule is.


def _standing(failures: list[datetime], pauses: list[Pause], now: datetime) -> Standing:
    ladder = [pause for pause in pauses if pause.start > now - LADDER_MEMORY]
    next_minutes = PAUSE_MINUTES[min(len(ladder), len(PAUSE_MINUTES) - 1)]
    if ladder and ladder[0].ends_at > now:
        until = ladder[0].ends_at
        minutes = math.ceil((until - now) / timedelta(minutes=1))
        return Standing(until, minutes, 0, next_minutes)
    if ladder:
        # After a pause, the next failure starts the next one.
        since, threshold = ladder[0].ends_at, 1
    else:
        since, threshold = now - COOLDOWN_WINDOW, COOLDOWN_THRESHOLD
    counted = sum(1 for at in failures if since < at <= now)
    return Standing(None, 0, max(threshold - counted, 0), next_minutes)


def _pause_earned(
    failures: list[datetime], pauses: list[Pause], now: datetime
) -> Pause | None:
    """The pause the newest failure starts, if it starts one."""
    standing = _standing(failures, pauses, now)
    if standing.paused_until is None and standing.attempts_left == 0:
        return Pause(now, standing.next_pause_minutes)
    return None


# --- Proving it's you -----------------------------------------------------------------
#
# Every sensitive change asks for the current password first. A wrong
# answer counts toward the same cooldown as a wrong sign-in, so a session
# left open on someone else's computer can't be used to guess the
# password, and while the account is paused no answer is checked at all.


def confirm_identity(
    user: User,
    password: str,
    *,
    purpose: str,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Whether ``password`` proves the signed-in ``user`` is who they say.

    While the account is paused, refuses without checking and without
    recording, exactly as sign-in does. Otherwise a wrong password is
    recorded as a failed sign-in, with ``purpose`` (a short label such as
    ``"password_change"``) in its details, and may start a pause.
    """
    if is_cooling_down(user, now=at):
        return False
    if user.check_password(password):
        return True
    record_failure(
        Kind.SIGN_IN_FAILED,
        user,
        request=request,
        at=at,
        details={"reauthentication": purpose},
    )
    return False


def password_changed(user: User, *, request: HttpRequest | None = None) -> None:
    """Record that ``user`` changed their own password, and tell them.

    Call after the new password is saved. Saving it has already signed
    out every other session, because the password is part of the
    session auth hash; the caller keeps its own with
    ``update_session_auth_hash``. The other sessions' device rows are
    removed here, so the Account page doesn't list devices that are
    already signed out.
    """
    _forget_other_sessions(user, request)
    record_event(Kind.PASSWORD_CHANGED, user, actor=user, request=request)
    send_alert(
        user,
        "Your password was changed",
        (
            "The password for your ThoughtTronix account was changed, and "
            "every other device signed in to it was signed out."
        ),
    )


def username_changed(
    user: User,
    old_username: str,
    *,
    actor: User | None = None,
    request: HttpRequest | None = None,
) -> None:
    """Record that ``user`` was renamed from ``old_username``, and tell them.

    Call after the new username is saved. ``actor`` is whoever made the
    change and defaults to ``user`` themselves; an admin's edit passes the
    admin. The event's ``details`` hold both names, and its username
    snapshot is the new one.

    A rename signs nobody out: the username isn't part of the session
    auth hash, and sign-in looks accounts up afresh each time.
    """
    new_username = user.get_username()
    record_event(
        Kind.USERNAME_CHANGED,
        user,
        actor=actor or user,
        request=request,
        details={"old": old_username, "new": new_username},
    )
    send_alert(
        user,
        "Your username was changed",
        (
            f"The username for your ThoughtTronix account was changed from "
            f'"{old_username}" to "{new_username}". Sign in with the new '
            f"username or your email address from now on."
        ),
    )


def sign_out_other_sessions(user: User, request: HttpRequest) -> None:
    """Sign ``user`` out everywhere except ``request``'s session.

    Rotates the session key on the account, which every session's auth
    hash includes, then refreshes this session's hash so it survives.
    The password is untouched. Removing the other device rows would sign
    those sessions out on its own; the rotation also catches any session
    that has no row.
    """
    _forget_other_sessions(user, request)
    user.rotate_session_key()
    update_session_auth_hash(request, user)
    record_event(Kind.OTHER_SESSIONS_ENDED, user, actor=user, request=request)


# --- Signed-in devices -------------------------------------------------------------
#
# Each browser signed in to an account has a ``UserSession`` row, and its
# id is kept in that browser's session. Every signed-in request checks the
# row is still there: deleting it is how one device signs out another.

USER_SESSION_KEY = "user_session"
# How often a device's "last active" time and IP are refreshed. Writing
# them on every request would be a database write per page.
LAST_SEEN_INTERVAL = timedelta(minutes=1)


def start_session(request: HttpRequest, user: User) -> UserSession:
    """Register the browser behind ``request`` as a device signed in to ``user``.

    Called on every sign-in. A browser signing in again replaces its own
    old row rather than appearing twice, and the account's expired rows
    are cleared out while we're here.
    """
    now = timezone.now()
    user.user_sessions.expired(now).delete()
    previous = request.session.get(USER_SESSION_KEY)
    if previous is not None:
        user.user_sessions.filter(pk=previous).delete()
    user_session = UserSession.objects.create(
        user=user,
        created_at=now,
        last_seen_at=now,
        ip_address=client_ip(request),
        user_agent=_user_agent(request),
    )
    request.session[USER_SESSION_KEY] = user_session.pk
    return user_session


def track_session(request: HttpRequest, *, now: datetime | None = None) -> bool:
    """Keep the signed-in device behind ``request`` honest; run on every request.

    Signs the request out if its device was signed out from elsewhere,
    and returns ``False`` when it did. Otherwise refreshes the device's
    last-active time and IP (at most once a minute) and returns ``True``.

    A refresh also marks the session modified, so its expiry slides
    forward with use. That keeps the session's lifetime and the row's
    "last active" in step, which is how ``UserSession.objects.active``
    knows a row has expired without reading the session store.

    A signed-in session with no row, from before devices were tracked,
    is given one.
    """
    user = request.user
    if not user.is_authenticated:
        return True
    pk = request.session.get(USER_SESSION_KEY)
    if pk is None:
        start_session(request, user)
        return True
    user_session = user.user_sessions.filter(pk=pk).first()
    if user_session is None:
        logout(request)
        return False
    now = now or timezone.now()
    if now - user_session.last_seen_at >= LAST_SEEN_INTERVAL:
        user_session.last_seen_at = now
        user_session.ip_address = client_ip(request)
        user_session.user_agent = _user_agent(request)
        user_session.save(update_fields=["last_seen_at", "ip_address", "user_agent"])
        request.session.modified = True
    return True


def end_session(request: HttpRequest) -> None:
    """Remove the device row for ``request``'s session, as signing out does."""
    pk = request.session.get(USER_SESSION_KEY)
    if pk is not None:
        UserSession.objects.filter(pk=pk).delete()


def current_session_id(request: HttpRequest) -> int | None:
    """The id of the ``UserSession`` row for this browser, if it has one."""
    return request.session.get(USER_SESSION_KEY)


def sign_out_session(
    user: User, user_session: UserSession, *, request: HttpRequest | None = None
) -> None:
    """Sign one of ``user``'s other devices out, and record it.

    The device is signed out on its next request, when ``track_session``
    finds its row gone. The event names the device ("Firefox on
    Windows") so the owner's history says which one.
    """
    label = user_session.label
    user_session.delete()
    record_event(
        Kind.SESSION_ENDED,
        user,
        actor=user,
        request=request,
        details={"device": label},
    )


def _forget_other_sessions(user: User, request: HttpRequest | None) -> None:
    current = current_session_id(request) if request is not None else None
    user.user_sessions.exclude(pk=current).delete()


def _user_agent(request: HttpRequest) -> str:
    max_length = UserSession._meta.get_field("user_agent").max_length
    return request.META.get("HTTP_USER_AGENT", "")[:max_length]


# --- Alerts -------------------------------------------------------------------------


def send_alert(
    user: User, subject: str, what_happened: str, *, at: datetime | None = None
) -> bool:
    """Email ``user`` that something happened to their account.

    Every security alert goes through here. The email says what happened
    and when, and ends "Wasn't you? Contact support." An account with no
    email is skipped silently: older accounts may have none, and an alert
    is never worth an error. Returns whether an email was sent.
    """
    if not user.email:
        return False
    body = render_to_string(
        "accounts/email/alert.txt",
        {
            "user": user,
            "what_happened": what_happened,
            "when": _format_time(at or timezone.now()),
        },
    )
    send_mail(f"ThoughtTronix: {subject}", body, None, [user.email])
    return True


def _format_time(moment: datetime) -> str:
    local = timezone.localtime(moment)
    return f"{local:%H:%M} {local.tzname()} on {local.day} {local:%B %Y}"
