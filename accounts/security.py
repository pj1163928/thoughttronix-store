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
change and "sign out of all other devices" it guards, the list of
signed-in devices that lets one be signed out at a time, the signed
links that verify an email address, those that confirm a new one, the
record of a forgotten password being reset, and two-factor: the
authenticator secret and its QR code, checking codes, recovery codes,
the code step of signing in, a code in place of the password as proof,
replacing recovery codes and turning two-factor off, and the owner's
choice to be asked for a code at checkout and on security changes.

The audit log is the source of truth for more than the admin's history
page. The cooldown counts failures from it, the Account page's activity
card reads it, and "password last changed" is derived from it, so every
security-relevant thing that happens to an account must pass through
``record_event``.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import pyotp
import segno
from django.contrib.auth import logout, update_session_auth_hash
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import RecoveryCode, SecurityEvent, TwoFactorDevice, User, UserSession

if TYPE_CHECKING:
    from django.contrib.sessions.backends.base import SessionBase
    from django.http import HttpRequest

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
    return _note_refusal(session, _identifier_key(identifier), now or timezone.now())


def forget_sign_in_attempts(session: SessionBase) -> None:
    """Clear this browser's sign-in history, as a successful sign-in does."""
    session.pop(SESSION_KEY, None)


def _identifier_key(identifier: str) -> str:
    return salted_hmac(
        "accounts.security.sign_in_attempts", identifier.casefold()
    ).hexdigest()


def _note_refusal(session: SessionBase, key: str, now: datetime) -> Standing:
    log = dict(session.get(SESSION_KEY, {}))
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
    answer: str,
    *,
    purpose: str,
    accept_code: bool = False,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Whether ``answer`` proves the signed-in ``user`` is who they say.

    ``answer`` is the current password. With ``accept_code``, a fresh code
    from the account's authenticator app passes too: the password is
    tried first, then, if ``answer`` looks like a code, the code, through
    the same replay check as sign-in. Recovery codes never pass; they are
    for signing in.

    While the account is paused, refuses without checking and without
    recording, exactly as sign-in does. Otherwise a wrong answer is
    recorded once, with ``purpose`` (a short label such as
    ``"password_change"``) in its details, and may start a pause. It is
    recorded as a failed two-factor code when it was checked as one, and
    as a failed sign-in otherwise.
    """
    if is_cooling_down(user, now=at):
        return False
    if user.check_password(answer):
        return True
    as_code = accept_code and is_authenticator_code(answer)
    if as_code:
        device = TwoFactorDevice.objects.confirmed().filter(user=user).first()
        if device is not None and verify_code(device, answer, at=at):
            return True
    record_failure(
        Kind.TWO_FACTOR_CODE_FAILED if as_code else Kind.SIGN_IN_FAILED,
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


def password_reset_requested(user: User, *, request: HttpRequest | None = None) -> None:
    """Record that a reset link was emailed to ``user``.

    Called only when the address matched an account. One that matched
    nobody records nothing, just as the reset page shows nothing
    different. There is no actor, because anyone can type an address into
    the form. No alert is sent either: the reset email itself tells the
    owner, and says to ignore it if they didn't ask.
    """
    record_event(Kind.PASSWORD_RESET_REQUESTED, user, request=request)


def password_reset_completed(user: User, *, request: HttpRequest | None = None) -> None:
    """Record that ``user`` set a new password from a reset link, and tell them.

    Call after the new password is saved. Saving it has already signed out
    every session, because the password is part of the session auth hash.
    The reset signs nobody in, so unlike ``password_changed`` there is no
    session here to keep, and every device row goes. The actor is the
    owner: following the link proved they read mail at the account's
    address.
    """
    user.user_sessions.all().delete()
    record_event(Kind.PASSWORD_RESET_COMPLETED, user, actor=user, request=request)
    send_alert(
        user,
        "Your password was reset",
        (
            "The password for your ThoughtTronix account was reset using a "
            "link emailed to this address, and every device signed in to it "
            "was signed out."
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
    are cleared out while we're here. Any half-finished two-factor
    sign-in in this browser is dropped: it has been finished or abandoned.
    """
    cancel_two_factor_sign_in(request.session)
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


