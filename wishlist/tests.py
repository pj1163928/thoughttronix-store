from http import HTTPStatus

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError
from django.urls import reverse

from .models import Wishlist, WishlistItem


@pytest.fixture
def wishlist(customer):
    return Wishlist.for_user(customer)


@pytest.fixture
def saved(wishlist, product):
    """Seraphine, on the customer's wishlist."""
    return wishlist.add(product)


@pytest.fixture
def other_customer(db):
    return get_user_model().objects.create_user(username="other", password="x")


def add_url(product):
    return reverse("wishlist:add", kwargs={"pk": product.pk})


def remove_url(product):
    return reverse("wishlist:remove", kwargs={"pk": product.pk})


# --- Model behavior ---------------------------------------------------------


def test_wishlist_str(wishlist):
    assert str(wishlist) == "Wishlist for customer"


def test_for_user_creates_the_wishlist_once(customer):
    first = Wishlist.for_user(customer)
    second = Wishlist.for_user(customer)

    assert first == second
    assert Wishlist.objects.count() == 1


def test_one_wishlist_per_user(wishlist, customer):
    with pytest.raises(IntegrityError):
        Wishlist.objects.create(user=customer)


def test_add_saves_a_product(wishlist, product):
    item = wishlist.add(product)

    assert str(item) == "Seraphine Home Hub"
    assert list(wishlist.items.all()) == [item]


def test_adding_twice_keeps_one_row(wishlist, product):
    wishlist.add(product)
    wishlist.add(product)

    assert wishlist.items.count() == 1


def test_wishlist_product_pair_is_unique(saved):
    with pytest.raises(IntegrityError):
        WishlistItem.objects.create(wishlist=saved.wishlist, product=saved.product)


def test_remove_drops_the_product(wishlist, saved, product):
    wishlist.remove(product)

    assert not wishlist.items.exists()


def test_removing_an_unsaved_product_changes_nothing(wishlist, product):
    wishlist.remove(product)

    assert not wishlist.items.exists()


def test_unavailable_products_can_be_saved(wishlist, unavailable_product):
    wishlist.add(unavailable_product)

    assert wishlist.items.get().product == unavailable_product


def test_newest_save_comes_first(wishlist, product, featured_product):
    wishlist.add(product)
    newer = wishlist.add(featured_product)

    assert wishlist.items.first() == newer


def test_of_is_scoped_to_the_owner(saved, customer, other_customer, featured_product):
    Wishlist.for_user(other_customer).add(featured_product)

    assert list(WishlistItem.objects.of(customer)) == [saved]


def test_of_anonymous_is_empty(saved):
    assert not WishlistItem.objects.of(AnonymousUser()).exists()


def test_holds(saved, customer, product, featured_product):
    mine = WishlistItem.objects.of(customer)

    assert mine.holds(product)
    assert not mine.holds(featured_product)


def test_deleting_a_product_removes_it_from_wishlists(saved, product):
    product.delete()

    assert not WishlistItem.objects.exists()


# --- Privacy ----------------------------------------------------------------


def test_wishlists_are_not_in_the_admin():
    """Private means private: not even the superuser browses them."""
    assert Wishlist not in admin.site._registry
    assert WishlistItem not in admin.site._registry


def test_customers_see_only_their_own_wishlist(client, saved, other_customer):
    client.force_login(other_customer)

    response = client.get(reverse("wishlist:list"))

    assert saved.product.name not in response.content.decode()
    assert "Your wishlist is empty" in response.content.decode()


