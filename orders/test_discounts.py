"""Discount code tests: the window, the money, and the two entry points.

The money cases are the priority — a wrong answer here is a wrong
charge. The window is tested at its boundaries rather than in the
middle, because that is where an off-by-one would actually live.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from products.models import Product

from .forms import ApplyDiscountForm
from .models import CartItem, DiscountCode

# --- The window -------------------------------------------------------------


def test_a_code_with_no_window_is_always_live(percent_code):
    assert percent_code.is_live()
    assert percent_code.status == "live"


def test_a_retired_code_is_not_live(percent_code):
    percent_code.is_active = False

    assert not percent_code.is_live()
    assert percent_code.status == "retired"


@pytest.mark.django_db
def test_the_window_is_closed_at_its_start_and_open_at_its_end():
    """``starts_at`` is inclusive, ``ends_at`` exclusive — checked on the second."""
    start = timezone.now()
    end = start + timedelta(days=7)
    code = DiscountCode.objects.create(
        code="WINDOW",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        starts_at=start,
        ends_at=end,
    )

    assert not code.is_live(start - timedelta(seconds=1))
    assert code.is_live(start)
    assert code.is_live(end - timedelta(seconds=1))
    assert not code.is_live(end)


def test_an_expired_code_reports_itself_expired(expired_code):
    assert not expired_code.is_live()
    assert expired_code.status == "expired"


@pytest.mark.django_db
def test_a_future_code_reports_itself_scheduled():
    code = DiscountCode.objects.create(
        code="PRESEASON",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("15"),
        starts_at=timezone.now() + timedelta(days=3),
    )

    assert not code.is_live()
    assert code.status == "scheduled"


def test_live_queryset_matches_is_live(percent_code, expired_code):
    live = DiscountCode.objects.live()

    assert percent_code in live
    assert expired_code not in live


# --- The money --------------------------------------------------------------


def test_percent_off_the_whole_order(cart, cart_item, percent_code):
    assert percent_code.discount_for(cart) == Decimal("70.00")


def test_amount_off_the_whole_order(cart, cart_item, amount_code):
    assert amount_code.discount_for(cart) == Decimal("20.00")


def test_percent_scales_with_quantity(cart, cart_item, product_code):
    """Two Seraphines at $349.99, half off, is half of both lines."""
    assert cart.subtotal() == Decimal("699.98")
    assert product_code.discount_for(cart) == Decimal("349.99")


@pytest.mark.django_db
def test_a_fixed_amount_comes_off_once_however_many_are_bought(cart, product):
    """The asymmetry with percent, asserted directly: $20 means $20."""
    CartItem.objects.create(cart=cart, product=product, quantity=3)
    code = DiscountCode.objects.create(
        code="TWENTY",
        kind=DiscountCode.Kind.AMOUNT,
        value=Decimal("20.00"),
        product=product,
    )

    assert cart.subtotal() == Decimal("1049.97")
    assert code.discount_for(cart) == Decimal("20.00")


def test_a_product_code_ignores_the_rest_of_the_cart(
    cart, cart_item, product_code, category
):
    cart.add(
        Product.objects.create(
            name="Charging Pillow",
            slug="charging-pillow",
            price=Decimal("69.00"),
            category=category,
        )
    )

    assert cart.subtotal() == Decimal("768.98")
    assert product_code.discount_for(cart) == Decimal("349.99")


def test_a_product_code_discounts_nothing_when_its_product_is_absent(
    cart, product_code, category
):
    cart.add(
        Product.objects.create(
            name="Charging Pillow",
            slug="charging-pillow",
            price=Decimal("69.00"),
            category=category,
        )
    )

    assert product_code.discount_for(cart) == Decimal("0.00")


@pytest.mark.django_db
def test_a_discount_never_exceeds_what_it_discounts(cart, product):
    CartItem.objects.create(cart=cart, product=product)
    code = DiscountCode.objects.create(
        code="TOOMUCH", kind=DiscountCode.Kind.AMOUNT, value=Decimal("500.00")
    )
    cart.discount_code = code

    assert code.discount_for(cart) == Decimal("349.99")
    assert cart.total() == Decimal("0.00")


@pytest.mark.django_db
def test_percentages_round_to_cents(cart, category):
    """A third off $10.00 is $3.33, not a fraction of a cent."""
    product = Product.objects.create(
        name="Thought Stub",
        slug="thought-stub",
        price=Decimal("10.00"),
        category=category,
    )
    CartItem.objects.create(cart=cart, product=product)
    code = DiscountCode.objects.create(
        code="THIRD", kind=DiscountCode.Kind.PERCENT, value=Decimal("33.33")
    )

    assert code.discount_for(cart) == Decimal("3.33")


def test_an_empty_cart_discounts_to_zero(cart, percent_code):
    assert percent_code.discount_for(cart) == Decimal("0.00")


# --- The cart's view of it --------------------------------------------------


def test_the_cart_total_drops_by_the_discount(cart, cart_item, percent_code):
    cart.discount_code = percent_code

    assert cart.subtotal() == Decimal("699.98")
    assert cart.discount_amount() == Decimal("70.00")
    assert cart.total() == Decimal("629.98")


def test_an_expired_code_on_a_cart_discounts_nothing(cart, cart_item, expired_code):
    cart.discount_code = expired_code

    assert cart.discount_amount() == Decimal("0.00")
    assert cart.total() == cart.subtotal()


# --- Labels and normalisation -----------------------------------------------


def test_codes_are_stored_in_capitals(db):
    code = DiscountCode.objects.create(
        code="  summer50  ", kind=DiscountCode.Kind.PERCENT, value=Decimal("50")
    )

    assert code.code == "SUMMER50"


def test_a_code_is_found_however_it_is_typed(percent_code):
    assert DiscountCode.objects.find("  thoughts10 ") == percent_code
    assert DiscountCode.objects.find("nonsense") is None
    assert DiscountCode.objects.find("") is None


def test_labels_read_as_english(percent_code, product_code, amount_code):
    assert percent_code.label == "10% off your order"
    assert product_code.label == "50% off Seraphine Home Hub"
    assert amount_code.label == "$20.00 off your order"


# --- The apply form ---------------------------------------------------------


def test_a_good_code_cleans_to_the_code_itself(cart, cart_item, percent_code):
    form = ApplyDiscountForm({"code": "thoughts10"}, cart=cart)

    assert form.is_valid()
    assert form.cleaned_data["code"] == percent_code


def test_an_unknown_code_is_rejected_by_name(cart, cart_item):
    form = ApplyDiscountForm({"code": "NOPE"}, cart=cart)

    assert not form.is_valid()
    assert form.errors["code"] == ["We don't have a code by that name."]


def test_an_expired_code_says_so(cart, cart_item, expired_code):
    form = ApplyDiscountForm({"code": "LASTQUARTER"}, cart=cart)

    assert not form.is_valid()
    assert "expired on" in form.errors["code"][0]


def test_a_retired_code_says_so(cart, cart_item, percent_code):
    percent_code.is_active = False
    percent_code.save()

    form = ApplyDiscountForm({"code": "THOUGHTS10"}, cart=cart)

    assert not form.is_valid()
    assert form.errors["code"] == ["THOUGHTS10 is no longer available."]


def test_a_product_code_names_the_product_it_needs(cart, product_code, category):
    cart.add(
        Product.objects.create(
            name="Charging Pillow",
            slug="charging-pillow",
            price=Decimal("69.00"),
            category=category,
        )
    )

    form = ApplyDiscountForm({"code": "SERAPHINE50"}, cart=cart)

    assert not form.is_valid()
    assert form.errors["code"] == [
        "SERAPHINE50 applies to Seraphine Home Hub, which isn't in your cart."
    ]


# --- The cart page ----------------------------------------------------------


@pytest.fixture
def signed_in(client, customer):
    client.force_login(customer)
    return client


def test_applying_a_code_attaches_it_and_shows_the_saving(
    signed_in, cart, cart_item, percent_code
):
    response = signed_in.post(reverse("orders:apply_discount"), {"code": "thoughts10"})

    assert response.status_code == 200
    cart.refresh_from_db()
    assert cart.discount_code == percent_code
    assert "You're saving $70.00." in response.content.decode()


def test_an_expired_code_renders_its_message_and_changes_nothing(
    signed_in, cart, cart_item, expired_code
):
    """The requirement in one test: a message, a whole page, an untouched cart."""
    response = signed_in.post(reverse("orders:apply_discount"), {"code": "LASTQUARTER"})

    assert response.status_code == 200
    assert "expired on" in response.content.decode()
    cart.refresh_from_db()
    assert cart.discount_code is None
    assert cart.total() == Decimal("699.98")


def test_removing_a_code_detaches_it(signed_in, cart, cart_item, percent_code):
    cart.discount_code = percent_code
    cart.save()

    response = signed_in.post(reverse("orders:remove_discount"))

    assert response.status_code == 200
    cart.refresh_from_db()
    assert cart.discount_code is None


def test_the_cart_page_offers_the_discount_box(signed_in, cart, cart_item):
    response = signed_in.get(reverse("orders:cart"))

    assert response.status_code == 200
    assert "Discount code" in response.content.decode()


def test_a_kept_code_that_matches_nothing_explains_itself(
    signed_in, cart, product_code, category
):
    """Applied, then the product was removed: a note, not a silent zero."""
    cart.add(
        Product.objects.create(
            name="Charging Pillow",
            slug="charging-pillow",
            price=Decimal("69.00"),
            category=category,
        )
    )
    cart.discount_code = product_code
    cart.save()

    body = signed_in.get(reverse("orders:cart")).content.decode()

    assert "only applies to Seraphine Home Hub" in body
    assert cart.total() == Decimal("69.00")


# --- Checkout ---------------------------------------------------------------


def test_checkout_bounces_a_cart_whose_code_expired(
    signed_in, cart, cart_item, expired_code
):
    cart.discount_code = expired_code
    cart.save()

    response = signed_in.get(reverse("orders:checkout"), follow=True)

    assert response.redirect_chain[-1][0] == reverse("orders:cart")
    assert "LASTQUARTER is no longer valid" in response.content.decode()
    cart.refresh_from_db()
    assert cart.discount_code is None


def test_checkout_shows_the_discounted_total(signed_in, cart, cart_item, percent_code):
    cart.discount_code = percent_code
    cart.save()

    body = signed_in.get(reverse("orders:checkout")).content.decode()

    assert "$629.98" in body
    assert "THOUGHTS10" in body
