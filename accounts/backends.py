"""Signing in with a username or an email.

``ModelBackend`` finds the account by its exact username. This backend
finds it by username or email, ignoring case, and changes nothing else:
permissions, and the refusal of inactive (locked) users, are inherited
as they are.
"""

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

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
            # as a wrong password does (Django #20760).
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    async def aauthenticate(self, request, username=None, password=None, **kwargs):
        # ModelBackend's async path has its own exact-username lookup;
        # route through the one above instead.
        return await sync_to_async(self.authenticate)(
            request, username=username, password=password, **kwargs
        )
