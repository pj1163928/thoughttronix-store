"""Middleware that runs on every signed-in request."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from . import security


class UserSessionMiddleware:
    """Sign a browser out once its device has been signed out elsewhere.

    Runs after ``AuthenticationMiddleware`` (it needs ``request.user``) and
    ``MessageMiddleware`` (it leaves a message). The decision and the
    bookkeeping are ``accounts.security.track_session``'s.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not security.track_session(request):
            messages.info(request, "This device was signed out from another device.")
        return self.get_response(request)


class TwoFactorRequiredMiddleware:
    """Send a superuser without two-factor to its setup page, from everywhere.

    Every page is gated, Django's admin included; only the setup page,
    signing out, and static and media files (which the setup page itself
    needs) stay open. Runs after ``UserSessionMiddleware``, so a device
    signed out from elsewhere is already anonymous by the time it gets
    here. Who is gated is ``accounts.security.two_factor_setup_owed``'s
    decision.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if security.two_factor_setup_owed(request.user) and not self._exempt(
            request.path
        ):
            return redirect("accounts:two_factor_setup")
        return self.get_response(request)

    @staticmethod
    def _exempt(path):
        open_pages = (
            reverse("accounts:two_factor_setup"),
            reverse("accounts:logout"),
        )
        open_prefixes = (settings.STATIC_URL, settings.MEDIA_URL)
        return path in open_pages or path.startswith(open_prefixes)
