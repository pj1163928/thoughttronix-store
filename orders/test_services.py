"""place_order tests — coverage priority 3 in the PRD.

Denormalization, cart emptying, atomicity, unavailable rejection, and
the card_last4-only rule.
"""

from decimal import Decimal

import pytest

from products.models import Product

from .models import CartItem, Order, OrderItem
from .services import place_order
from .test_checkout_form import VALID_DATA


@pytest.fixture
def checkout_data():
    return dict(VALID_DATA)


def test_creates_an_order_with_denormalized_snapshot(cart, cart_item, checkout_data):
    order = place_order(cart, cart.user, checkout_data)

    assert order.user == cart.user
    assert order.total == Decimal("699.98")
    assert order.status == Order.Status.PLACED
    item = order.items.get()
    assert item.product_name == "Seraphine Home Hub"
    assert item.unit_price == Decimal("349.99")
    assert item.quantity == 2
    assert item.line_total == Decimal("699.98")


def test_order_history_survives_catalog_changes(cart, cart_item, checkout_data):
    order = place_order(cart, cart.user, checkout_data)

    product = cart_item.product
    product.name = "Seraphine Home Hub II"
    product.price = Decimal("999.00")
    product.save()

    item = order.items.get()
    assert item.product_name == "Seraphine Home Hub"
    assert item.unit_price == Decimal("349.99")


def test_addresses_and_email_are_copied_onto_the_order(cart, cart_item, checkout_data):
    order = place_order(cart, cart.user, checkout_data)

    assert order.email == "casey@example.com"
    assert order.shipping_street == "12 Cortex Lane"
    assert order.shipping_line2 == "Unit 7"
    assert order.shipping_state == "TX"
    assert order.billing_zip == "79015-1234"


def test_only_the_last_four_card_digits_are_stored(cart, cart_item, checkout_data):
    order = place_order(cart, cart.user, checkout_data)

    assert order.card_last4 == "4242"
    stored = [field.name for field in Order._meta.get_fields()]
    assert "card_number" not in stored
    assert "card_cvv" not in stored
    assert "card_expiry" not in stored


def test_the_cart_is_emptied(cart, cart_item, checkout_data):
    place_order(cart, cart.user, checkout_data)

    assert not cart.items.exists()
    assert cart.total() == Decimal("0.00")


def test_an_empty_cart_is_rejected(cart, checkout_data):
    with pytest.raises(ValueError):
        place_order(cart, cart.user, checkout_data)

    assert not Order.objects.exists()


def test_an_unavailable_product_is_rejected(
    cart, cart_item, unavailable_product, checkout_data
):
    cart.items.create(product=unavailable_product)

    with pytest.raises(ValueError, match="EchoPatch"):
        place_order(cart, cart.user, checkout_data)

    assert not Order.objects.exists()
    assert cart.items.count() == 2  # the cart is untouched


def test_a_failure_midway_leaves_no_partial_order(
    cart, cart_item, category, checkout_data, monkeypatch
):
    """All-or-nothing: if any line fails, no order and no emptied cart."""
    cart.add(
        Product.objects.create(
            name="Charging Pillow",
            slug="charging-pillow",
            price=Decimal("69.00"),
            category=category,
        )
    )

    original = OrderItem.objects.create
    calls = {"count": 0}

    def create_then_explode(**kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("boom")
        return original(**kwargs)

    monkeypatch.setattr(OrderItem.objects, "create", create_then_explode)

    with pytest.raises(RuntimeError):
        place_order(cart, cart.user, checkout_data)

    assert not Order.objects.exists()
    assert not OrderItem.objects.exists()
    assert CartItem.objects.count() == 2


def test_a_discount_is_applied_and_snapshotted(
    cart, cart_item, percent_code, checkout_data
):
    cart.discount_code = percent_code
    cart.save()

    order = place_order(cart, cart.user, checkout_data)

    assert order.subtotal == Decimal("699.98")
    assert order.discount_amount == Decimal("70.00")
    assert order.total == Decimal("629.98")
    assert order.discount_code == "THOUGHTS10"
    assert order.discount_code_used == percent_code


def test_an_order_without_a_code_records_no_discount(cart, cart_item, checkout_data):
    order = place_order(cart, cart.user, checkout_data)

    assert order.discount_amount == Decimal("0.00")
    assert order.discount_code == ""
    assert order.discount_code_used is None
    assert order.total == Decimal("699.98")


def test_the_code_is_released_with_the_cart(
    cart, cart_item, percent_code, checkout_data
):
    cart.discount_code = percent_code
    cart.save()

    place_order(cart, cart.user, checkout_data)

    cart.refresh_from_db()
    assert cart.discount_code is None
    assert cart.total() == Decimal("0.00")


def test_a_code_that_expired_before_checkout_is_rejected(
    cart, cart_item, expired_code, checkout_data
):
    cart.discount_code = expired_code
    cart.save()

    with pytest.raises(ValueError, match="LASTQUARTER"):
        place_order(cart, cart.user, checkout_data)

    assert not Order.objects.exists()
    assert cart.items.count() == 1  # the cart is untouched


def test_retiring_a_code_does_not_touch_the_orders_that_used_it(
    cart, cart_item, percent_code, checkout_data
):
    """The headline guarantee: history is a snapshot, not a live view."""
    cart.discount_code = percent_code
    cart.save()
    order = place_order(cart, cart.user, checkout_data)

    percent_code.is_active = False
    percent_code.value = Decimal("99")
    percent_code.save()

    order.refresh_from_db()
    assert order.total == Decimal("629.98")
    assert order.discount_amount == Decimal("70.00")
    assert order.discount_code == "THOUGHTS10"


def test_an_order_survives_its_code_being_deleted_outright(
    cart, cart_item, percent_code, checkout_data
):
    cart.discount_code = percent_code
    cart.save()
    order = place_order(cart, cart.user, checkout_data)

    percent_code.delete()

    order.refresh_from_db()
    assert order.discount_code_used is None
    assert order.discount_code == "THOUGHTS10"
    assert order.discount_amount == Decimal("70.00")
    assert order.total == Decimal("629.98")
