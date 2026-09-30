"""The Images page, the storefront's pictures, the admin, and media serving."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from . import images
from .models import Product

pytestmark = pytest.mark.django_db


@pytest.fixture
def prepared(make_image):
    return images.validate_image(make_image(800, 1000))


@pytest.fixture
def product_with_image(product, prepared):
    images.set_main_image(product, prepared, "Seraphine on a shelf")
    return Product.objects.get(pk=product.pk)


@pytest.fixture
def extra(product_with_image, prepared):
    return images.add_extra_image(product_with_image, prepared, "The back panel")


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


def images_url(product):
    return reverse("products:manage_product_images", kwargs={"pk": product.pk})


def page_urls(product, extra):
    """The Images-page URLs that answer GET."""
    return [
        images_url(product),
        reverse("products:manage_product_image_remove", kwargs={"pk": product.pk}),
        reverse(
            "products:manage_product_extra_remove",
            kwargs={"pk": product.pk, "extra_pk": extra.pk},
        ),
    ]


def action_urls(product, extra):
    """The Images-page URLs that only answer POST."""
    return [
        reverse("products:manage_product_image_upload", kwargs={"pk": product.pk}),
        reverse("products:manage_product_extra_add", kwargs={"pk": product.pk}),
        reverse(
            "products:manage_product_extra_move",
            kwargs={"pk": product.pk, "extra_pk": extra.pk},
        ),
    ]


# --- Access control ----------------------------------------------------------


def test_anonymous_users_are_sent_to_login(client, product_with_image, extra):
    for url in page_urls(product_with_image, extra):
        response = client.get(url)
        assert response.status_code == HTTPStatus.FOUND, url
        assert reverse("accounts:login") in response.url
    for url in action_urls(product_with_image, extra):
        assert client.post(url).status_code == HTTPStatus.FOUND, url


def test_customers_get_403(client, customer, product_with_image, extra):
    client.force_login(customer)

    for url in page_urls(product_with_image, extra):
        assert client.get(url).status_code == HTTPStatus.FORBIDDEN, url
    for url in action_urls(product_with_image, extra):
        assert client.post(url).status_code == HTTPStatus.FORBIDDEN, url
    assert Product.objects.get().image  # nothing was touched


def test_staff_get_200(staff_client, product_with_image, extra):
    for url in page_urls(product_with_image, extra):
        response = staff_client.get(url)

        assert response.status_code == HTTPStatus.OK, url
        assert "{#" not in response.content.decode(), url


def test_an_extra_is_only_reachable_through_its_own_product(
    staff_client, extra, featured_product
):
    url = reverse(
        "products:manage_product_extra_remove",
        kwargs={"pk": featured_product.pk, "extra_pk": extra.pk},
    )

    assert staff_client.get(url).status_code == HTTPStatus.NOT_FOUND
    assert staff_client.post(url).status_code == HTTPStatus.NOT_FOUND


# --- Uploading ------------------------------------------------------------------


def test_staff_can_upload_a_main_image(staff_client, product, make_image):
    response = staff_client.post(
        reverse("products:manage_product_image_upload", kwargs={"pk": product.pk}),
        {"main-image": make_image(900, 1200), "main-alt_text": "Seraphine, lit"},
        follow=True,
    )

    product = Product.objects.get(pk=product.pk)
    assert product.has_image
    assert product.image_alt == "Seraphine, lit"
    assert "Main image added" in response.content.decode()
    assert response.redirect_chain[-1][0] == images_url(product)


def test_a_rejected_upload_explains_why_and_changes_nothing(
    staff_client, product_with_image, make_image
):
    old = product_with_image.image.name

    response = staff_client.post(
        reverse(
            "products:manage_product_image_upload", kwargs={"pk": product_with_image.pk}
        ),
        {"main-image": make_image(400, 500, name="tiny.png")},
    )

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "“tiny.png” is 400 × 500 pixels" in page
    assert "at least 600 pixels on each side" in page
    assert Product.objects.get(pk=product_with_image.pk).image.name == old


def test_replacing_deletes_the_old_files(
    staff_client,
    product_with_image,
    make_image,
    media_root,
    django_capture_on_commit_callbacks,
):
    old = media_root / product_with_image.image.name

    with django_capture_on_commit_callbacks(execute=True):
        response = staff_client.post(
            reverse(
                "products:manage_product_image_upload",
                kwargs={"pk": product_with_image.pk},
            ),
            {"main-image": make_image(900, 900)},
            follow=True,
        )

    assert "Main image replaced" in response.content.decode()
    assert not old.exists()


def test_a_storage_failure_is_reported_not_a_500(
    staff_client, product, make_image, monkeypatch
):
    def full_disk(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(images, "_store", full_disk)

    response = staff_client.post(
        reverse("products:manage_product_image_upload", kwargs={"pk": product.pk}),
        {"main-image": make_image()},
        follow=True,
    )

    assert "be saved, so nothing was changed" in response.content.decode()
    assert not Product.objects.get(pk=product.pk).image


def test_staff_can_remove_the_main_image_after_confirming(
    staff_client, product_with_image
):
    url = reverse(
        "products:manage_product_image_remove", kwargs={"pk": product_with_image.pk}
    )

    confirm = staff_client.get(url).content.decode()
    assert "Remove the main image" in confirm
    assert "Home Assistants placeholder" in confirm

    response = staff_client.post(url, follow=True)

    assert "now shows the placeholder" in response.content.decode()
    assert not Product.objects.get(pk=product_with_image.pk).image


def test_removing_a_missing_main_image_just_says_so(staff_client, product):
    response = staff_client.get(
        reverse("products:manage_product_image_remove", kwargs={"pk": product.pk}),
        follow=True,
    )

    assert "has no main image" in response.content.decode()


# --- Extras on the Images page ----------------------------------------------------


def test_staff_can_add_an_extra(staff_client, product_with_image, make_image):
    response = staff_client.post(
        reverse(
            "products:manage_product_extra_add", kwargs={"pk": product_with_image.pk}
        ),
        {"extra-image": make_image(), "extra-alt_text": "Side view"},
        follow=True,
    )

    assert "Extra image added" in response.content.decode()
    assert product_with_image.extra_images.get().alt_text == "Side view"


def test_the_page_replaces_the_add_form_at_the_limit(staff_client, product, prepared):
    for _ in range(images.MAX_EXTRAS):
        images.add_extra_image(product, prepared)

    page = staff_client.get(images_url(product)).content.decode()

    assert "8 / 8" in page
    assert "already has 8 extra images" in page
    assert "Add extra image" not in page


def test_a_ninth_extra_is_refused_with_the_limit_message(
    staff_client, product, prepared, make_image
):
    for _ in range(images.MAX_EXTRAS):
        images.add_extra_image(product, prepared)

    response = staff_client.post(
        reverse("products:manage_product_extra_add", kwargs={"pk": product.pk}),
        {"extra-image": make_image()},
    )

    assert "already has 8 extra images" in response.content.decode()
    assert product.extra_images.count() == images.MAX_EXTRAS


def test_staff_can_reorder_extras(staff_client, product, prepared):
    first = images.add_extra_image(product, prepared)
    second = images.add_extra_image(product, prepared)

    staff_client.post(
        reverse(
            "products:manage_product_extra_move",
            kwargs={"pk": product.pk, "extra_pk": second.pk},
        ),
        {"direction": "up"},
    )

    assert list(product.extra_images.all()) == [second, first]


def test_a_nonsense_direction_moves_nothing(staff_client, product, prepared):
    first = images.add_extra_image(product, prepared)
    second = images.add_extra_image(product, prepared)

    staff_client.post(
        reverse(
            "products:manage_product_extra_move",
            kwargs={"pk": product.pk, "extra_pk": second.pk},
        ),
        {"direction": "sideways"},
    )

    assert list(product.extra_images.all()) == [first, second]


def test_staff_can_remove_an_extra_after_confirming(staff_client, extra):
    url = reverse(
        "products:manage_product_extra_remove",
        kwargs={"pk": extra.product_id, "extra_pk": extra.pk},
    )

    assert "Remove this extra image" in staff_client.get(url).content.decode()
    staff_client.post(url)

    assert not extra.product.extra_images.exists()
    assert Product.objects.get(pk=extra.product_id).image  # main untouched


# --- The rest of the back office ----------------------------------------------------


def test_creating_a_product_leads_to_its_images_page(staff_client, category):
    response = staff_client.post(
        reverse("products:manage_product_create"),
        {
            "name": "Thought Lamp",
            "slug": "thought-lamp",
            "price": "49.00",
            "category": str(category.pk),
        },
    )

    assert response.url == images_url(Product.objects.get(slug="thought-lamp"))


def test_the_product_list_shows_thumbnails_and_no_image_badges(
    staff_client, product_with_image, featured_product
):
    page = staff_client.get(reverse("products:manage_products")).content.decode()

    assert f"/media/{product_with_image.image_thumbnail.name}" in page
    assert page.count("No image") == 1


# --- The storefront -------------------------------------------------------------------


def test_catalog_cards_use_the_thumbnail_lazily_with_dimensions(
    client, product_with_image
):
    page = client.get(reverse("products:catalog")).content.decode()

    assert f'src="/media/{product_with_image.image_thumbnail.name}"' in page
    assert 'width="600" height="750"' in page
    assert 'loading="lazy"' in page
    assert 'decoding="async"' in page
    assert "aspect-[4/5]" in page


def test_catalog_shows_the_placeholder_when_the_file_is_missing(
    client, product_with_image, media_root
):
    (media_root / product_with_image.image_thumbnail.name).unlink()

    page = client.get(reverse("products:catalog")).content.decode()

    assert product_with_image.image_thumbnail.name not in page
    assert "images/placeholders/home-assistants.svg" in page


def test_detail_shows_the_full_image_eagerly_without_a_carousel(
    client, product_with_image
):
    page = client.get(product_with_image.get_absolute_url()).content.decode()

    tag = page[page.index(f"/media/{product_with_image.image.name}") :]
    tag = tag[: tag.index(">")]
    assert "loading=" not in tag  # above the fold: not lazy
    assert "carousel" not in page


def test_detail_shows_a_carousel_when_there_are_extras(client, extra):
    page = client.get(extra.product.get_absolute_url()).content.decode()

    assert 'class="carousel' in page
    assert 'href="#image-1"' in page
    assert 'href="#image-2"' in page
    assert f"/media/{extra.image.name}" in page
    assert 'alt="The back panel"' in page


def test_detail_without_an_image_shows_the_placeholder(client, product):
    page = client.get(product.get_absolute_url()).content.decode()

    assert "images/placeholders/home-assistants.svg" in page
    assert "/media/" not in page


# --- The Django admin ------------------------------------------------------------------


@pytest.fixture
def admin_client(client, db):
    admin = get_user_model().objects.create_superuser("root", password="root12345")
    client.force_login(admin)
    return client


def test_the_admin_shows_images_read_only(admin_client, extra):
    page = admin_client.get(
        reverse("admin:products_product_change", args=[extra.product_id])
    ).content.decode()

    assert 'type="file"' not in page
    assert "Manage images in the back office" in page
    assert images_url(extra.product) in page
    assert f"/media/{extra.thumbnail.name}" in page


def test_the_admin_add_form_still_works(admin_client):
    page = admin_client.get(reverse("admin:products_product_add")).content.decode()

    assert 'type="file"' not in page
    assert "Save the product first" in page


# --- Media serving -------------------------------------------------------------------


def test_media_is_served_regardless_of_debug(client, product_with_image, settings):
    settings.DEBUG = False

    response = client.get(f"/media/{product_with_image.image.name}")

    assert response.status_code == HTTPStatus.OK
    assert b"".join(response.streaming_content)[:4] == b"RIFF"
