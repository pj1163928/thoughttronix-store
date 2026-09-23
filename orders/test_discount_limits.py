"""Usage limits: who has used a code, how often, and who may still use it.

The counting rules are tested before the enforcement is, because every
checkpoint asks the same two methods and a wrong count would be a wrong
answer in four places at once. The cancellation case gets its own test
rather than a branch in another: releasing a use is a deliberate policy,
not an implementation detail, and it should fail loudly if reversed.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .forms import ApplyDiscountForm
from .models import Cart, CartItem, DiscountCode, Order
from .services import place_order
from .test_checkout_form import VALID_DATA


@pytest.fixture
def checkout_data():
    return dict(VALID_DATA)


@pytest.fixture
def other_customer(db):
    return get_user_model().objects.create_user(
        username="othercustomer", password="other123"
    )


def redeem(code, user, status=Order.Status.PLACED, when=None):
    """Record a redemption the way ``place_order`` would, without a checkout."""
    return Order.objects.create(
        user=user,
        status=status,
        total=Decimal("100.00"),
        email="casey@example.com",
        shipping_name="Casey",
        shipping_street="12 Cortex Lane",
        shipping_city="Canyon",
        shipping_state="TX",
        shipping_zip="79015",
        billing_name="Casey",
        billing_street="12 Cortex Lane",
        billing_city="Canyon",
        billing_state="TX",
        billing_zip="79015",
        card_last4="4242",
        discount_code_used=code,
        discount_code=code.code,
        discount_amount=Decimal("10.00"),
        created_at=when or timezone.now(),
    )


# --- Counting ---------------------------------------------------------------


def test_a_new_code_is_one_per_customer_by_default(db):
    code = DiscountCode.objects.create(
        code="DEFAULTS", kind=DiscountCode.Kind.PERCENT, value=Decimal("10")
    )

    assert code.per_user_limit == 1
    assert code.total_limit is None


def test_uses_are_counted_from_the_orders(once_per_customer_code, customer):
    assert once_per_customer_code.times_used() == 0

    redeem(once_per_customer_code, customer)

    assert once_per_customer_code.times_used() == 1
    assert once_per_customer_code.times_used_by(customer) == 1


def test_a_cancelled_order_gives_the_use_back(once_per_customer_code, customer):
    """The policy in one test: cancelling releases the redemption."""
    order = redeem(once_per_customer_code, customer)
    assert once_per_customer_code.times_used() == 1

    order.status = Order.Status.CANCELLED
    order.save()

    assert once_per_customer_code.times_used() == 0
    assert once_per_customer_code.unusable_reason(customer) is None


def test_counting_since_ignores_earlier_orders(once_per_customer_code, customer):
    redeem(once_per_customer_code, customer, when=timezone.now() - timedelta(days=30))
    assert once_per_customer_code.times_used() == 1

    once_per_customer_code.counting_since = timezone.now() - timedelta(days=1)
    once_per_customer_code.save()

    assert once_per_customer_code.times_used() == 0


def test_the_annotation_agrees_with_the_method(
    once_per_customer_code, customer, other_customer
):
    """``with_usage`` is SQL's copy of ``counted_orders`` — they must not drift."""
    redeem(once_per_customer_code, customer)
    redeem(once_per_customer_code, other_customer)
    redeem(once_per_customer_code, customer, status=Order.Status.CANCELLED)

    annotated = DiscountCode.objects.with_usage().get(pk=once_per_customer_code.pk)

    assert annotated.used == once_per_customer_code.times_used() == 2


# --- Eligibility ------------------------------------------------------------


def test_a_second_use_by_the_same_customer_is_refused(once_per_customer_code, customer):
    redeem(once_per_customer_code, customer)

    assert (
        once_per_customer_code.unusable_reason(customer)
        == "You've already used ONCEONLY."
    )


def test_one_customers_use_does_not_block_another(
    once_per_customer_code, customer, other_customer
):
    redeem(once_per_customer_code, customer)

    assert once_per_customer_code.unusable_reason(other_customer) is None