def test_product_page_shows_only_the_viewers_own_state(
    client, saved, other_customer, product
):
    client.force_login(other_customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert add_url(product) in page
    assert "On your wishlist" not in page


def test_removing_another_customers_line_404s(client, saved, other_customer):
    client.force_login(other_customer)

    response = client.post(reverse("wishlist:remove_item", kwargs={"pk": saved.pk}))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert WishlistItem.objects.filter(pk=saved.pk).exists()


def test_another_customers_remove_leaves_mine_alone(
    client, saved, other_customer, product
):
    client.force_login(other_customer)

    client.post(remove_url(product))

    assert WishlistItem.objects.filter(pk=saved.pk).exists()


# --- The wishlist page -------------------------------------------------------


def test_wishlist_page_requires_login(client, db):
    response = client.get(reverse("wishlist:list"))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url


def test_empty_wishlist_shows_empty_state(client, customer):
    client.force_login(customer)

    response = client.get(reverse("wishlist:list"))

    page = response.content.decode()
    assert "Your wishlist is empty" in page
    assert reverse("products:catalog") in page


def test_visiting_the_page_creates_no_wishlist(client, customer):
    client.force_login(customer)

    client.get(reverse("wishlist:list"))

    assert not Wishlist.objects.exists()


def test_wishlist_page_lists_saved_products(client, customer, saved):
    client.force_login(customer)

    response = client.get(reverse("wishlist:list"))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "Seraphine Home Hub" in page
    assert "349.99" in page
    assert reverse("wishlist:remove_item", kwargs={"pk": saved.pk}) in page
    assert reverse("orders:add", kwargs={"pk": saved.product.pk}) in page


def test_wishlist_page_greys_out_unavailable_products(
    client, customer, wishlist, unavailable_product
):
    wishlist.add(unavailable_product)
    client.force_login(customer)

    response = client.get(reverse("wishlist:list"))

    page = response.content.decode()
    assert "EchoPatch" in page
    assert "Unavailable" in page
    assert reverse("orders:add", kwargs={"pk": unavailable_product.pk}) not in page


def test_navbar_links_to_the_wishlist(client, customer):
    client.force_login(customer)

    response = client.get(reverse("products:catalog"))

    assert reverse("wishlist:list") in response.content.decode()


def test_adding_to_cart_keeps_the_wishlist_entry(client, customer, saved, product):
    client.force_login(customer)

    client.post(reverse("orders:add", kwargs={"pk": product.pk}))

    assert WishlistItem.objects.filter(pk=saved.pk).exists()


# --- Remove from the wishlist page (HTMX) -----------------------------------


def test_remove_item_returns_the_list_partial(
    client, customer, saved, wishlist, featured_product
):
    wishlist.add(featured_product)
    client.force_login(customer)

    response = client.post(reverse("wishlist:remove_item", kwargs={"pk": saved.pk}))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert "Seraphine Home Hub" not in page
    assert "Cogitator Crown" in page
    assert not WishlistItem.objects.filter(pk=saved.pk).exists()


def test_removing_the_last_item_shows_the_empty_state(client, customer, saved):
    client.force_login(customer)

    response = client.post(reverse("wishlist:remove_item", kwargs={"pk": saved.pk}))

    assert "Your wishlist is empty" in response.content.decode()


# --- The product page button -------------------------------------------------


def test_product_page_prompts_anonymous_users_to_sign_in(client, product):
    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert "Add to wishlist" in page
    assert add_url(product) not in page
    assert f"{reverse('accounts:login')}?next=" in page


def test_product_page_offers_to_add_an_unsaved_product(client, customer, product):
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert "Add to wishlist" in page
    assert add_url(product) in page
    assert 'id="wishlist-button"' in page


def test_product_page_shows_a_saved_product_as_saved(client, customer, saved, product):
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert "On your wishlist" in page
    assert remove_url(product) in page
    assert add_url(product) not in page


def test_unavailable_product_page_still_offers_the_wishlist(
    client, customer, unavailable_product
):
    client.force_login(customer)

    response = client.get(unavailable_product.get_absolute_url())

    assert add_url(unavailable_product) in response.content.decode()


# --- Add and remove (HTMX) ---------------------------------------------------


def test_anonymous_add_redirects_to_login(client, product):
    response = client.post(add_url(product))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url
    assert not WishlistItem.objects.exists()


def test_add_is_post_only(client, customer, product):
    client.force_login(customer)

    response = client.get(add_url(product))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert not WishlistItem.objects.exists()


def test_add_returns_the_saved_button(client, customer, product):
    client.force_login(customer)

    response = client.post(add_url(product))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert "On your wishlist" in page
    assert remove_url(product) in page
    assert customer.wishlist.items.get().product == product


def test_add_twice_stays_saved(client, customer, product):
    """A double click or a stale tab never flips the product back off."""
    client.force_login(customer)
    client.post(add_url(product))

    response = client.post(add_url(product))

    assert "On your wishlist" in response.content.decode()
    assert customer.wishlist.items.count() == 1


def test_add_an_unavailable_product(client, customer, unavailable_product):
    client.force_login(customer)

    response = client.post(add_url(unavailable_product))

    assert response.status_code == HTTPStatus.OK
    assert customer.wishlist.items.get().product == unavailable_product


def test_add_a_missing_product_404s(client, customer):
    client.force_login(customer)

    response = client.post(reverse("wishlist:add", kwargs={"pk": 999}))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_remove_returns_the_unsaved_button(client, customer, saved, product):
    client.force_login(customer)

    response = client.post(remove_url(product))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert "Add to wishlist" in page
    assert add_url(product) in page
    assert not WishlistItem.objects.exists()


def test_remove_twice_stays_removed(client, customer, product):
    client.force_login(customer)

    response = client.post(remove_url(product))

    assert response.status_code == HTTPStatus.OK
    assert "Add to wishlist" in response.content.decode()
    assert not WishlistItem.objects.exists()
