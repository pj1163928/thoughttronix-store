"""The development email backend: the console, but readable.

Django's own console backend prints each message exactly as it would go
over the wire. Django 6 builds messages with Python's modern email API,
which sends any body with a line over 78 characters as quoted-printable:
long lines are broken with a trailing ``=`` and non-ASCII is escaped. A
mail client decodes that before anyone sees it, but the console doesn't,
so a verification or reset link printed there can't be copied and used.

This backend prints the message encoded the way the console needs it,
with long lines left whole. What a real backend sends is unchanged.
"""

import email.policy

from django.core.mail.backends.console import EmailBackend

# RFC 5322's hard limit on a line. Every line a message of ours has
# fits, so the body goes out as plain 8-bit text rather than
# quoted-printable.
READABLE = email.policy.default.clone(max_line_length=998)


class ConsoleEmailBackend(EmailBackend):
    """Print each email to the console with its body as plain text."""

    def write_message(self, message):
        msg = message.message(policy=READABLE)
        self.stream.write(f"{msg.as_bytes().decode('utf-8')}\n")
        self.stream.write("-" * 79)
        self.stream.write("\n")
