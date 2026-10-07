"""Signing in with a username or an email, under the sign-in cooldown.

``ModelBackend`` finds the account by its exact username. This backend
finds it by username or email, ignoring case. Permissions, and the
refusal of inactive (locked) users, are inherited as they are.

It is also where failed sign-ins are written to the audit log. Every
sign-in path, the storefront's and the admin's alike, comes through
``authenticate``, and only here is it known *why* an attempt was refused:
a password that was checked and was wrong is a failure; an attempt turned
away by the cooldown was never checked and must not be recorded, or the
cooldown could be kept going forever. ``accounts.security`` owns the rule;
this backend only consults it.
"""

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from . import security
from .models import SecurityEvent

UserModel = get_user_model()


class UsernameOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel._default_manager.get_by_identifier(username)
        except UserModel.DoesNotExist:
            # Hash anyway, so an unknown account takes as long to refuse
            # as a wrong password does (Django #20760). The failure is
            # recorded with no account and no identifier: people type
            # their password into the username box.
            UserModel().set_password(password)
            security.record_failure(
                SecurityEvent.Kind.SIGN_IN_FAILED, None, request=request
            )
            return None
        if security.is_cooling_down(user):
            # Refused unchecked and unrecorded. Hashing keeps the refusal
            # as slow as a wrong password, so timing doesn't reveal it.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        security.record_failure(
            SecurityEvent.Kind.SIGN_IN_FAILED, user, request=request
        )
        return None

    async def aauthenticate(self, request, username=None, password=None, **kwargs):
        # ModelBackend's async path has its own exact-username lookup;
        # route through the one above instead.
        return await sync_to_async(self.authenticate)(
            request, username=username, password=password, **kwargs
        )
