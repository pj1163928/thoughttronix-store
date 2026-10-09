"""Phase 18: the ``reset_2fa`` break-glass command and the cookie settings.

``reset_2fa`` is the one override that works on a superuser, because
whoever runs it already controls the server. The cookie settings are read
from ``.env``, and the app must still run with no ``.env`` at all.
"""

import runpy
from io import StringIO
from pathlib import Path

import environs
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from accounts import security
from accounts.models import RecoveryCode, SecurityEvent, TwoFactorDevice

Kind = SecurityEvent.Kind
User = get_user_model()

SETTINGS_FILE = Path(settings.BASE_DIR) / "config" / "settings.py"
COOKIE_SETTINGS = ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SESSION_COOKIE_AGE")


@pytest.fixture
def root(db, enrol_two_factor):
    root = User.objects.create_superuser(
        username="root", password="root-pass-123", email="root@example.com"
    )
    enrol_two_factor(root)
    security.generate_recovery_codes(root)
    return root


def reset_2fa(username):
    out = StringIO()
    call_command("reset_2fa", username, stdout=out)
    return out.getvalue()


# --- reset_2fa ---------------------------------------------------------------------


def test_reset_2fa_works_on_a_superuser(root):
    output = reset_2fa("root")

    assert not root.two_factor_enabled
    assert not TwoFactorDevice.objects.filter(user=root).exists()
    assert not RecoveryCode.objects.filter(user=root).exists()
    assert "Two-factor reset for root" in output


def test_reset_2fa_logs_the_event_with_no_actor(root):
    reset_2fa("root")

    event = SecurityEvent.objects.get(user=root, kind=Kind.TWO_FACTOR_RESET)
    assert event.actor is None
    assert event.ip_address is None


def test_reset_2fa_emails_the_owner(root):
    reset_2fa("root")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["root@example.com"]
    assert "Two-factor authentication was reset" in mail.outbox[0].subject


def test_reset_2fa_matches_the_username_in_any_case(root):
    reset_2fa("ROOT")

    assert not root.two_factor_enabled


def test_after_reset_2fa_a_superuser_is_sent_back_to_setup(root):
    reset_2fa("root")
    client = Client()
    client.post(
        reverse("accounts:login"), {"username": "root", "password": "root-pass-123"}
    )

    response = client.get(reverse("products:catalog"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:two_factor_setup"))


def test_reset_2fa_fails_cleanly_for_an_unknown_username(root):
    with pytest.raises(CommandError, match='No account has the username "nobody"'):
        reset_2fa("nobody")

    assert root.two_factor_enabled
    assert not SecurityEvent.objects.filter(kind=Kind.TWO_FACTOR_RESET).exists()


def test_reset_2fa_leaves_an_account_without_two_factor_alone(db):
    User.objects.create_user(username="casey", password="casey-pass-123")

    output = reset_2fa("casey")

    assert "doesn't have two-factor on" in output
    assert not SecurityEvent.objects.filter(kind=Kind.TWO_FACTOR_RESET).exists()
    assert not mail.outbox


# --- Cookie settings ---------------------------------------------------------------


@pytest.fixture
def load_settings(monkeypatch):
    """Run ``config/settings.py`` afresh, ignoring any developer ``.env``.

    Returns the module's names as a dict; Django's live settings are untouched.
    """
    monkeypatch.setattr(environs.Env, "read_env", lambda *args, **kwargs: None)
    for name in COOKIE_SETTINGS:
        monkeypatch.delenv(name, raising=False)

    def load(**environ):
        for name, value in environ.items():
            monkeypatch.setenv(name, value)
        return runpy.run_path(str(SETTINGS_FILE))

    return load


def test_cookie_settings_have_working_defaults_with_no_env(load_settings):
    loaded = load_settings()

    assert loaded["SESSION_COOKIE_SECURE"] is False
    assert loaded["CSRF_COOKIE_SECURE"] is False
    assert loaded["SESSION_COOKIE_AGE"] == 60 * 60 * 24 * 14


def test_each_cookie_setting_can_be_overridden_from_env(load_settings):
    loaded = load_settings(
        SESSION_COOKIE_SECURE="True",
        CSRF_COOKIE_SECURE="True",
        SESSION_COOKIE_AGE="3600",
    )

    assert loaded["SESSION_COOKIE_SECURE"] is True
    assert loaded["CSRF_COOKIE_SECURE"] is True
    assert loaded["SESSION_COOKIE_AGE"] == 3600


def test_env_example_lists_every_cookie_setting():
    example = (Path(settings.BASE_DIR) / ".env.example").read_text()

    for name in COOKIE_SETTINGS:
        assert f"# {name}=" in example
