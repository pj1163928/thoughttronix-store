"""Which products a code covers, and how the back office is organised.

The deletion test is the one that matters most here. A ``SELECTED`` code
whose last product is deleted must stop discounting, never widen to the
whole store — that is the entire reason ``applies_to`` is a stored field
rather than "an empty set means everything".
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from products.models import Product

from .forms import DiscountCodeForm
from .models import CartItem, DiscountCode


@pytest.fixture
def second_product(category):
    return Product.objects.create(
        name="Charging Pillow",
        slug="charging-pillow",
        price=Decimal("69.00"),
        category=category,
    )


@pytest.fixture
def third_product(category):
    return Product.objects.create(
        name="Whisper Alarm Clock",
        slug="whisper-alarm-clock",
        price=Decimal("59.00"),
        category=category,
    )


@pytest.fixture
def multi_code(db, product, second_product):
    """25% off two of the three things in the cart."""
    code = DiscountCode.objects.create(
        code="PAIR25",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("25"),
        applies_to=DiscountCode.Scope.SELECTED,
        per_user_limit=None,
    )
    code.products.set([product, second_product])
    return code


# --- What a multi-product code discounts ------------------------------------


def test_a_multi_product_code_covers_each_chosen_line(
    cart, product, second_product, third_product, multi_code
):
    CartItem.objects.create(cart=cart, product=product)  # 349.99
    CartItem.objects.create(cart=cart, product=second_product)  # 69.00
    CartItem.objects.create(cart=cart, product=third_product)  # 59.00

    assert cart.subtotal() == Decimal("477.99")
    # A quarter off 349.99 + 69.00 only.
    assert multi_code.discount_for(cart) == Decimal("104.75")


def test_a_fixed_amount_over_several_products_still_comes_off_once(
    cart, product, second_product
):
    CartItem.objects.create(cart=cart, product=product, quantity=2)
    CartItem.objects.create(cart=cart, product=second_product, quantity=3)
    code = DiscountCode.objects.create(
        code="PAIR30",
        kind=DiscountCode.Kind.AMOUNT,
        value=Decimal("30.00"),
        applies_to=DiscountCode.Scope.SELECTED,
    )
    code.products.set([product, second_product])

    assert code.discount_for(cart) == Decimal("30.00")


def test_a_selected_code_with_no_products_discounts_nothing(cart, cart_item):
    """The safe failure: a promotion that stops, not one that widens."""
    code = DiscountCode.objects.create(
        code="ORPHANED",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("50"),
        applies_to=DiscountCode.Scope.SELECTED,
    )

    assert code.discount_for(cart) == Decimal("0.00")


def test_deleting_the_last_product_does_not_widen_the_code(
    cart, cart_item, product_code, second_product
):
    """Deleting Seraphine must not turn 50%-off-Seraphine into 50% off everything."""
    cart.add(second_product)
    assert product_code.discount_for(cart) == Decimal("349.99")

    product_code.products.first().delete()

    assert product_code.products.count() == 0
    assert product_code.applies_to == DiscountCode.Scope.SELECTED
    assert product_code.discount_for(cart) == Decimal("0.00")


def test_an_order_wide_code_still_covers_everything(
    cart, product, second_product, percent_code
):
    CartItem.objects.create(cart=cart, product=product)
    CartItem.objects.create(cart=cart, product=second_product)

    assert percent_code.applies_to == DiscountCode.Scope.ALL
    assert percent_code.discount_for(cart) == Decimal("41.90")


# --- How a code describes itself --------------------------------------------


def test_labels_count_the_products_past_two(
    product, second_product, third_product, multi_code
):
    assert multi_code.label == "25% off Charging Pillow and Seraphine Home Hub"

    multi_code.products.add(third_product)
    # Products are ordered by name, so the count covers whatever trails.
    assert multi_code.label == (
        "25% off Charging Pillow, Seraphine Home Hub and 1 more"
    )


def test_a_single_product_label_is_unchanged(product_code):
    assert product_code.label == "50% off Seraphine Home Hub"
    assert product_code.covers_one_product


def test_the_cart_names_what_is_missing(client, cart, multi_code, third_product):
    """A code for two absent products says so in the plural."""
    cart.add(third_product)
    cart.discount_code = multi_code
    cart.save()
    client.force_login(cart.user)

    body = client.get(reverse("orders:cart")).content.decode()

    assert "only applies to Charging Pillow and Seraphine Home Hub" in body


# --- The form's two rules ---------------------------------------------------


def test_selecting_no_products_is_rejected(db, product):
    form = DiscountCodeForm(
        {
            "code": "NOTHING",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "10",
            "applies_to": DiscountCode.Scope.SELECTED,
            "per_user_limit": "1",
        }
    )

    assert not form.is_valid()
    assert "Pick at least one product" in form.errors["products"][0]


def test_choosing_the_whole_order_drops_any_ticked_products(db, product):
    """The two fields can never contradict each other after cleaning."""
    form = DiscountCodeForm(
        {
            "code": "EVERYTHING",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "10",
            "applies_to": DiscountCode.Scope.ALL,
            "products": [product.pk],
            "per_user_limit": "1",
        }
    )

    assert form.is_valid()
    code = form.save()
    assert code.applies_to == DiscountCode.Scope.ALL
    assert code.products.count() == 0


def test_a_blank_limit_means_unlimited(db):
    form = DiscountCodeForm(
        {
            "code": "NOCAP",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "10",
            "applies_to": DiscountCode.Scope.ALL,
            "per_user_limit": "",
            "total_limit": "",
        }
    )

    assert form.is_valid()
    code = form.save()
    assert code.per_user_limit is None
    assert code.total_limit is None


# --- Active and inactive ----------------------------------------------------


@pytest.fixture
def scheduled_code(db):
    return DiscountCode.objects.create(
        code="PRESEASON",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("15"),
        starts_at=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def retired_code(db):
    return DiscountCode.objects.create(
        code="WELCOMEBACK",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("20"),
        is_active=False,
    )


def test_active_keeps_scheduled_codes_and_drops_expired_ones(
    percent_code, scheduled_code, expired_code, retired_code
):
    active = DiscountCode.objects.active()

    assert percent_code in active
    assert scheduled_code in active
    assert expired_code not in active
    assert retired_code not in active


def test_inactive_is_the_exact_complement(
    percent_code, scheduled_code, expired_code, retired_code
):
    active = set(DiscountCode.objects.active())
    inactive = set(DiscountCode.objects.inactive())

    assert active | inactive == set(DiscountCode.objects.all())
    assert not active & inactive


def test_an_expired_code_is_inactive_despite_its_flag(expired_code):
    """The trap this split exists to avoid: is_active is True here."""
    assert expired_code.is_active
    assert expired_code in DiscountCode.objects.inactive()


# --- The back-office list ---------------------------------------------------


def test_the_list_shows_only_active_codes_by_default(
    client, staff_user, percent_code, expired_code, retired_code
):
    client.force_login(staff_user)

    body = client.get(reverse("orders:manage_discounts")).content.decode()

    assert "THOUGHTS10" in body
    assert "LASTQUARTER" not in body
    assert "WELCOMEBACK" not in body


def test_the_inactive_tab_shows_the_rest(
    client, staff_user, percent_code, expired_code, retired_code
):
    client.force_login(staff_user)

    body = client.get(
        reverse("orders:manage_discounts"), {"show": "inactive"}
    ).content.decode()

    assert "THOUGHTS10" not in body
    assert "LASTQUARTER" in body
    assert "WELCOMEBACK" in body


def test_the_all_tab_shows_everything(
    client, staff_user, percent_code, expired_code, retired_code
):
    client.force_login(staff_user)

    body = client.get(
        reverse("orders:manage_discounts"), {"show": "all"}
    ).content.decode()

    assert "THOUGHTS10" in body
    assert "LASTQUARTER" in body
    assert "WELCOMEBACK" in body


def test_a_nonsense_bucket_falls_back_to_active(
    client, staff_user, percent_code, expired_code
):
    client.force_login(staff_user)

    body = client.get(
        reverse("orders:manage_discounts"), {"show": "sideways"}
    ).content.decode()

    assert "THOUGHTS10" in body
    assert "LASTQUARTER" not in body


def test_the_list_shows_usage_against_the_limits(client, staff_user, db):
    DiscountCode.objects.create(
        code="FIRSTFIFTY",
        kind=DiscountCode.Kind.AMOUNT,
        value=Decimal("50.00"),
        per_user_limit=2,
        total_limit=50,
    )
    client.force_login(staff_user)

    body = client.get(reverse("orders:manage_discounts")).content.decode()

    assert "0 / 50" in body
    assert "2 per customer" in body


def test_an_empty_active_bucket_offers_the_inactive_one(
    client, staff_user, retired_code
):
    """Codes exist, just none active — that is not the same as an empty store."""
    client.force_login(staff_user)

    body = client.get(reverse("orders:manage_discounts")).content.decode()

    assert "No active discount codes" in body
    assert "Reinstate an old one" in body
