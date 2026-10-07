"""Successful sign-ins, written to the audit log.

Django announces every sign-in through ``user_logged_in``, whichever page
it came from — the storefront's sign-in page and the admin's alike.
Hooking the signal rather than ``SignInView`` means no sign-in path can
skip the log. The receiver only translates; ``accounts.security``
records.

Failed sign-ins are recorded by ``accounts.backends`` instead. Django's
``user_login_failed`` fires for a cooldown refusal exactly as it does for
a wrong password, and the cooldown must record the one and not the
other; only the backend can tell them apart.
"""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from . import security
from .models import SecurityEvent


@receiver(user_logged_in, dispatch_uid="accounts.record_sign_in")
def record_sign_in(sender, request, user, **kwargs):
    security.record_event(
        SecurityEvent.Kind.SIGN_IN_SUCCEEDED, user, actor=user, request=request
    )
