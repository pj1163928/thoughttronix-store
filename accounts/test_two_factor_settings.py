"""Asking for a code beyond sign-in: at checkout, and on security changes.

A two-factor user chooses, on the two-factor settings page, whether to be
asked for a code when placing an order and, beside the password, on every
security change. Codes are made with ``pyotp`` from the device's secret;
the one-step drift keeps the real clock safe across a step boundary.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from accounts import security
from accounts.models import SecurityEvent, TwoFactorDevice
from orders.models import Order
from orders.test_checkout_form import VALID_DATA

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
SETTINGS = reverse("accounts:two_factor_settings")
CHECKOUT = reverse("orders:checkout")
RENAME = reverse("accounts:change_username")


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


@pytest.fixture
def device(casey):
    """Casey with two-factor on, asked for a code at sign-in only."""
    device = security.pending_two_factor_device(casey)
    security.enable_two_factor(device)
    mail.outbox.clear()
    return device


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


def ask(device, *, checkout=False, security_changes=False):
    device.ask_at_checkout = checkout
    device.ask_for_security_changes = security_changes
    device.save()


def code(device, steps=0):
    """The code ``steps`` time steps from now; 0 is the current one."""
    moment = datetime.now(UTC) + timedelta(seconds=30 * steps)
    return pyotp.TOTP(device.secret).at(moment)


def wrong_code(device):
    return code(device, steps=10)


def failures(user):
    return user.security_events.filter(kind=Kind.TWO_FACTOR_CODE_FAILED)


# --- Whether a code is required ----------------------------------------------------


def test_nobody_without_two_factor_is_asked(casey):
    assert not security.code_required(casey, "checkout")
    assert not security.code_required(casey, "security_changes")


def test_a_pending_device_asks_for_nothing(casey):
    pending = security.pending_two_factor_device(casey)
    ask(pending, checkout=True, security_changes=True)

    assert not security.code_required(casey, "checkout")
    assert not security.code_required(casey, "security_changes")


def test_two_factor_alone_asks_for_nothing_beyond_sign_in(casey, device):
    assert not security.code_required(casey, "checkout")
    assert not security.code_required(casey, "security_changes")


def test_each_choice_is_asked_for_separately(casey, device):
    ask(device, checkout=True)
    assert security.code_required(casey, "checkout")
    assert not security.code_required(casey, "security_changes")

    ask(device, security_changes=True)
    assert not security.code_required(casey, "checkout")
    assert security.code_required(casey, "security_changes")


# --- Checking a code as proof ------------------------------------------------------


def test_a_current_code_confirms_it_is_you(casey, device):
    assert security.confirm_code(casey, code(device), purpose="test")
    assert not failures(casey).exists()


def test_a_wrong_code_is_recorded_as_a_failure(casey, device):
    assert not security.confirm_code(casey, wrong_code(device), purpose="checkout")

    event = failures(casey).get()
    assert event.details == {"reauthentication": "checkout"}


def test_a_code_cannot_be_used_twice(casey, device):
    current = code(device)

    assert security.confirm_code(casey, current, purpose="test")
    assert not security.confirm_code(casey, current, purpose="test")


def test_a_recovery_code_is_not_accepted(casey, device):
    recovery = security.generate_recovery_codes(casey)[0]

    assert not security.confirm_code(casey, recovery, purpose="test")


def test_wrong_codes_count_toward_the_cooldown(casey, device):
    for _ in range(security.COOLDOWN_THRESHOLD):
        security.confirm_code(casey, wrong_code(device), purpose="test")

    assert security.is_cooling_down(casey)
    # While paused, even a right code is refused, and nothing is recorded.
    before = failures(casey).count()
    assert not security.confirm_code(casey, code(device), purpose="test")
    assert failures(casey).count() == before


def test_without_two_factor_no_code_confirms_anything(casey):
    assert not security.confirm_code(casey, "123456", purpose="test")


# --- Saving the choices ------------------------------------------------------------


def test_saving_records_the_event_and_alerts(casey, device):
    assert security.update_two_factor_settings(
        casey, ask_at_checkout=True, ask_for_security_changes=False
    )

    device.refresh_from_db()
    assert device.ask_at_checkout
    assert not device.ask_for_security_changes
    event = casey.security_events.get(kind=Kind.TWO_FACTOR_SETTINGS_CHANGED)
    assert event.actor == casey
    assert event.details == {"checkout": True, "security_changes": False}
    assert len(mail.outbox) == 1
    alert = mail.outbox[0]
    assert alert.subject == "ThoughtTronix: Your two-factor settings were changed"
    assert "when you sign in and when you place an order." in alert.body
    assert "Wasn't you? Contact support." in alert.body


def test_saving_the_same_choices_changes_nothing(casey, device):
    assert not security.update_two_factor_settings(
        casey, ask_at_checkout=False, ask_for_security_changes=False
    )

    assert not casey.security_events.filter(
        kind=Kind.TWO_FACTOR_SETTINGS_CHANGED
    ).exists()
    assert mail.outbox == []


# --- The settings page -------------------------------------------------------------


def settings_post(client, current=PASSWORD, two_factor_code="", **choices):
    data = {"current_password": current, "two_factor_code": two_factor_code}
    data |= {name: "on" for name, chosen in choices.items() if chosen}
    return client.post(SETTINGS, data)


def test_the_page_requires_sign_in(client, db):
    response = client.get(SETTINGS)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_the_page_needs_two_factor_on(signed_in):
    response = signed_in.get(SETTINGS)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")


def test_the_page_shows_the_choices_then_password_and_code(signed_in, device):
    ask(device, checkout=True)

    form = signed_in.get(SETTINGS).context["form"]

    assert list(form.fields) == [
        "ask_at_checkout",
        "ask_for_security_changes",
        "current_password",
        "two_factor_code",
    ]
    assert form.initial == {"ask_at_checkout": True, "ask_for_security_changes": False}


def test_saving_takes_the_password_and_a_code(signed_in, casey, device):
    response = settings_post(
        signed_in, two_factor_code=code(device), ask_at_checkout=True
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    device.refresh_from_db()
    assert device.ask_at_checkout
    assert casey.security_events.filter(kind=Kind.TWO_FACTOR_SETTINGS_CHANGED).exists()


def test_the_password_alone_saves_nothing(signed_in, device):
    response = settings_post(signed_in, ask_at_checkout=True)

    assert "two_factor_code" in response.context["form"].errors
    device.refresh_from_db()
    assert not device.ask_at_checkout


def test_a_wrong_code_saves_nothing_and_counts(signed_in, casey, device):
    response = settings_post(
        signed_in, two_factor_code=wrong_code(device), ask_at_checkout=True
    )

    assert response.context["form"].errors["two_factor_code"] == [
        "That code didn't work."
    ]
    device.refresh_from_db()
    assert not device.ask_at_checkout
    assert failures(casey).count() == 1


def test_a_wrong_password_saves_nothing_and_spends_no_code(signed_in, device):
    response = settings_post(
        signed_in, current="nope", two_factor_code=code(device), ask_at_checkout=True
    )

    assert "current_password" in response.context["form"].errors
    device.refresh_from_db()
    assert not device.ask_at_checkout
    assert device.last_used_step is None


# --- Security changes --------------------------------------------------------------


def test_without_the_choice_security_changes_take_the_password_only(signed_in, device):
    form = signed_in.get(RENAME).context["form"]

    assert list(form.fields) == ["current_password", "username"]


def test_with_the_choice_security_changes_take_a_code_too(signed_in, device):
    ask(device, security_changes=True)

    form = signed_in.get(RENAME).context["form"]

    assert list(form.fields) == ["current_password", "two_factor_code", "username"]
    assert form.fields["two_factor_code"].label == "Authenticator code"


def test_the_password_alone_no_longer_makes_the_change(signed_in, casey, device):
    ask(device, security_changes=True)

    response = signed_in.post(
        RENAME, {"current_password": PASSWORD, "username": "casey_r"}
    )

    assert "two_factor_code" in response.context["form"].errors
    casey.refresh_from_db()
    assert casey.username == "casey"


def test_a_wrong_code_refuses_the_change_and_counts(signed_in, casey, device):
    ask(device, security_changes=True)

    response = signed_in.post(
        RENAME,
        {
            "current_password": PASSWORD,
            "two_factor_code": wrong_code(device),
            "username": "casey_r",
        },
    )

    assert "two_factor_code" in response.context["form"].errors
    casey.refresh_from_db()
    assert casey.username == "casey"
    assert failures(casey).get().details == {"reauthentication": "change_username"}


def test_the_password_and_a_code_make_the_change(signed_in, casey, device):
    ask(device, security_changes=True)

    response = signed_in.post(
        RENAME,
        {
            "current_password": PASSWORD,
            "two_factor_code": code(device),
            "username": "casey_r",
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    casey.refresh_from_db()
    assert casey.username == "casey_r"


def test_a_mistake_elsewhere_on_the_form_spends_no_code(signed_in, casey, device):
    ask(device, security_changes=True)

    response = signed_in.post(
        RENAME,
        {
            "current_password": PASSWORD,
            "two_factor_code": code(device),
            "username": "casey@home",
        },
    )

    assert "username" in response.context["form"].errors
    device.refresh_from_db()
    assert device.last_used_step is None


def test_every_security_change_asks_for_the_code(signed_in, casey, device):
    ask(device, security_changes=True)
    other = casey.user_sessions.create()

    for url in (
        reverse("accounts:password_change"),
        reverse("accounts:change_email"),
        reverse("accounts:account"),  # "Sign out of all other devices"
        reverse("accounts:sign_out_device", args=[other.pk]),
    ):
        form = signed_in.get(url).context["form"]
        assert "two_factor_code" in form.fields, url


def test_the_hub_shows_the_choices_and_links_to_settings(signed_in, device):
    ask(device, checkout=True)

    page = signed_in.get(reverse("accounts:account")).content.decode()

    assert "Asked for when you place an order" in page
    assert "Not asked for on security changes" in page
    assert SETTINGS in page


# --- Checkout ----------------------------------------------------------------------


@pytest.fixture
def shopper(client, customer, cart_item):
    """The conftest customer, signed in with a full cart and two-factor on."""
    device = security.pending_two_factor_device(customer)
    security.enable_two_factor(device)
    client.force_login(customer)
    return device


def test_without_the_choice_checkout_asks_for_no_code(client, shopper):
    form = client.get(CHECKOUT).context["form"]

    assert "two_factor_code" not in form.fields

    response = client.post(CHECKOUT, VALID_DATA)
    assert response.status_code == HTTPStatus.FOUND
    assert Order.objects.exists()


def test_with_the_choice_checkout_asks_for_a_code(client, shopper):
    ask(shopper, checkout=True)

    response = client.get(CHECKOUT)

    assert "two_factor_code" in response.context["form"].fields
    assert "Confirm it's you" in response.content.decode()


def test_no_order_without_the_code(client, shopper):
    ask(shopper, checkout=True)

    response = client.post(CHECKOUT, VALID_DATA)

    assert response.status_code == HTTPStatus.OK
    assert "two_factor_code" in response.context["form"].errors
    assert not Order.objects.exists()


def test_no_order_with_a_wrong_code_and_it_counts(client, customer, shopper):
    ask(shopper, checkout=True)

    response = client.post(
        CHECKOUT, {**VALID_DATA, "two_factor_code": wrong_code(shopper)}
    )

    assert "two_factor_code" in response.context["form"].errors
    assert not Order.objects.exists()
    assert failures(customer).get().details == {"reauthentication": "checkout"}


def test_the_right_code_places_the_order(client, shopper):
    ask(shopper, checkout=True)

    response = client.post(CHECKOUT, {**VALID_DATA, "two_factor_code": code(shopper)})

    order = Order.objects.get()
    assert response.url == reverse("orders:confirmation", kwargs={"pk": order.pk})


def test_a_mistyped_card_spends_no_code(client, shopper):
    ask(shopper, checkout=True)

    client.post(
        CHECKOUT,
        {
            **VALID_DATA,
            "card_number": "4242 4242 4242 4241",
            "two_factor_code": code(shopper),
        },
    )

    assert not Order.objects.exists()
    shopper.refresh_from_db()
    assert shopper.last_used_step is None


def test_turning_two_factor_off_would_take_the_choices_with_it(casey, device):
    ask(device, checkout=True, security_changes=True)

    device.delete()

    assert not TwoFactorDevice.objects.exists()
    assert not security.code_required(casey, "checkout")
    assert not security.code_required(casey, "security_changes")
