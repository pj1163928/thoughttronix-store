"""Typing a code that already exists, and what the back office offers instead.

The point of the flow is that a name clash is never a dead end. Each
test here pins one of the four statuses a clash can hit, because they
offer genuinely different things: only a retired code can come back
unchanged, and only new dates can revive an expired one.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import DiscountCode, Order
from .test_discount_limits import redeem


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


@pytest.fixture
def retired_code(db):
    return DiscountCode.objects.create(
        code="WELCOMEBACK",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("20"),
        is_active=False,
    )


def new_terms(**overrides):
    """A complete create-form payload, so tests vary only what they mean to."""
    return {
        "code": "WELCOMEBACK",
        "kind": DiscountCode.Kind.PERCENT,
        "value": "35",
        "applies_to": DiscountCode.Scope.ALL,
        "per_user_limit": "2",
        "total_limit": "",
        "starts_at": "",
        "ends_at": "",
    } | overrides


# --- The offer --------------------------------------------------------------


def test_a_clash_with_a_retired_code_offers_both_routes(staff_client, retired_code):
    response = staff_client.post(reverse("orders:manage_discount_create"), new_terms())
    body = response.content.decode()

    assert response.status_code == 200
    assert DiscountCode.objects.count() == 1  # nothing was created
    assert "already exists" in body
    assert "Reinstate as it was" in body
    assert "Reinstate with my new terms" in body
    assert "Start the usage count over" in body


def test_the_offer_shows_both_sets_of_terms(staff_client, retired_code):
    body = staff_client.post(
        reverse("orders:manage_discount_create"), new_terms()
    ).content.decode()

    assert "20% off your order" in body  # what exists
    assert "35% off your order" in body  # what was typed


def test_a_clash_with_an_expired_code_offers_only_new_terms(staff_client, db):
    DiscountCode.objects.create(
        code="LASTQUARTER",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("25"),
        ends_at=timezone.now() - timedelta(days=1),
    )

    body = staff_client.post(
        reverse("orders:manage_discount_create"), new_terms(code="LASTQUARTER")
    ).content.decode()

    assert "Reinstate as it was" not in body
    assert "Reinstate with my new terms" in body
    assert "only new dates can revive it" in body


def test_a_clash_with_a_live_code_offers_no_reinstatement(staff_client, percent_code):
    body = staff_client.post(
        reverse("orders:manage_discount_create"), new_terms(code="thoughts10")
    ).content.decode()

    assert "Reinstate" not in body
    assert "nothing to" in body
    assert "Edit THOUGHTS10" in body


def test_a_clash_is_found_whatever_the_capitalisation(staff_client, retired_code):
    body = staff_client.post(
        reverse("orders:manage_discount_create"), new_terms(code="  welcomeback  ")
    ).content.decode()

    assert "already exists" in body
    assert DiscountCode.objects.count() == 1


def test_other_mistakes_are_still_ordinary_errors(staff_client, retired_code):
    """A bad value gets the form back, not a reinstatement offer."""
    body = staff_client.post(
        reverse("orders:manage_discount_create"), new_terms(value="150")
    ).content.decode()

    assert "A percentage can&#x27;t be more than 100." in body
    assert "Reinstate" not in body


# --- Reinstating ------------------------------------------------------------


def test_reinstating_as_it_was_leaves_the_terms_alone(staff_client, retired_code):
    response = staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(),  # the typed terms ride along but must be ignored
        follow=True,
    )

    retired_code.refresh_from_db()
    assert retired_code.is_active
    assert retired_code.value == Decimal("20")  # not the 35 that was typed
    assert retired_code.per_user_limit == 1  # not the 2 that was typed
    assert "WELCOMEBACK is back." in response.content.decode()


def test_reinstating_with_new_terms_applies_them(staff_client, retired_code):
    response = staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(apply_terms="1"),
        follow=True,
    )

    retired_code.refresh_from_db()
    assert retired_code.is_active
    assert retired_code.value == Decimal("35")
    assert retired_code.per_user_limit == 2
    assert "WELCOMEBACK is back with your new terms." in response.content.decode()


def test_reinstating_with_new_terms_keeps_a_product_set(
    staff_client, retired_code, product, featured_product
):
    """The hidden fields carry every ticked box, not just the first."""
    staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(
            apply_terms="1",
            applies_to=DiscountCode.Scope.SELECTED,
            products=[product.pk, featured_product.pk],
        ),
    )

    retired_code.refresh_from_db()
    assert retired_code.applies_to == DiscountCode.Scope.SELECTED
    assert set(retired_code.products.all()) == {product, featured_product}


def test_reinstating_does_not_reset_the_count_unless_asked(
    staff_client, retired_code, customer
):
    redeem(retired_code, customer)

    staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(),
    )

    retired_code.refresh_from_db()
    assert retired_code.counting_since is None
    assert retired_code.times_used() == 1
    assert retired_code.unusable_reason(customer) == "You've already used WELCOMEBACK."


def test_resetting_the_count_frees_past_customers(staff_client, retired_code, customer):
    order = redeem(retired_code, customer)

    response = staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(reset_usage="on"),
        follow=True,
    )

    retired_code.refresh_from_db()
    assert retired_code.counting_since is not None
    assert retired_code.times_used() == 0
    assert retired_code.unusable_reason(customer) is None
    assert "usage count starts over" in response.content.decode()

    # The order itself is untouched — it keeps the discount it was given.
    order.refresh_from_db()
    assert order.discount_code == "WELCOMEBACK"
    assert order.discount_amount == Decimal("10.00")


def test_a_sold_out_code_comes_back_usable_when_the_count_is_reset(
    staff_client, db, customer
):
    code = DiscountCode.objects.create(
        code="SOLDOUT",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        per_user_limit=None,
        total_limit=1,
        is_active=False,
    )
    redeem(code, customer)
    assert code.unusable_reason(customer) == "SOLDOUT is no longer available."

    staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": code.pk}),
        {"reset_usage": "on"},
    )

    code.refresh_from_db()
    assert code.unusable_reason(customer) is None


def test_reinstating_an_expired_code_as_is_is_refused(staff_client, expired_code):
    """There is no button for this, but a hand-made POST must not lie."""
    response = staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": expired_code.pk}),
        {},
        follow=True,
    )

    expired_code.refresh_from_db()
    assert expired_code.status == "expired"
    assert "already expired" in response.content.decode()


def test_new_dates_genuinely_revive_an_expired_code(staff_client, expired_code):
    ends = (timezone.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")

    staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": expired_code.pk}),
        new_terms(code="LASTQUARTER", apply_terms="1", ends_at=ends),
    )

    expired_code.refresh_from_db()
    assert expired_code.status == "live"


def test_a_cancelled_order_does_not_block_reinstatement(
    staff_client, retired_code, customer
):
    redeem(retired_code, customer, status=Order.Status.CANCELLED)

    staff_client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk}),
        new_terms(),
    )

    retired_code.refresh_from_db()
    assert retired_code.times_used() == 0
    assert retired_code.unusable_reason(customer) is None


def test_customers_cannot_reinstate_codes(client, customer, retired_code):
    client.force_login(customer)

    response = client.post(
        reverse("orders:manage_discount_reinstate", kwargs={"pk": retired_code.pk})
    )

    assert response.status_code == 403
    retired_code.refresh_from_db()
    assert not retired_code.is_active


# --- The edit form is deliberately not part of this ------------------------


def test_renaming_a_code_onto_another_is_still_a_plain_error(
    staff_client, percent_code, retired_code
):
    """Reinstatement is an answer to creating a duplicate, not to editing one."""
    staff_client.post(
        reverse("orders:manage_discount_update", kwargs={"pk": retired_code.pk}),
        new_terms(code="THOUGHTS10"),
    )

    retired_code.refresh_from_db()
    assert retired_code.code == "WELCOMEBACK"
    assert not retired_code.is_active
