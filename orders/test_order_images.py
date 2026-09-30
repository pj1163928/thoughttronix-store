"""Images on the order side: the snapshot place_order takes, and the pages that show it.

The headline rule: a failed image copy must never fail an order.
"""

from decimal import Decimal

import pytest
from django.core.files.storage import default_storage
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from products import images
from products.models import Product

from . import services
from .models import Cart, OrderItem
from .services import place_order
from .test_checkout_form import VALID_DATA

pytestmark = pytest.mark.django_db


@pytest.fixture
def pictured_item(cart_item, make_image):
    """The cart's Seraphine line, with Seraphine given a real image."""
    images.set_main_image(
        cart_item.product, images.validate_image(make_image(800, 1000))
    )
    return cart_item


def order_files(media_root):
    folder = media_root / images.ORDER_FOLDER
    return list(folder.iterdir()) if folder.exists() else []


# --- place_order ------------------------------------------------------------------


def test_placing_an_order_snapshots_each_lines_image(
    cart, pictured_item, media_root, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        order = place_order(cart, cart.user, dict(VALID_DATA))

    item = order.items.get()
    assert item.image.name.startswith("orders/")
    assert (media_root / item.image.name).exists()
    assert not item.thumbnail.is_placeholder


def test_the_snapshot_waits_for_the_commit(cart, pictured_item, media_root):
    """Inside the test's transaction nothing commits, so nothing is copied."""
    order = place_order(cart, cart.user, dict(VALID_DATA))

    assert not order.items.get().image
    assert order_files(media_root) == []


def test_a_failed_copy_does_not_fail_the_order(
    cart, pictured_item, monkeypatch, django_capture_on_commit_callbacks
):
    real_save = default_storage.save

    def refuse_order_images(name, content, **kwargs):
        if name.startswith(images.ORDER_FOLDER):
            raise OSError("disk full")
        return real_save(name, content, **kwargs)

    monkeypatch.setattr(default_storage, "save", refuse_order_images)

    with django_capture_on_commit_callbacks(execute=True):
        order = place_order(cart, cart.user, dict(VALID_DATA))

    assert order.pk is not None
    assert order.total == Decimal("699.98")
    item = order.items.get()
    assert not item.image
    assert item.thumbnail.is_placeholder
    assert not cart.items.exists()


def test_even_a_crashing_snapshot_step_does_not_fail_the_order(
    cart, pictured_item, monkeypatch, django_capture_on_commit_callbacks
):
    def crash(order):
        raise RuntimeError("snapshot bug")

    monkeypatch.setattr(services, "snapshot_for_order", crash)

    with django_capture_on_commit_callbacks(execute=True):
        order = place_order(cart, cart.user, dict(VALID_DATA))

    assert order.items.get().thumbnail.is_placeholder


def test_a_rolled_back_order_copies_nothing(
    cart, pictured_item, media_root, monkeypatch, django_capture_on_commit_callbacks
):
    def explode(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(OrderItem.objects, "create", explode)

    with django_capture_on_commit_callbacks(execute=True), pytest.raises(RuntimeError):
        place_order(cart, cart.user, dict(VALID_DATA))

    assert order_files(media_root) == []


# --- The pages ---------------------------------------------------------------------


@pytest.fixture
def placed_order(cart, pictured_item, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return place_order(cart, cart.user, dict(VALID_DATA))


@pytest.mark.parametrize("page", ["orders:confirmation", "orders:detail"])
def test_customer_order_pages_show_the_snapshot(client, placed_order, page):
    client.force_login(placed_order.user)
    snapshot = placed_order.items.get().image.name

    html = client.get(reverse(page, kwargs={"pk": placed_order.pk})).content.decode()

    assert f"/media/{snapshot}" in html


def test_order_history_shows_the_snapshot(client, placed_order):
    client.force_login(placed_order.user)

    html = client.get(reverse("orders:history")).content.decode()

    assert f"/media/{placed_order.items.get().image.name}" in html


def test_the_staff_order_page_shows_the_snapshot(client, staff_user, placed_order):
    client.force_login(staff_user)

    html = client.get(
        reverse("orders:manage_order_detail", kwargs={"pk": placed_order.pk})
    ).content.decode()

    assert f"/media/{placed_order.items.get().image.name}" in html


def test_an_order_keeps_its_picture_after_the_product_changes(
    client, placed_order, make_image, django_capture_on_commit_callbacks
):
    snapshot = placed_order.items.get().image.name
    product = Product.objects.get(pk=placed_order.items.get().product_id)
    with django_capture_on_commit_callbacks(execute=True):
        images.set_main_image(product, images.validate_image(make_image(900, 900)))

    client.force_login(placed_order.user)
    html = client.get(
        reverse("orders:detail", kwargs={"pk": placed_order.pk})
    ).content.decode()

    assert f"/media/{snapshot}" in html
    assert product.image_thumbnail.name not in html


def test_an_order_placed_before_images_shows_the_placeholder(client, cart, cart_item):
    order = place_order(cart, cart.user, dict(VALID_DATA))  # no product image
    client.force_login(order.user)

    html = client.get(
        reverse("orders:detail", kwargs={"pk": order.pk})
    ).content.decode()

    assert "images/placeholders/home-assistants.svg" in html
    assert "/media/" not in html


def test_the_cart_and_checkout_show_the_products_thumbnail(client, pictured_item):
    client.force_login(pictured_item.cart.user)
    thumbnail = Product.objects.get(pk=pictured_item.product_id).image_thumbnail.name

    assert f"/media/{thumbnail}" in client.get(reverse("orders:cart")).content.decode()
    assert (
        f"/media/{thumbnail}" in client.get(reverse("orders:checkout")).content.decode()
    )


def test_order_history_queries_do_not_grow_with_orders(client, customer, product):
    def history_queries():
        with CaptureQueriesContext(connection) as queries:
            client.get(reverse("orders:history"))
        return len(queries)

    def buy():
        cart = Cart.for_user(customer)
        cart.add(product)
        place_order(cart, customer, dict(VALID_DATA))

    client.force_login(customer)
    buy()
    one_order = history_queries()
    for _ in range(3):
        buy()

    assert history_queries() == one_order