def test_a_multi_use_limit_allows_exactly_that_many(db, customer):
    code = DiscountCode.objects.create(
        code="THRICE",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        per_user_limit=3,
    )

    for _ in range(2):
        redeem(code, customer)
    assert code.unusable_reason(customer) is None

    redeem(code, customer)
    assert "3 times, which is the limit" in code.unusable_reason(customer)


def test_an_unlimited_code_never_runs_out(percent_code, customer):
    for _ in range(5):
        redeem(percent_code, customer)

    assert percent_code.unusable_reason(customer) is None


def test_a_total_limit_stops_everyone(db, customer, other_customer):
    code = DiscountCode.objects.create(
        code="FIRSTTWO",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        per_user_limit=None,
        total_limit=2,
    )
    redeem(code, customer)
    redeem(code, other_customer)

    assert code.unusable_reason(customer) == "FIRSTTWO has been fully claimed."
    assert code.unusable_reason(other_customer) == "FIRSTTWO has been fully claimed."


def test_the_window_is_reported_before_the_limit(db, customer):
    """An expired code says it expired, not that you've used it up."""
    code = DiscountCode.objects.create(
        code="OLDNEWS",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        total_limit=1,
        ends_at=timezone.now() - timedelta(days=1),
    )
    redeem(code, customer)

    assert "expired on" in code.unusable_reason(customer)


# --- The three checkpoints --------------------------------------------------


def test_the_cart_box_refuses_a_code_this_customer_used(
    cart, cart_item, once_per_customer_code
):
    redeem(once_per_customer_code, cart.user)

    form = ApplyDiscountForm({"code": "ONCEONLY"}, cart=cart)

    assert not form.is_valid()
    assert form.errors["code"] == ["You've already used ONCEONLY."]


def test_a_cart_stops_discounting_once_the_code_runs_out(
    cart, cart_item, once_per_customer_code
):
    """Applied first, exhausted after — the total must tell the truth."""
    cart.discount_code = once_per_customer_code
    cart.save()
    assert cart.discount_amount() == Decimal("70.00")

    redeem(once_per_customer_code, cart.user)

    assert cart.discount_amount() == Decimal("0.00")
    assert cart.total() == cart.subtotal()
    assert cart.discount_problem() == "You've already used ONCEONLY."


def test_the_till_refuses_a_code_that_ran_out(
    cart, cart_item, once_per_customer_code, checkout_data
):
    cart.discount_code = once_per_customer_code
    cart.save()
    redeem(once_per_customer_code, cart.user)

    with pytest.raises(ValueError, match="You've already used ONCEONLY."):
        place_order(cart, cart.user, checkout_data)

    assert cart.items.exists()  # the transaction rolled nothing forward


def test_checkout_bounces_a_cart_whose_code_ran_out(
    client, cart, cart_item, once_per_customer_code
):
    cart.discount_code = once_per_customer_code
    cart.save()
    redeem(once_per_customer_code, cart.user)
    client.force_login(cart.user)

    response = client.get(reverse("orders:checkout"), follow=True)

    assert response.redirect_chain[-1][0] == reverse("orders:cart")
    assert "You&#x27;ve already used ONCEONLY." in response.content.decode()
    cart.refresh_from_db()
    assert cart.discount_code is None


def test_a_real_checkout_consumes_the_one_use(
    cart, cart_item, once_per_customer_code, checkout_data
):
    """End to end: place an order, then the same code is spent."""
    cart.discount_code = once_per_customer_code
    cart.save()

    order = place_order(cart, cart.user, checkout_data)

    assert order.discount_amount == Decimal("70.00")
    assert once_per_customer_code.times_used_by(cart.user) == 1
    assert once_per_customer_code.unusable_reason(cart.user) is not None


def test_a_second_customer_can_still_use_it(
    cart, cart_item, once_per_customer_code, checkout_data, other_customer, product
):
    cart.discount_code = once_per_customer_code
    cart.save()
    place_order(cart, cart.user, checkout_data)
    assert once_per_customer_code.times_used_by(cart.user) == 1

    other_cart = Cart.for_user(other_customer)
    CartItem.objects.create(cart=other_cart, product=product, quantity=2)
    other_cart.discount_code = once_per_customer_code
    other_cart.save()

    assert other_cart.discount_amount() == Decimal("70.00")
