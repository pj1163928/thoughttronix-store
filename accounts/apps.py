from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # Connects the sign-in receivers that write to the audit log.
        from . import signals  # noqa: F401
