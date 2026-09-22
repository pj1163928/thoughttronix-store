"""Back-office order management: access control, the status filter, updates."""

from decimal import Decimal
from http import HTTPStatus

import pytest
from django.urls import reverse

from .models import DiscountCode, Order
from .services import place_order
from .test_checkout_form import VALID_DATA

pytestmark = pytest.mark.django_db


@pytest.fixture
def order(cart, cart_item):
    return place_order(cart, cart.user, dict(VALID_DATA))


@pytest.fixture
def shipped_order(customer):
    return Order.objects.create(
        user=customer,
        status=Order.Status.SHIPPED,
        total=Decimal("9.00"),
        email="casey@example.com",
        shipping_name="Casey Monroe",
        shipping_street="9 Synapse Court",
        shipping_city="Canyon",
        shipping_state="TX",
        shipping_zip="79015",
        billing_name="Casey Monroe",
        billing_street="9 Synapse Court",
        billing_city="Canyon",
        billing_state="TX",
        billing_zip="79015",
        card_last4="4242",
    )


def manage_urls(order):
    return [
        reverse("orders:manage_orders"),
        reverse("orders:manage_order_detail", kwargs={"pk": order.pk}),
        reverse("orders:manage_order_status", kwargs={"pk": order.pk}),
    ]


# --- Access control ----------------------------------------------------------


def test_anonymous_users_are_sent_to_login(client, order):
    for url in manage_urls(order):
        response = client.get(url)

        assert response.status_code == HTTPStatus.FOUND, url
        assert reverse("accounts:login") in response.url


def test_customers_get_403(client, customer, order):
    client.force_login(customer)

    for url in manage_urls(order):
        assert client.get(url).status_code == HTTPStatus.FORBIDDEN, url


# --- The order list ----------------------------------------------------------


def test_staff_see_every_customers_orders(client, staff_user, order, shipped_order):
    client.force_login(staff_user)

    page = client.get(reverse("orders:manage_orders")).content.decode()

    assert order.number in page
    assert shipped_order.number in page
    assert order.user.username in page


def test_list_filters_by_status(client, staff_user, order, shipped_order):
    client.force_login(staff_user)

    page = client.get(
        reverse("orders:manage_orders"), {"status": "SHIPPED"}
    ).content.decode()

    assert shipped_order.number in page
    assert order.number not in page


def test_unknown_status_filter_is_ignored(client, staff_user, order, shipped_order):
    client.force_login(staff_user)

    page = client.get(
        reverse("orders:manage_orders"), {"status": "TELEPORTED"}
    ).content.decode()

    assert order.number in page
    assert shipped_order.number in page


def test_list_has_a_designed_empty_state(client, staff_user):
    client.force_login(staff_user)

    assert (
        "No orders yet" in client.get(reverse("orders:manage_orders")).content.decode()
    )


def test_filtered_empty_state_offers_to_clear(client, staff_user, order):
    client.force_login(staff_user)

    page = client.get(
        reverse("orders:manage_orders"), {"status": "DELIVERED"}
    ).content.decode()

    assert "No orders with that status" in page


# --- Order detail and status updates -----------------------------------------


def test_detail_shows_the_customer_and_both_addresses(client, staff_user, order):
    client.force_login(staff_user)

    page = client.get(
        reverse("orders:manage_order_detail", kwargs={"pk": order.pk})
    ).content.decode()

    assert order.number in page
    assert order.user.username in page
    assert "Shipping address" in page
    assert "Billing address" in page
    assert "card ending 4242" in page


def test_staff_can_update_an_orders_status(client, staff_user, order):
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_order_status", kwargs={"pk": order.pk}),
        {"status": "SHIPPED"},
        follow=True,
    )

    order.refresh_from_db()
    assert order.status == Order.Status.SHIPPED
    assert "is now shipped" in response.content.decode()


def test_an_unknown_status_is_rejected(client, staff_user, order):
    client.force_login(staff_user)

    client.post(
        reverse("orders:manage_order_status", kwargs={"pk": order.pk}),
        {"status": "TELEPORTED"},
    )

    order.refresh_from_db()
    assert order.status == Order.Status.PLACED


# --- Discount codes ---------------------------------------------------------


def test_customers_cannot_reach_the_discount_pages(client, customer):
    client.force_login(customer)

    for name in ("orders:manage_discounts", "orders:manage_discount_create"):
        assert client.get(reverse(name)).status_code == HTTPStatus.FORBIDDEN


def test_the_discount_list_has_an_empty_state(client, staff_user):
    client.force_login(staff_user)

    page = client.get(reverse("orders:manage_discounts")).content.decode()

    assert "No discount codes yet" in page


def test_staff_can_create_a_code(client, staff_user, product):
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_discount_create"),
        {
            "code": "spring50",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "50",
            "product": product.pk,
            "starts_at": "",
            "ends_at": "",
        },
        follow=True,
    )

    code = DiscountCode.objects.get()
    assert code.code == "SPRING50"
    assert code.product == product
    assert code.is_active
    assert "SPRING50 created." in response.content.decode()


def test_a_percentage_over_a_hundred_is_rejected(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_discount_create"),
        {"code": "TOOGOOD", "kind": DiscountCode.Kind.PERCENT, "value": "150"},
    )

    assert response.status_code == HTTPStatus.OK  # the form, re-rendered
    assert not DiscountCode.objects.exists()
    assert "A percentage can&#x27;t be more than 100." in response.content.decode()


def test_a_window_that_ends_before_it_starts_is_rejected(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_discount_create"),
        {
            "code": "BACKWARDS",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "10",
            "starts_at": "2026-10-01T00:00",
            "ends_at": "2026-09-01T00:00",
        },
    )

    assert not DiscountCode.objects.exists()
    assert "The end must come after the start." in response.content.decode()


def test_retiring_a_code_leaves_its_terms_alone(client, staff_user, percent_code):
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_discount_toggle", kwargs={"pk": percent_code.pk}),
        follow=True,
    )

    percent_code.refresh_from_db()
    assert not percent_code.is_active
    assert percent_code.value == Decimal("10")
    assert "Past orders are unchanged" in response.content.decode()


def test_a_retired_code_can_be_reactivated(client, staff_user, percent_code):
    percent_code.is_active = False
    percent_code.save()
    client.force_login(staff_user)

    client.post(
        reverse("orders:manage_discount_toggle", kwargs={"pk": percent_code.pk})
    )

    percent_code.refresh_from_db()
    assert percent_code.is_active


def test_the_edit_form_cannot_switch_a_code_off(client, staff_user, percent_code):
    """``is_active`` is not a field here — retiring is its own action."""
    client.force_login(staff_user)

    client.post(
        reverse("orders:manage_discount_update", kwargs={"pk": percent_code.pk}),
        {
            "code": "THOUGHTS10",
            "kind": DiscountCode.Kind.PERCENT,
            "value": "15",
            "is_active": "false",
            "starts_at": "",
            "ends_at": "",
        },
    )

    percent_code.refresh_from_db()
    assert percent_code.value == Decimal("15")
    assert percent_code.is_active


def test_a_duplicate_code_in_a_different_case_is_caught_by_the_form(
    client, staff_user, percent_code
):
    """Normalisation happens before the unique check, not after it."""
    client.force_login(staff_user)

    response = client.post(
        reverse("orders:manage_discount_create"),
        {"code": "thoughts10", "kind": DiscountCode.Kind.PERCENT, "value": "5"},
    )

    assert response.status_code == HTTPStatus.OK
    assert DiscountCode.objects.count() == 1
    assert "already exists" in response.content.decode()
