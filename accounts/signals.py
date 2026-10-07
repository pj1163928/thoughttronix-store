"""Sign-in outcomes, written to the audit log.

Django announces every sign-in through ``user_logged_in`` and every
failed attempt through ``user_login_failed``, whichever page the attempt
came from — the storefront's sign-in page and the admin's alike. Hooking
the signals rather than ``SignInView`` means no sign-in path can skip
the log. The receivers only translate; ``accounts.security`` records.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from . import security
from .models import SecurityEvent


@receiver(user_logged_in, dispatch_uid="accounts.record_sign_in")
def record_sign_in(sender, request, user, **kwargs):
    security.record_event(
        SecurityEvent.Kind.SIGN_IN_SUCCEEDED, user, actor=user, request=request
    )


@receiver(user_login_failed, dispatch_uid="accounts.record_failed_sign_in")
def record_failed_sign_in(sender, credentials, request=None, **kwargs):
    # The attempt is pinned to the account it named, if any, so the
    # cooldown can count it. An identifier that matches nobody is not
    # stored at all: people type their password into the username box.
    # The actor is unknown either way — failing to sign in proves nothing
    # about who was typing.
    User = get_user_model()
    try:
        user = User.objects.get_by_natural_key(credentials.get("username"))
    except User.DoesNotExist:
        user = None
    security.record_event(SecurityEvent.Kind.SIGN_IN_FAILED, user, request=request)
