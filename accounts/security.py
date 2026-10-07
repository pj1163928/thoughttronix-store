"""Account security — the codebase's fourth deliberate deep module.

Everything that decides whether an account is safe lives here, so that
views, forms, the admin, middleware and management commands only ever
call in and contain no security logic of their own. The PRD
(``prd/account-security.md``) gives this module two-factor codes,
recovery codes, the sign-in cooldown and alert emails; they arrive phase
by phase. What it holds today is the foundation the rest is built on:
recording a ``SecurityEvent``.

The audit log is the source of truth for more than the admin's history
page. The cooldown counts failures from it, the Account page's activity
card reads it, and "password last changed" is derived from it, so every
security-relevant thing that happens to an account must pass through
``record_event``.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from .models import SecurityEvent

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .models import User


def record_event(
    kind: SecurityEvent.Kind,
    user: User | None,
    *,
    actor: User | None = None,
    request: HttpRequest | None = None,
    details: dict[str, Any] | None = None,
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
    """
    return SecurityEvent.objects.create(
        kind=kind,
        user=user,
        actor=actor,
        username=user.get_username() if user is not None else "",
        ip_address=client_ip(request),
        details=details or {},
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
