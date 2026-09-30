"""products/images.py — the validator, the storage pipeline, extras and snapshots.

The rules and their messages first, then the pipeline's ordering
guarantees (old files go only after commit; a failure removes the new
files and leaves the old image alone), then the exists-or-placeholder
rule, the extras, and order-line snapshots.
"""

import io
import random
import struct
import zlib
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from orders.models import Order, OrderItem

from . import images
from .models import Product, ProductImage

pytestmark = pytest.mark.django_db


def stored_files(media_root):
    """Every file under MEDIA_ROOT, as storage names."""
    if not media_root.exists():
        return set()
    return {
        path.relative_to(media_root).as_posix()
        for path in media_root.rglob("*")
        if path.is_file()
    }


def png_header(width, height):
    """A PNG that *claims* ``width`` × ``height`` — its header, and nothing to decode.

    The validator must refuse oversized images from the header alone,
    so tests never need to build a 48-megapixel image to prove it.
    """

    def chunk(kind, data):
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


def decode(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def rejection(upload):
    with pytest.raises(ValidationError) as caught:
        images.validate_image(upload)
    return caught.value.messages[0]


@pytest.fixture
def prepared(make_image):
    """A ready-to-store image: 800 × 1000 in, 800 × 1000 display, 600 × 750 thumb."""
    return images.validate_image(make_image(800, 1000))


@pytest.fixture
def product_with_image(product, prepared):
    images.set_main_image(product, prepared, "Seraphine on a shelf")
    return product


# --- The validator: what it accepts ------------------------------------------


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepts_each_format_and_stores_webp(make_image, fmt):
    result = images.validate_image(make_image(900, 1200, fmt))

    assert decode(result.display).format == "WEBP"
    assert decode(result.thumbnail).format == "WEBP"


def test_resizes_to_a_display_file_and_a_thumbnail(make_image):
    result = images.validate_image(make_image(1500, 2000))

    assert (result.width, result.height) == (900, 1200)
    assert decode(result.display).size == (900, 1200)
    assert decode(result.thumbnail).size == (600, 800)


def test_never_enlarges_a_small_image(make_image):
    result = images.validate_image(make_image(700, 800))

    assert decode(result.display).size == (700, 800)
    assert decode(result.thumbnail).size == images.thumbnail_size(700, 800)


def test_judges_the_type_by_content_not_the_name(make_image):
    png_named_jpg = make_image(800, 1000, "PNG", name="photo.jpg")

    assert images.validate_image(png_named_jpg).width == 800


def test_applies_the_exif_rotation(make_image):
    exif = Image.Exif()
    exif[images.EXIF_ORIENTATION] = 6  # "rotate 90° clockwise to view"

    result = images.validate_image(make_image(1000, 700, "JPEG", exif=exif))

    assert decode(result.display).size == (700, 1000)


def test_converts_cmyk_to_rgb(make_image):
    result = images.validate_image(make_image(800, 1000, "JPEG", mode="CMYK"))

    assert decode(result.display).mode == "RGB"


def test_keeps_transparency(make_image):
    result = images.validate_image(make_image(800, 1000, "PNG", mode="RGBA"))

    assert decode(result.display).mode == "RGBA"
    assert decode(result.thumbnail).mode == "RGBA"


def test_accepts_exactly_three_to_one(make_image):
    assert images.validate_image(make_image(1800, 600)).width == 1200


# --- The validator: what it refuses, and what it says -------------------------


def test_refuses_a_file_over_10_mb():
    upload = SimpleUploadedFile("huge.png", b"\0" * (12 * 1024 * 1024))

    message = rejection(upload)

    assert "“huge.png” is 12.0 MB" in message
    assert "at most 10 MB" in message


def test_refuses_something_that_is_not_an_image():
    upload = SimpleUploadedFile("notes.png", b"these are not pixels")

    message = rejection(upload)

    assert "“notes.png” isn't a JPEG, PNG or WebP image" in message
    assert "even though its name ends in .png" in message


def test_names_the_format_of_an_image_it_does_not_accept(make_image):
    message = rejection(make_image(800, 1000, "GIF", name="banner.gif"))

    assert "“banner.gif” is in GIF format" in message
    assert "Only JPEG, PNG and WebP" in message


def test_refuses_an_image_under_600_pixels_on_a_side(make_image):
    message = rejection(make_image(500, 900))

    assert "is 500 × 900 pixels" in message
    assert "at least 600 pixels on each side" in message


def test_reports_the_size_as_the_customer_will_see_it(make_image):
    """A sideways-tagged photo is described the right way up."""
    exif = Image.Exif()
    exif[images.EXIF_ORIENTATION] = 6

    message = rejection(make_image(900, 500, "JPEG", exif=exif))

    assert "is 500 × 900 pixels" in message


def test_refuses_more_than_40_megapixels_without_decoding():
    upload = SimpleUploadedFile("poster.png", png_header(8000, 6000))

    message = rejection(upload)

    assert "is 8000 × 6000 pixels (48.0 megapixels)" in message
    assert "limit is 40 megapixels" in message


def test_refuses_a_decompression_bomb_header():
    upload = SimpleUploadedFile("bomb.png", png_header(20000, 20000))

    message = rejection(upload)

    assert "far more than 40 megapixels" in message


@pytest.mark.parametrize(
    ("width", "height", "shape"),
    [(2000, 600, "wide as it is tall"), (600, 1900, "tall as it is wide")],
)
def test_refuses_an_aspect_beyond_three_to_one(make_image, width, height, shape):
    message = rejection(make_image(width, height))

    assert f"is {width} × {height} pixels" in message
    assert f"more than 3 times as {shape}" in message


def test_refuses_an_animation(make_image):
    second_frame = Image.new("RGB", (800, 1000), (255, 0, 0))

    message = rejection(
        make_image(800, 1000, "PNG", save_all=True, append_images=[second_frame])
    )

    assert "is an animated PNG with 2 frames" in message
    assert "Only still images" in message


def test_refuses_a_truncated_file():
    # Noise doesn't compress away, so the cut lands inside the pixel data.
    noise = random.Random(2026).randbytes(800 * 1000 * 3)
    noisy = Image.frombytes("RGB", (800, 1000), noise)
    buffer = io.BytesIO()
    noisy.save(buffer, "PNG")
    whole = buffer.getvalue()

    message = rejection(SimpleUploadedFile("cut.png", whole[: len(whole) // 2]))

    assert "“cut.png” looks like a PNG file, but it is damaged or incomplete" in message


# --- The pipeline: the main image ---------------------------------------------


def test_set_main_image_stores_two_webps_and_records_them(
    product, prepared, media_root
):
    images.set_main_image(product, prepared, "Seraphine on a shelf")

    product = Product.objects.get(pk=product.pk)
    assert product.image.name.startswith("products/")
    assert product.image.name.endswith(".webp")
    assert product.image_thumbnail.name.endswith("-thumb.webp")
    assert (product.image_width, product.image_height) == (800, 1000)
    assert product.image_alt == "Seraphine on a shelf"
    assert stored_files(media_root) == {
        product.image.name,
        product.image_thumbnail.name,
    }


def test_replacing_deletes_the_old_files_only_after_commit(
    product_with_image, make_image, media_root, django_capture_on_commit_callbacks
):
    old = {product_with_image.image.name, product_with_image.image_thumbnail.name}

    with django_capture_on_commit_callbacks() as callbacks:
        images.set_main_image(
            product_with_image, images.validate_image(make_image(900, 900))
        )
        # Not yet committed: both generations are on disk.
        assert old < stored_files(media_root)
    for callback in callbacks:
        callback()

    new = {product_with_image.image.name, product_with_image.image_thumbnail.name}
    assert new.isdisjoint(old)  # fresh random names bust caches
    assert stored_files(media_root) == new


def test_a_failed_save_removes_the_new_files_and_keeps_the_old_image(
    product_with_image, make_image, media_root, monkeypatch
):
    before = stored_files(media_root)
    old_name = product_with_image.image.name
    replacement = images.validate_image(make_image(900, 900))

    def explode(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(Product, "save", explode)
    with pytest.raises(RuntimeError):
        images.set_main_image(product_with_image, replacement)
    monkeypatch.undo()

    assert stored_files(media_root) == before
    assert product_with_image.image.name == old_name  # the instance is restored too
    assert Product.objects.get(pk=product_with_image.pk).image.name == old_name


def test_a_failed_second_write_removes_the_first(
    product, prepared, media_root, monkeypatch
):
    real_save = default_storage.save
    calls = []

    def fail_second(name, content, **kwargs):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_save(name, content, **kwargs)

    monkeypatch.setattr(default_storage, "save", fail_second)
    with pytest.raises(OSError):
        images.set_main_image(product, prepared)

    assert stored_files(media_root) == set()
    assert not Product.objects.get(pk=product.pk).image


def test_remove_main_image_clears_it_and_deletes_the_files(
    product_with_image, media_root, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert images.remove_main_image(product_with_image)

    product = Product.objects.get(pk=product_with_image.pk)
    assert not product.image
    assert product.image_width is None
    assert product.card_image.is_placeholder
    assert stored_files(media_root) == set()
    assert not images.remove_main_image(product)  # nothing left to remove


def test_deleting_a_product_deletes_all_its_files(
    product_with_image, prepared, media_root, django_capture_on_commit_callbacks
):
    images.add_extra_image(product_with_image, prepared)
    assert len(stored_files(media_root)) == 4

    with django_capture_on_commit_callbacks(execute=True):
        product_with_image.delete()

    assert stored_files(media_root) == set()


# --- Never load a missing file --------------------------------------------------


def test_pictures_use_the_stored_files(product_with_image):
    product = Product.objects.get(pk=product_with_image.pk)

    assert product.card_image.url == f"/media/{product.image_thumbnail.name}"
    assert (product.card_image.width, product.card_image.height) == (600, 750)
    assert product.display_image.url == f"/media/{product.image.name}"
    assert (product.display_image.width, product.display_image.height) == (800, 1000)
    assert product.card_image.alt == "Seraphine on a shelf"
    assert product.has_image


def test_a_product_without_an_image_gets_its_category_placeholder(product):
    picture = product.card_image

    assert picture.is_placeholder
    assert picture.url.endswith("images/placeholders/home-assistants.svg")
    assert picture.alt == product.name
    assert not product.has_image


def test_a_missing_file_falls_back_to_the_placeholder(product_with_image, media_root):
    (media_root / product_with_image.image_thumbnail.name).unlink()
    product = Product.objects.get(pk=product_with_image.pk)

    assert product.card_image.is_placeholder  # cards check the thumbnail
    assert not product.display_image.is_placeholder  # detail checks the display file
    assert not product.has_image


def test_a_name_storage_refuses_falls_back_to_the_placeholder(product):
    product.image = "../../etc/passwd"
    product.image_thumbnail = "../../etc/passwd"
    product.image_width = product.image_height = 800

    assert product.display_image.is_placeholder
    assert product.card_image.is_placeholder


def test_the_alt_text_falls_back_to_the_product_name(product, prepared):
    images.set_main_image(product, prepared)

    assert Product.objects.get(pk=product.pk).card_image.alt == product.name


# --- Extras ---------------------------------------------------------------------


def test_extras_never_touch_the_main_image(product_with_image, prepared):
    main = product_with_image.image.name

    images.add_extra_image(product_with_image, prepared)

    product = Product.objects.get(pk=product_with_image.pk)
    assert product.image.name == main
    assert product.extra_images.count() == 1


def test_an_extra_does_not_stand_in_for_a_missing_main_image(product, prepared):
    images.add_extra_image(product, prepared)

    assert Product.objects.get(pk=product.pk).card_image.is_placeholder


def test_extras_are_capped_at_eight(product, prepared, media_root):
    for _ in range(images.MAX_EXTRAS):
        images.add_extra_image(product, prepared)
    files_before = stored_files(media_root)

    with pytest.raises(ValidationError) as caught:
        images.add_extra_image(product, prepared)

    assert caught.value.messages[0] == (
        "Seraphine Home Hub already has 8 extra images, the most a product can "
        "have. Remove one before adding another."
    )
    assert stored_files(media_root) == files_before  # nothing written
    assert list(product.extra_images.values_list("sort_order", flat=True)) == list(
        range(8)
    )


def test_move_extra_reorders_and_stops_at_the_ends(product, prepared):
    first, second, third = (images.add_extra_image(product, prepared) for _ in range(3))

    assert images.move_extra(third, "up")
    assert list(product.extra_images.all()) == [first, third, second]

    assert images.move_extra(first, "down")
    assert list(product.extra_images.all()) == [third, first, second]

    assert not images.move_extra(third, "up")
    assert not images.move_extra(second, "down")


def test_move_extra_copes_with_gaps_left_by_removals(product, prepared):
    first, second, third = (images.add_extra_image(product, prepared) for _ in range(3))
    images.remove_extra_image(second)

    assert images.move_extra(third, "up")
    assert list(product.extra_images.all()) == [third, first]


def test_removing_an_extra_deletes_its_files(
    product, prepared, media_root, django_capture_on_commit_callbacks
):
    extra = images.add_extra_image(product, prepared)

    with django_capture_on_commit_callbacks(execute=True):
        images.remove_extra_image(extra)

    assert not ProductImage.objects.exists()
    assert stored_files(media_root) == set()


def test_the_gallery_puts_the_main_image_first(product_with_image, prepared):
    images.add_extra_image(product_with_image, prepared, "The back panel")
    images.add_extra_image(product_with_image, prepared)

    slides = Product.objects.get(pk=product_with_image.pk).gallery

    assert [slide.display.alt for slide in slides] == [
        "Seraphine on a shelf",
        "The back panel",
        "Seraphine Home Hub — image 3 of 3",
    ]


def test_the_gallery_leaves_out_an_extra_whose_file_is_missing(
    product_with_image, prepared, media_root
):
    extra = images.add_extra_image(product_with_image, prepared)
    (media_root / extra.image.name).unlink()

    slides = Product.objects.get(pk=product_with_image.pk).gallery

    assert len(slides) == 1


# --- Order snapshots ------------------------------------------------------------


@pytest.fixture
def order_line(customer, product_with_image):
    order = Order.objects.create(
        user=customer,
        total=Decimal("349.99"),
        email="casey@example.com",
        shipping_name="Casey",
        shipping_street="1 Road",
        shipping_city="Canyon",
        shipping_state="TX",
        shipping_zip="79015",
        billing_name="Casey",
        billing_street="1 Road",
        billing_city="Canyon",
        billing_state="TX",
        billing_zip="79015",
        card_last4="4242",
    )
    return OrderItem.objects.create(
        order=order,
        product=product_with_image,
        product_name=product_with_image.name,
        unit_price=product_with_image.price,
        quantity=1,
    )


def test_snapshot_copies_the_thumbnail_onto_the_line(order_line, media_root):
    assert images.snapshot_for_order(order_line.order) == 1

    item = OrderItem.objects.get(pk=order_line.pk)
    product = item.product
    assert item.image.name.startswith("orders/")
    assert item.image.name != product.image_thumbnail.name
    assert (media_root / item.image.name).read_bytes() == (
        media_root / product.image_thumbnail.name
    ).read_bytes()
    assert (item.image_width, item.image_height) == (600, 750)
    assert item.thumbnail.url == f"/media/{item.image.name}"


def test_a_snapshot_outlives_the_products_image(
    order_line, make_image, django_capture_on_commit_callbacks
):
    images.snapshot_for_order(order_line.order)
    snapshot = OrderItem.objects.get(pk=order_line.pk).image.name

    with django_capture_on_commit_callbacks(execute=True):
        images.set_main_image(
            order_line.product, images.validate_image(make_image(900, 900))
        )
        order_line.product.delete()

    item = OrderItem.objects.get(pk=order_line.pk)
    assert item.image.name == snapshot
    assert not item.thumbnail.is_placeholder


def test_a_line_without_a_product_image_gets_no_snapshot(order_line, media_root):
    images.remove_main_image(order_line.product)

    assert images.snapshot_for_order(order_line.order) == 0
    item = OrderItem.objects.get(pk=order_line.pk)
    assert item.thumbnail.is_placeholder
    assert item.thumbnail.url.endswith("home-assistants.svg")


def test_a_line_whose_product_was_deleted_shows_the_default_placeholder(order_line):
    order_line.product.delete()

    item = OrderItem.objects.get(pk=order_line.pk)
    assert item.thumbnail.url.endswith("images/placeholders/default.svg")


def test_snapshot_never_raises(order_line, monkeypatch):
    def broken_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(default_storage, "save", broken_save)

    assert images.snapshot_for_order(order_line.order) == 0
    assert not OrderItem.objects.get(pk=order_line.pk).image


def test_deleting_an_order_deletes_its_snapshots(
    order_line, media_root, django_capture_on_commit_callbacks
):
    images.snapshot_for_order(order_line.order)
    snapshot = OrderItem.objects.get(pk=order_line.pk).image.name

    with django_capture_on_commit_callbacks(execute=True):
        order_line.order.delete()

    assert snapshot not in stored_files(media_root)


def test_a_stray_file_is_not_mistaken_for_a_product_image(product):
    """Setting a field by hand is not enough — dimensions come from the pipeline."""
    default_storage.save("products/stray.webp", ContentFile(b"x"))
    product.image_thumbnail = "products/stray.webp"

    assert product.card_image.is_placeholder
