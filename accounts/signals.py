"""Sign-ins and sign-outs, written to the audit log and the device list.

Django announces every sign-in through ``user_logged_in``, whichever page
it came from — the storefront's sign-in page and the admin's alike.
Hooking the signal rather than ``SignInView`` means no sign-in path can
skip the log or the device list. The receivers only translate;
``accounts.security`` records.

Failed sign-ins are recorded by ``accounts.backends`` instead. Django's
``user_login_failed`` fires for a cooldown refusal exactly as it does for
a wrong password, and the cooldown must record the one and not the
other; only the backend can tell them apart.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from . import security
from .models import SecurityEvent


@receiver(user_logged_in, dispatch_uid="accounts.record_sign_in")
def record_sign_in(sender, request, user, **kwargs):
    security.record_event(
        SecurityEvent.Kind.SIGN_IN_SUCCEEDED, user, actor=user, request=request
    )
    security.start_session(request, user)


@receiver(user_logged_out, dispatch_uid="accounts.end_session")
def end_session(sender, request, user, **kwargs):
    security.end_session(request)
