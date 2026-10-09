"""Break-glass: take two-factor off an account from the server.

    uv run python manage.py reset_2fa <username>

The one way back in for an administrator who has lost both their phone
and their recovery codes. Unlike the admin's "Reset two-factor" action it
works on any account, superusers included, because whoever can run this
already controls the server. The reset is recorded with no actor and the
owner is emailed, as for every override. A superuser is sent back through
two-factor setup at their next sign-in. Django's own ``changepassword``
covers a lost password.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts import security


class Command(BaseCommand):
    help = "Turn two-factor off for one account, superusers included."

    def add_arguments(self, parser):
        parser.add_argument("username", help="The account's username, in any case.")

    def handle(self, *args, username, **options):
        try:
            user = get_user_model().objects.get(username__iexact=username)
        except get_user_model().DoesNotExist:
            raise CommandError(f'No account has the username "{username}".') from None

        if not security.reset_two_factor(user):
            self.stdout.write(
                f"{user.username} doesn't have two-factor on. Nothing was changed."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Two-factor reset for {user.username}. Their device and "
                "recovery codes are gone, and the owner has been emailed."
            )
        )
