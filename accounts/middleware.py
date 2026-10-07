"""Every signed-in request checks its device is still signed in."""

from django.contrib import messages

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