# --- Verifying an email address -----------------------------------------------------
#
# A verification link carries a signed token naming the account and the
# address it was sent to, with no table behind it. The signature makes it
# unforgeable; the address in it makes it die the moment the account's
# email changes; the time in it makes it die after a day. Verification is
# a courtesy, never a gate: an unverified account works like any other.

EMAIL_VERIFICATION_MAX_AGE = timedelta(hours=24)
_VERIFICATION_SALT = "accounts.security.verify_email"


def make_verification_token(user: User, *, at: datetime | None = None) -> str:
    """A token that verifies ``user``'s current email, valid for 24 hours.

    ``at`` stamps the token with a given moment instead of now; tests use
    it to pin the clock.
    """
    issued = at or timezone.now()
    return signing.Signer(salt=_VERIFICATION_SALT).sign_object(
        {"user": user.pk, "email": user.email, "at": int(issued.timestamp())}
    )


def user_for_verification_token(
    token: str, *, now: datetime | None = None
) -> User | None:
    """The account ``token`` verifies, or ``None`` if it verifies nothing.

    A token is refused when its signature doesn't check out, when it is
    more than 24 hours old, when its account is gone, or when the account's
    email is no longer the one it was sent to. A token for an address
    that is already verified is still honoured; verifying it again changes
    nothing.
    """
    try:
        payload = signing.Signer(salt=_VERIFICATION_SALT).unsign_object(token)
        issued = datetime.fromtimestamp(payload["at"], tz=UTC)
        user_id, email = payload["user"], payload["email"]
    except (signing.BadSignature, KeyError, TypeError, ValueError, OverflowError):
        return None
    now = now or timezone.now()
    if not issued <= now <= issued + EMAIL_VERIFICATION_MAX_AGE:
        return None
    user = User.objects.filter(pk=user_id).first()
    if user is None or not email or user.email != email:
        return None
    return user


def send_verification_email(user: User, request: HttpRequest) -> bool:
    """Email ``user`` a link that confirms their address.

    Sent at sign-up and whenever the owner asks for another. Each link
    is independent: sending a new one doesn't cancel the last. An account
    with no email is skipped. Returns whether an email was sent.
    """
    if not user.email:
        return False
    link = request.build_absolute_uri(
        reverse("accounts:verify_email", args=[make_verification_token(user)])
    )
    body = render_to_string(
        "accounts/email/verify_email.txt",
        {"user": user, "link": link, "hours": _hours(EMAIL_VERIFICATION_MAX_AGE)},
    )
    send_mail("ThoughtTronix: Confirm your email address", body, None, [user.email])
    return True


