"""The superuser gate: no two-factor, no store, no back office, no admin.

A superuser without confirmed two-factor is sent to the setup page from
everywhere but setup itself, signing out, and static and media files.
Everyone else, and a superuser with two-factor on, is untouched.
"""

import io

import pyotp
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from accounts import security
from accounts.models import RecoveryCode, TwoFactorDevice

User = get_user_model()

SETUP = reverse("accounts:two_factor_setup")
GATED_PAGES = [
    reverse("products:catalog"),
    reverse("accounts:account"),
    reverse("dashboard:index"),
    reverse("admin:index"),
    reverse("admin:accounts_user_changelist"),
]


@pytest.fixture
def root(db):
    return User.objects.create_superuser(
        username="root", password="root-pass-123", email="root@example.com"
    )


@pytest.fixture
def gated(client, root):
    client.force_login(root)
    return client


# --- Gated -----------------------------------------------------------------------


@pytest.mark.parametrize("url", GATED_PAGES)
def test_an_unenrolled_superuser_is_sent_to_setup(gated, url):
    response = gated.get(url)

    assert response.status_code == 302
    assert response.url == SETUP


def test_posts_are_gated_too(gated, customer):
    response = gated.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "mark_email_verified", "_selected_action": [customer.pk]},
    )

    assert response.url == SETUP


def test_a_setup_started_but_not_confirmed_still_gates(gated, root):
    security.pending_two_factor_device(root)

    assert gated.get(reverse("products:catalog")).url == SETUP


def test_promoting_a_user_gates_their_next_request(client, customer):
    client.force_login(customer)
    assert client.get(reverse("products:catalog")).status_code == 200

    customer.is_staff = customer.is_superuser = True
    customer.save()

    assert client.get(reverse("products:catalog")).url == SETUP


# --- Open while gated ------------------------------------------------------------


def test_the_setup_page_opens_and_says_why(gated):
    response = gated.get(SETUP)

    assert response.status_code == 200
    page = response.content.decode()
    assert "Administrator accounts must use two-factor" in page
    # Cancelling would only bounce straight back here.
    assert ">Cancel<" not in page


def test_an_optional_setup_page_keeps_its_cancel_link(client, customer):
    client.force_login(customer)

    page = client.get(SETUP).content.decode()

    assert ">Cancel<" in page
    assert "Administrator accounts must use two-factor" not in page


def test_signing_out_still_works(gated):
    response = gated.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert response.url != SETUP
    assert "_auth_user_id" not in gated.session


@pytest.mark.parametrize(
    "path",
    [f"/{settings.STATIC_URL.strip('/')}/css/tailwind.css", "/media/avatars/x.webp"],
)
def test_static_and_media_are_not_gated(gated, path):
    response = gated.get(path)

    assert response.status_code != 302


def test_finishing_setup_opens_every_page(gated, root):
    gated.get(SETUP)
    device = TwoFactorDevice.objects.get(user=root)

    response = gated.post(SETUP, {"code": pyotp.TOTP(device.secret).now()})

    assert response.status_code == 200
    assert "accounts/recovery_codes_issued.html" in [t.name for t in response.templates]
    for url in GATED_PAGES:
        assert gated.get(url).status_code == 200, url


# --- Untouched -------------------------------------------------------------------


def test_an_enrolled_superuser_is_untouched(gated, root, enrol_two_factor):
    enrol_two_factor(root)

    for url in GATED_PAGES:
        assert gated.get(url).status_code == 200, url


def test_customers_and_staff_are_untouched(client, customer, staff_user):
    client.force_login(customer)
    assert client.get(reverse("products:catalog")).status_code == 200
    assert client.get(reverse("accounts:account")).status_code == 200

    client.force_login(staff_user)
    assert client.get(reverse("dashboard:index")).status_code == 200


def test_visitors_are_untouched(client, db):
    assert client.get(reverse("products:catalog")).status_code == 200


# --- The seed --------------------------------------------------------------------


def test_seed_leaves_nobody_enrolled(db, enrol_two_factor):
    # A demo sign-up: not one of the seed's own accounts, so it survives.
    visitor = User.objects.create_user(username="demo_signup", password="x")
    enrol_two_factor(visitor)
    security.generate_recovery_codes(visitor)

    call_command("seed", stdout=io.StringIO())

    assert User.objects.filter(username="demo_signup").exists()
    assert not TwoFactorDevice.objects.exists()
    assert not RecoveryCode.objects.exists()


def test_the_seeded_admin_lands_on_setup_after_signing_in(client, db):
    call_command("seed", stdout=io.StringIO())

    response = client.post(
        reverse("accounts:login"),
        {"username": "admin", "password": "admin123"},
        follow=True,
    )

    assert response.request["PATH_INFO"] == SETUP
    assert response.context["user"].username == "admin"
