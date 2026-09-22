from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse

from products.models import Product

from .models import Cart, CartItem

# --- Model behavior ---------------------------------------------------------


def test_cart_str(cart):
    assert str(cart) == "Cart for customer"


def test_cart_item_str(cart_item):
    assert str(cart_item) == "2 × Seraphine Home Hub"


def test_for_user_creates_the_cart_once(customer):
    first = Cart.for_user(customer)
    second = Cart.for_user(customer)

    assert first == second
    assert Cart.objects.count() == 1


def test_add_creates_a_line_at_quantity_one(cart, product):
    item = cart.add(product)

    assert item.quantity == 1
    assert cart.items.count() == 1


def test_duplicate_add_increments_instead_of_duplicating(cart, product):
    cart.add(product)
    item = cart.add(product)

    assert item.quantity == 2
    assert cart.items.count() == 1


def test_cart_product_pair_is_unique(cart_item):
    with pytest.raises(IntegrityError):
        CartItem.objects.create(cart=cart_item.cart, product=cart_item.product)


def test_line_total(cart_item):
    assert cart_item.line_total == Decimal("699.98")


def test_cart_subtotal_sums_all_lines(cart, cart_item, category):
    other = Product.objects.create(
        name="Charging Pillow",
        slug="charging-pillow",
        price=Decimal("69.00"),
        category=category,
    )
    cart.add(other)

    assert cart.subtotal() == Decimal("768.98")


def test_cart_total_matches_the_subtotal_without_a_code(cart, cart_item):
    assert cart.total() == cart.subtotal() == Decimal("699.98")


def test_empty_cart_total_is_zero(cart):
    assert cart.subtotal() == Decimal("0.00")
    assert cart.total() == Decimal("0.00")
    assert cart.item_count() == 0


def test_item_count_sums_quantities(cart, cart_item, unavailable_product):
    CartItem.objects.create(cart=cart, product=unavailable_product, quantity=3)

    assert cart.item_count() == 5


def test_increment(cart_item):
    cart_item.increment()

    cart_item.refresh_from_db()
    assert cart_item.quantity == 3


def test_decrement_stops_at_one(cart, product):
    item = cart.add(product)

    item.decrement()

    item.refresh_from_db()
    assert item.quantity == 1


# --- The cart page -----------------------------------------------------------


def test_cart_page_requires_login(client, db):
    response = client.get(reverse("orders:cart"))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url


def test_cart_page_shows_lines_and_total(client, customer, cart_item):
    client.force_login(customer)

    response = client.get(reverse("orders:cart"))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert cart_item.product.name in page
    assert "699.98" in page
    assert "Checkout" in page


def test_empty_cart_shows_empty_state(client, customer):
    client.force_login(customer)

    response = client.get(reverse("orders:cart"))

    assert "Your cart is empty" in response.content.decode()


def test_customers_see_only_their_own_cart(client, customer, cart_item):
    other = get_user_model().objects.create_user(username="other", password="x")
    client.force_login(other)

    response = client.get(reverse("orders:cart"))

    assert cart_item.product.name not in response.content.decode()


# --- Add to cart (HTMX) ------------------------------------------------------


def test_anonymous_add_redirects_to_login(client, product):
    response = client.post(reverse("orders:add", kwargs={"pk": product.pk}))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url


def test_catalog_prompts_anonymous_users_to_sign_in(client, product):
    response = client.get(reverse("products:catalog"))

    page = response.content.decode()
    assert f"{reverse('accounts:login')}?next=" in page


def test_add_returns_partial_with_oob_badge(client, customer, product):
    client.force_login(customer)

    response = client.post(reverse("orders:add", kwargs={"pk": product.pk}))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert "In cart (1)" in page
    assert 'hx-swap-oob="true"' in page
    assert customer.cart.item_count() == 1


def test_add_twice_increments(client, customer, product):
    client.force_login(customer)
    client.post(reverse("orders:add", kwargs={"pk": product.pk}))

    response = client.post(reverse("orders:add", kwargs={"pk": product.pk}))

    assert "In cart (2)" in response.content.decode()
    assert customer.cart.items.count() == 1


def test_add_unavailable_product_404s(client, customer, unavailable_product):
    client.force_login(customer)

    response = client.post(reverse("orders:add", kwargs={"pk": unavailable_product.pk}))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert not CartItem.objects.exists()


def test_catalog_shows_in_cart_state(client, customer, cart_item):
    client.force_login(customer)

    response = client.get(reverse("products:catalog"))

    assert "In cart (2)" in response.content.decode()


def test_navbar_badge_shows_unit_count(client, customer, cart_item):
    client.force_login(customer)

    response = client.get(reverse("products:catalog"))

    page = response.content.decode()
    assert 'id="cart-badge"' in page
    assert '<span class="badge badge-primary badge-sm indicator-item">2</span>' in page


# --- Line mutations (HTMX) ---------------------------------------------------


def test_increment_endpoint_returns_cart_partial(client, customer, cart_item):
    client.force_login(customer)

    response = client.post(reverse("orders:increment", kwargs={"pk": cart_item.pk}))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert 'hx-swap-oob="true"' in page
    cart_item.refresh_from_db()
    assert cart_item.quantity == 3


def test_decrement_endpoint_stops_at_one(client, customer, cart, product):
    item = cart.add(product)
    client.force_login(customer)

    client.post(reverse("orders:decrement", kwargs={"pk": item.pk}))

    item.refresh_from_db()
    assert item.quantity == 1


def test_remove_endpoint_deletes_the_line(client, customer, cart_item):
    client.force_login(customer)

    response = client.post(reverse("orders:remove", kwargs={"pk": cart_item.pk}))

    assert not CartItem.objects.exists()
    # Removing the last line swaps in the designed empty state.
    assert "Your cart is empty" in response.content.decode()


def test_cannot_mutate_another_customers_line(client, cart_item):
    other = get_user_model().objects.create_user(username="other", password="x")
    client.force_login(other)

    response = client.post(reverse("orders:remove", kwargs={"pk": cart_item.pk}))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert CartItem.objects.count() == 1