def mark_email_verified(
    user: User,
    *,
    actor: User | None = None,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Record that ``user``'s current email is confirmed.

    ``actor`` defaults to ``user``, who proved it by following the link;
    an admin marking it verified passes the admin, and the owner is then
    emailed, as for every override. Verifying an address that is already
    verified, or an account with no email, changes nothing and records
    nothing. Returns whether anything changed.
    """
    if not user.email or user.email_verified:
        return False
    at = at or timezone.now()
    user.email_verified_at = at
    user.save(update_fields=["email_verified_at"])
    record_event(
        Kind.EMAIL_VERIFIED,
        user,
        actor=actor or user,
        request=request,
        details={"email": user.email},
        at=at,
    )
    if actor is not None and actor != user:
        send_alert(
            user,
            "Your email address was confirmed",
            (
                f"ThoughtTronix support marked {user.email} as the confirmed "
                f"email address for your account."
            ),
            at=at,
        )
    return True


# --- Changing an email address ----------------------------------------------------
#
# A new address takes effect only once a link sent to it is followed, so a
# typo can't cut the owner off: until then the old address goes on
# working for sign-in and password reset. Like a verification link, the
# token has no table behind it. It carries the account, the new address
# and the address it is replacing, so it dies when the account's email
# changes by any route, including another change being confirmed first.

EMAIL_CHANGE_MAX_AGE = timedelta(hours=24)
_EMAIL_CHANGE_SALT = "accounts.security.change_email"


@dataclass(frozen=True)
class EmailChange:
    """A change of address waiting to be confirmed: ``user`` to ``new_email``."""

    user: User
    new_email: str

    @property
    def old_email(self) -> str:
        return self.user.email

    def is_available(self) -> bool:
        """Whether no other account has taken the new address in the meantime."""
        return not email_taken(self.new_email, by_other_than=self.user)


def email_taken(email: str, *, by_other_than: User) -> bool:
    """Whether an account other than ``by_other_than`` uses ``email``, in any case."""
    return User.objects.with_email(email).exclude(pk=by_other_than.pk).exists()


def make_email_change_token(
    user: User, new_email: str, *, at: datetime | None = None
) -> str:
    """A token that moves ``user`` to ``new_email``, valid for 24 hours.

    ``at`` stamps the token with a given moment instead of now; tests use
    it to pin the clock.
    """
    issued = at or timezone.now()
    return signing.Signer(salt=_EMAIL_CHANGE_SALT).sign_object(
        {
            "user": user.pk,
            "old": user.email,
            "new": new_email,
            "at": int(issued.timestamp()),
        }
    )


def email_change_for_token(
    token: str, *, now: datetime | None = None
) -> EmailChange | None:
    """The change ``token`` would make, or ``None`` if it makes none.

    A token is refused when its signature doesn't check out, when it is
    more than 24 hours old, when its account is gone, or when the
    account's email is no longer the one it replaces. Whether the new
    address is still free is a separate question (``is_available``),
    asked again when the change is confirmed.
    """
    try:
        payload = signing.Signer(salt=_EMAIL_CHANGE_SALT).unsign_object(token)
        issued = datetime.fromtimestamp(payload["at"], tz=UTC)
        user_id, old, new = payload["user"], payload["old"], payload["new"]
    except (signing.BadSignature, KeyError, TypeError, ValueError, OverflowError):
        return None
    now = now or timezone.now()
    if not issued <= now <= issued + EMAIL_CHANGE_MAX_AGE:
        return None
    user = User.objects.filter(pk=user_id).first()
    if user is None or not new or user.email != old:
        return None
    return EmailChange(user, new)


def request_email_change(user: User, new_email: str, *, request: HttpRequest) -> None:
    """Email a confirmation link to ``new_email``, and record the request.

    Nothing about the account changes yet. The link goes to the *new*
    address, because following it is what proves the owner receives mail
    there. Each request is independent: a new one doesn't cancel the last,
    but whichever is confirmed first kills the rest.
    """
    link = request.build_absolute_uri(
        reverse(
            "accounts:confirm_email_change",
            args=[make_email_change_token(user, new_email)],
        )
    )
    body = render_to_string(
        "accounts/email/confirm_email_change.txt",
        {
            "user": user,
            "new_email": new_email,
            "link": link,
            "hours": _hours(EMAIL_CHANGE_MAX_AGE),
        },
    )
    send_mail("ThoughtTronix: Confirm your new email address", body, None, [new_email])
    record_event(
        Kind.EMAIL_CHANGE_REQUESTED,
        user,
        actor=user,
        request=request,
        details={"old": user.email, "new": new_email},
    )


def change_email(
    user: User,
    new_email: str,
    *,
    actor: User | None = None,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Switch ``user`` to ``new_email``, counted as verified, and tell the old address.

    Used when a confirmation link is followed. ``actor`` is whoever made
    the change and defaults to ``user``; an admin's direct edit passes the
    admin. Uniqueness is checked again here, and the database's own
    constraint backs that up should two accounts race for one address.
    Returns ``False``, changing and recording nothing, when another
    account has the address.

    The notice goes to the address being replaced, which is the one an
    attacker who changed it could no longer read. An account that had no
    email gets no notice.
    """
    at = at or timezone.now()
    old_email = user.email
    try:
        with transaction.atomic():
            if email_taken(new_email, by_other_than=user):
                return False
            user.email = new_email
            user.email_verified_at = at
            user.save(update_fields=["email", "email_verified_at"])
    except IntegrityError:
        user.refresh_from_db(fields=["email", "email_verified_at"])
        return False
    record_event(
        Kind.EMAIL_CHANGE_CONFIRMED,
        user,
        actor=actor or user,
        request=request,
        details={"old": old_email, "new": new_email},
        at=at,
    )
    by_support = actor is not None and actor.pk != user.pk
    send_alert(
        user,
        "Your email address was changed",
        (
            f"The email address for your ThoughtTronix account was changed "
            f"{'by ThoughtTronix support ' if by_support else ''}from "
            f"{old_email} to {new_email}. Account emails, including "
            f"password resets, will go to the new address from now on."
        ),
        at=at,
        to=old_email,
    )
    return True


def overridable(admin: User, users: Iterable[User]) -> tuple[list[User], list[User]]:
    """Split ``users`` into those ``admin`` may override and those skipped.

    No superuser may apply an override to their own account or to another
    superuser's, so that no admin can quietly take over another. Both are
    skipped; the caller names them in a warning. Superusers change their
    own accounts through the Account page, like everyone else.
    """
    allowed, skipped = [], []
    for user in users:
        if user.pk == admin.pk or user.is_superuser:
            skipped.append(user)
        else:
            allowed.append(user)
    return allowed, skipped


def _hours(duration: timedelta) -> int:
    return int(duration / timedelta(hours=1))


# --- Two-factor authentication ----------------------------------------------------
#
# Standard TOTP (RFC 6238): six digits from a shared secret and the
# current 30-second time step, so any authenticator app works, offline.
# A code from one step either side of now is accepted, for a phone whose
# clock is a little off, and no step is accepted twice, so a code someone
# watched being typed can't be replayed.
#
# Setup is two-stage. Opening the setup page makes a device with a fresh
# secret, unconfirmed; only a working code from the app confirms it and
# turns two-factor on. Until then the account is exactly as it was.

TOTP_ISSUER = "ThoughtTronix"
TOTP_DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
# No 0/o, 1/l/i: a recovery code is read off paper and typed by hand.
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RECOVERY_HALF = 5


def pending_two_factor_device(user: User) -> TwoFactorDevice | None:
    """The device ``user`` is setting up, made with a fresh secret if needed.

    The same pending device, and so the same secret, comes back on every
    visit until setup is confirmed, so reloading the setup page doesn't
    undo a QR code already scanned. Returns ``None`` when two-factor is
    already on: there is nothing to set up.
    """
    device, _ = TwoFactorDevice.objects.get_or_create(
        user=user, defaults={"secret": pyotp.random_base32()}
    )
    return None if device.confirmed_at else device


def provisioning_uri(device: TwoFactorDevice) -> str:
    """The ``otpauth://`` URI an authenticator app reads from the QR code.

    It names the store and the account's username, which is what the app
    lists the entry as. It contains the secret, so it belongs on the
    setup page and nowhere else.
    """
    return pyotp.TOTP(device.secret).provisioning_uri(
        name=device.user.get_username(), issuer_name=TOTP_ISSUER
    )


def provisioning_qr_svg(device: TwoFactorDevice) -> str:
    """The setup QR code as an inline ``<svg>``: dark modules on white.

    Rendered on the server, so there is no image file and nothing in
    media. The white quiet zone is part of the drawing, because scanners
    need it and the store's theme is dark.
    """
    return segno.make(provisioning_uri(device), error="m").svg_inline(
        scale=5,
        border=4,
        dark="#000",
        light="#fff",
        omitsize=True,
        svgclass="h-auto w-full",
        title="QR code for setting up two-factor authentication",
    )


def setup_key(device: TwoFactorDevice) -> str:
    """The secret in groups of four, for typing into an app that can't scan.

    Authenticator apps ignore the spaces.
    """
    return " ".join(device.secret[i : i + 4] for i in range(0, len(device.secret), 4))


def is_authenticator_code(answer: str) -> bool:
    """Whether ``answer`` has the shape of an authenticator code: six digits.

    Spaces are ignored. It says nothing about whether the code is right;
    it lets a form tell a code from a password before deciding when to
    check it, since checking a right code spends it.
    """
    answer = "".join(answer.split())
    return len(answer) == 6 and answer.isdigit()


def verify_code(
    device: TwoFactorDevice, code: str, *, at: datetime | None = None
) -> bool:
    """Whether ``code`` is a fresh authenticator code for ``device``.

    Accepts the code for the time step at ``at`` (default now) and for
    one step either side. A code from a step at or before the newest one
    already accepted is refused, so each code works once. Accepting a
    code records its step, atomically, so two requests racing with the
    same code can't both succeed. Spaces are ignored; anything that isn't
    six digits is refused without being checked.

    This only answers the question. Counting a wrong code toward the
    cooldown is the caller's decision.
    """
    if not is_authenticator_code(code):
        return False
    code = "".join(code.split())
    totp = pyotp.TOTP(device.secret)
    now_step = totp.timecode(at or timezone.now())
    matched = None
    for step in range(now_step - TOTP_DRIFT_STEPS, now_step + TOTP_DRIFT_STEPS + 1):
        # Every candidate is compared, so timing doesn't say which matched.
        if hmac.compare_digest(totp.generate_otp(step), code):
            matched = step
    if matched is None:
        return False
    claimed = (
        TwoFactorDevice.objects.filter(pk=device.pk)
        .filter(Q(last_used_step__isnull=True) | Q(last_used_step__lt=matched))
        .update(last_used_step=matched)
    )
    if claimed:
        device.last_used_step = matched
    return bool(claimed)


def enable_two_factor(
    device: TwoFactorDevice,
    *,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> list[str]:
    """Turn two-factor on for ``device``'s account, and return its recovery codes.

    Call once a working code has been checked with ``verify_code``. The
    device is confirmed, a fresh set of recovery codes replaces any old
    one, the event is recorded and the owner is told. The codes are
    returned in plain text for the caller to show once; only their hashes
    are kept.
    """
    at = at or timezone.now()
    user = device.user
    with transaction.atomic():
        device.confirmed_at = at
        device.save(update_fields=["confirmed_at"])
        codes = generate_recovery_codes(user)
    record_event(Kind.TWO_FACTOR_ENABLED, user, actor=user, request=request, at=at)
    send_alert(
        user,
        "Two-factor authentication was turned on",
        (
            "Two-factor authentication was turned on for your ThoughtTronix "
            "account, using an authenticator app. Ten recovery codes were "
            "created for signing in without it."
        ),
        at=at,
    )
    return codes


def generate_recovery_codes(user: User) -> list[str]:
    """Replace ``user``'s recovery codes with ten new ones, and return them.

    Every old code stops working. Each new one looks like ``k7m2p-x9qtr``
    (about 49 bits of randomness) and is stored only as a hash, so the
    returned list is the only time the codes exist in plain text.
    """
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    with transaction.atomic():
        user.recovery_codes.all().delete()
        RecoveryCode.objects.bulk_create(
            RecoveryCode(user=user, code_hash=_hash_recovery_code(code))
            for code in codes
        )
    return codes


# --- Managing two-factor ----------------------------------------------------------
#
# Once two-factor is on, its owner can replace their recovery codes or turn
# it off. Turning it off is the one change that takes both the password
# and a code, so someone holding only the unlocked phone, or only the
# password, can't remove the protection. Superusers can't turn it off at
# all: two-factor is mandatory for the accounts that can do anything.


def two_factor_required(user: User) -> bool:
    """Whether ``user`` must keep two-factor on: every superuser must."""
    return user.is_superuser


def disable_two_factor(
    user: User,
    *,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Turn two-factor off for ``user``, and tell them.

    Call once the caller has checked both the password and a code. The
    device goes, and with it the owner's choices of when to be asked for a
    code; every recovery code goes too. The event is recorded and the
    owner emailed. Refused, changing and recording nothing, for an account
    that must keep two-factor (see ``two_factor_required``) or doesn't
    have it on. Returns whether two-factor was turned off.
    """
    if two_factor_required(user) or not user.two_factor_enabled:
        return False
    at = at or timezone.now()
    with transaction.atomic():
        TwoFactorDevice.objects.filter(user=user).delete()
        user.recovery_codes.all().delete()
    record_event(Kind.TWO_FACTOR_DISABLED, user, actor=user, request=request, at=at)
    send_alert(
        user,
        "Two-factor authentication was turned off",
        (
            "Two-factor authentication was turned off for your ThoughtTronix "
            "account. Signing in now takes only your password, and your "
            "recovery codes no longer work."
        ),
        at=at,
    )
    return True


def regenerate_recovery_codes(
    user: User,
    *,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> list[str]:
    """Replace ``user``'s recovery codes, tell them, and return the new set.

    Call once the caller has checked it's them; ``user`` must have
    two-factor on. Every old code stops working, used or not. The ten new
    ones are returned in plain text for the caller to show once (see
    ``generate_recovery_codes``).
    """
    at = at or timezone.now()
    codes = generate_recovery_codes(user)
    record_event(
        Kind.RECOVERY_CODES_REGENERATED, user, actor=user, request=request, at=at
    )
    send_alert(
        user,
        "Your recovery codes were replaced",
        (
            "A new set of ten recovery codes was made for your ThoughtTronix "
            "account. Your old recovery codes no longer work."
        ),
        at=at,
    )
    return codes


# --- Signing in with two-factor ---------------------------------------------------
#
# For an account with two-factor on, a correct password is only step 1.
# It signs nobody in: the browser's session is given a note that the
# account passed step 1 and when, and step 2 asks for a code. Only a
# working code turns that note into a real sign-in. The note lasts five
# minutes and survives five wrong codes, whichever runs out first.
#
# A wrong code is a failure like a wrong password, counted toward the same
# cooldown on the account and the same history in the browser, so going
# back to the password step never buys fresh code guesses.

PENDING_SIGN_IN_KEY = "pending_sign_in"
PENDING_SIGN_IN_MAX_AGE = timedelta(minutes=5)
SIGN_IN_CODE_ATTEMPTS = 5


def begin_two_factor_sign_in(
    session: SessionBase, user: User, identifier: str, *, at: datetime | None = None
) -> None:
    """Note in ``session`` that ``user`` has passed the password step.

    Call instead of signing in when ``user`` has two-factor on; the user
    stays signed out until ``check_sign_in_code`` accepts a code. The note
    holds the account, the time, the account's session auth hash (so a
    password change or "sign out of all other devices" in between kills
    it) and a keyed hash of ``identifier``, what was typed at step 1, so
    wrong codes count in this browser's history against the same entry
    as wrong passwords. Never the identifier itself.

    A note already in the session, for any account, is replaced.
    """
    session[PENDING_SIGN_IN_KEY] = {
        "user": user.pk,
        "at": (at or timezone.now()).isoformat(),
        "auth_hash": user.get_session_auth_hash(),
        "attempts_key": _identifier_key(identifier),
        "failures": 0,
    }


def pending_sign_in_user(
    session: SessionBase, *, now: datetime | None = None
) -> User | None:
    """The account waiting at step 2 in ``session``, or ``None`` if there isn't one.

    The note is dropped, and ``None`` returned, once it is more than five
    minutes old, or when the account has since been locked, deleted, had
    its password changed or its other sessions signed out, or no longer
    has two-factor on. ``now`` defaults to the current time; tests pass a
    fixed one.
    """
    pending = session.get(PENDING_SIGN_IN_KEY)
    if pending is None:
        return None
    now = now or timezone.now()
    started = datetime.fromisoformat(pending["at"])
    user = User.objects.filter(pk=pending["user"], is_active=True).first()
    if (
        now - started > PENDING_SIGN_IN_MAX_AGE
        or user is None
        or not hmac.compare_digest(user.get_session_auth_hash(), pending["auth_hash"])
        or not user.two_factor_enabled
    ):
        cancel_two_factor_sign_in(session)
        return None
    return user


def cancel_two_factor_sign_in(session: SessionBase) -> None:
    """Drop any half-finished sign-in in ``session``; the next try starts at step 1."""
    session.pop(PENDING_SIGN_IN_KEY, None)


def check_sign_in_code(
    request: HttpRequest, code: str, *, at: datetime | None = None
) -> User | None:
    """Step 2: the account ``code`` signs in, or ``None`` if it signs in nobody.

    ``code`` is either a fresh authenticator code (see ``verify_code``) or
    an unused recovery code (see ``use_recovery_code``). On success the
    half-finished sign-in is cleared and its account returned, for the
    caller to sign in with ``django.contrib.auth.login``.

    A wrong code is recorded as a failed two-factor code and counted in
    this browser's history. The fifth wrong code discards the
    half-finished sign-in, as does the account being paused, so the user
    starts again from the password; while the account is paused no code is
    checked or recorded at all, exactly as for a password. ``at``
    defaults to now; tests pass a fixed one.
    """
    at = at or timezone.now()
    session = request.session
    user = pending_sign_in_user(session, now=at)
    if user is None:
        return None
    if is_cooling_down(user, now=at):
        cancel_two_factor_sign_in(session)
        return None
    device = TwoFactorDevice.objects.confirmed().get(user=user)
    if verify_code(device, code, at=at) or use_recovery_code(
        user, code, request=request, at=at
    ):
        cancel_two_factor_sign_in(session)
        return user

    record_failure(Kind.TWO_FACTOR_CODE_FAILED, user, request=request, at=at)
    pending = dict(session[PENDING_SIGN_IN_KEY])
    pending["failures"] += 1
    session[PENDING_SIGN_IN_KEY] = pending
    _note_refusal(session, pending["attempts_key"], at)
    if pending["failures"] >= SIGN_IN_CODE_ATTEMPTS or is_cooling_down(user, now=at):
        cancel_two_factor_sign_in(session)
    return None


def use_recovery_code(
    user: User,
    code: str,
    *,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Spend one of ``user``'s recovery codes, if ``code`` is one; tell them if so.

    Each code works once: it is marked used atomically, so two requests
    racing with the same code can't both succeed. Case and the dash are
    ignored. A code that works records the event, with how many are left
    in ``details``, and emails the owner, since a recovery code being used
    by someone else means they have the owner's password and the paper the
    codes were written on.

    Only sign-in accepts recovery codes. A form asking "prove it's you"
    takes an authenticator code (see ``confirm_code``).
    """
    at = at or timezone.now()
    claimed = RecoveryCode.objects.filter(
        user=user, code_hash=_hash_recovery_code(code), used_at__isnull=True
    ).update(used_at=at)
    if not claimed:
        return False
    remaining = user.recovery_codes.unused().count()
    record_event(
        Kind.RECOVERY_CODE_USED,
        user,
        actor=user,
        request=request,
        details={"remaining": remaining},
        at=at,
    )
    send_alert(
        user,
        "A recovery code was used to sign in",
        (
            f"One of the recovery codes for your ThoughtTronix account was "
            f"used to sign in, in place of a code from your authenticator "
            f"app. It can't be used again, and {remaining} of your recovery "
            f"codes {'is' if remaining == 1 else 'are'} left."
        ),
        at=at,
    )
    return True


# --- Asking for a code beyond sign-in -------------------------------------------
#
# Sign-in always asks a two-factor user for a code. Asking at other times
# is the owner's choice, kept on their device: when placing an order, and
# beside the current password on every security change. A code given as
# proof is checked like any other, so it can't be replayed, and a wrong
# one counts toward the same cooldown as a wrong password.

CodeOccasion = Literal["checkout", "security_changes"]
_OCCASION_FIELDS: dict[str, str] = {
    "checkout": "ask_at_checkout",
    "security_changes": "ask_for_security_changes",
}


def code_required(user: User, occasion: CodeOccasion) -> bool:
    """Whether ``user`` has asked to give a code for ``occasion``.

    ``"checkout"`` is placing an order; ``"security_changes"`` is every
    form that asks for the current password. Always ``False`` without
    two-factor on.
    """
    if not user.is_authenticated:
        return False
    return (
        TwoFactorDevice.objects.confirmed()
        .filter(user=user, **{_OCCASION_FIELDS[occasion]: True})
        .exists()
    )


def confirm_code(
    user: User,
    code: str,
    *,
    purpose: str,
    request: HttpRequest | None = None,
    at: datetime | None = None,
) -> bool:
    """Whether ``code`` from ``user``'s authenticator app proves it's them.

    The code counterpart of ``confirm_identity``. While the account is
    paused, refuses without checking and without recording. Otherwise a
    wrong code (or no two-factor at all) is recorded as a failed
    two-factor code, with ``purpose`` in its details, and may start a
    pause. Recovery codes aren't accepted: they are for signing in.
    """
    if is_cooling_down(user, now=at):
        return False
    device = TwoFactorDevice.objects.confirmed().filter(user=user).first()
    if device is not None and verify_code(device, code, at=at):
        return True
    record_failure(
        Kind.TWO_FACTOR_CODE_FAILED,
        user,
        request=request,
        at=at,
        details={"reauthentication": purpose},
    )
    return False


def update_two_factor_settings(
    user: User,
    *,
    ask_at_checkout: bool,
    ask_for_security_changes: bool,
    request: HttpRequest | None = None,
) -> bool:
    """Save when ``user`` wants to be asked for a code, and tell them.

    Records the event, with the new choices in ``details``, and emails
    the owner, since switching a choice off removes a protection. Choices
    that match what is saved change nothing and record nothing. Returns
    whether anything changed. ``user`` must have two-factor on.
    """
    device = TwoFactorDevice.objects.confirmed().get(user=user)
    if (device.ask_at_checkout, device.ask_for_security_changes) == (
        ask_at_checkout,
        ask_for_security_changes,
    ):
        return False
    device.ask_at_checkout = ask_at_checkout
    device.ask_for_security_changes = ask_for_security_changes
    device.save(update_fields=["ask_at_checkout", "ask_for_security_changes"])
    record_event(
        Kind.TWO_FACTOR_SETTINGS_CHANGED,
        user,
        actor=user,
        request=request,
        details={
            "checkout": ask_at_checkout,
            "security_changes": ask_for_security_changes,
        },
    )
    occasions = ["when you sign in"]
    if ask_at_checkout:
        occasions.append("when you place an order")
    if ask_for_security_changes:
        occasions.append("with your password for security changes")
    send_alert(
        user,
        "Your two-factor settings were changed",
        (
            "The two-factor settings for your ThoughtTronix account were "
            f"changed. A code from your authenticator app is now asked for "
            f"{_and_list(occasions)}."
        ),
    )
    return True


def _and_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _new_recovery_code() -> str:
    chars = "".join(
        secrets.choice(_RECOVERY_ALPHABET) for _ in range(2 * _RECOVERY_HALF)
    )
    return f"{chars[:_RECOVERY_HALF]}-{chars[_RECOVERY_HALF:]}"


def _hash_recovery_code(code: str) -> str:
    # Typed codes may come with or without the dash, in any case.
    normalized = "".join(ch for ch in code.lower() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


# --- Alerts -------------------------------------------------------------------------


def send_alert(
    user: User,
    subject: str,
    what_happened: str,
    *,
    at: datetime | None = None,
    to: str | None = None,
) -> bool:
    """Email ``user`` that something happened to their account.

    Every security alert goes through here. The email says what happened
    and when, and ends "Wasn't you? Contact support." It goes to the
    account's email, or to ``to`` when given (a changed email's notice
    goes to the address it replaced). No address means no email, silently:
    older accounts may have none, and an alert is never worth an error.
    Returns whether an email was sent.
    """
    address = user.email if to is None else to
    if not address:
        return False
    body = render_to_string(
        "accounts/email/alert.txt",
        {
            "user": user,
            "what_happened": what_happened,
            "when": _format_time(at or timezone.now()),
        },
    )
    send_mail(f"ThoughtTronix: {subject}", body, None, [address])
    return True


def _format_time(moment: datetime) -> str:
    local = timezone.localtime(moment)
    return f"{local:%H:%M} {local.tzname()} on {local.day} {local:%B %Y}"
