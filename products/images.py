"""Product images — the codebase's third deliberate deep module.

Everything that turns an uploaded file into a picture on a page lives
here: the one validator every upload path shares, the resize-and-store
pipeline, the extras' ordering, the order-line snapshot, and the
exists-or-placeholder rule that keeps a missing file from ever reaching
an ``<img>`` tag. Forms call ``validate_image``; views, ``place_order``
and the seed call the rest. Nothing else writes or deletes image files.

The pipeline's order is the design:

1. validate and resize in memory — nothing touches storage until the
   upload has passed every rule;
2. write the new files under fresh random names;
3. save the row, in a transaction;
4. delete the old files, but only once that transaction commits.

A failure at step 2 or 3 removes the new files and leaves the old image
exactly as it was, so a failed replace never costs the product the image
it already had, and the database never points at a file that isn't there.

Each stored image is two WebP files: a *display* file (longest side
``DISPLAY_LONGEST_SIDE``) for the product page and a *thumbnail*
(``THUMBNAIL_WIDTH`` wide) for cards and order lines. The upload itself
is never kept.

This module deliberately imports no models, so models can import it;
it works on the instances it is handed.
"""

from __future__ import annotations

import io
import logging
import os
import uuid
import warnings
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, BinaryIO, Literal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Max
from django.templatetags.static import static
from PIL import Image, ImageOps, UnidentifiedImageError

if TYPE_CHECKING:
    from django.db.models.fields.files import FieldFile

    from orders.models import Order

    from .models import Product, ProductImage

logger = logging.getLogger(__name__)

# The rules, in the units the messages use.
MAX_FILE_MB = 10
MIN_SIDE = 600
MAX_MEGAPIXELS = 40
MAX_ASPECT = 3
MAX_EXTRAS = 8

# What gets stored.
DISPLAY_LONGEST_SIDE = 1200
THUMBNAIL_WIDTH = 600
WEBP_QUALITY = 82
PRODUCT_FOLDER = "products"
ORDER_FOLDER = "orders"

# Every placeholder SVG in assets/images/placeholders/ is drawn at 4:3.
PLACEHOLDER_SIZE = (400, 300)

# Pillow's format name -> the name an employee knows it by. MPO is the
# multi-picture JPEG some phone cameras write; it is a JPEG to everyone
# but Pillow, and its extra frames are depth data, not animation.
ACCEPTED_FORMATS = {"JPEG": "JPEG", "MPO": "JPEG", "PNG": "PNG", "WEBP": "WebP"}

# EXIF orientations that turn the picture on its side.
SIDEWAYS_ORIENTATIONS = {5, 6, 7, 8}
EXIF_ORIENTATION = 0x0112


# --- What templates receive -------------------------------------------------


@dataclass(frozen=True)
class Picture:
    """Everything an ``<img>`` tag needs, already resolved.

    Templates never read an image field directly. They receive a
    ``Picture`` whose ``url`` is either a media file that exists in
    storage right now or a static placeholder — never a guess.
    """

    url: str
    width: int
    height: int
    alt: str
    is_placeholder: bool = False

    @classmethod
    def placeholder(cls, static_path: str, alt: str) -> Picture:
        """A category placeholder illustration, served as a static file."""
        width, height = PLACEHOLDER_SIZE
        return cls(static(static_path), width, height, alt, is_placeholder=True)


@dataclass(frozen=True)
class Slide:
    """One image in the product page's gallery: the large view and its thumbnail."""

    display: Picture
    thumbnail: Picture


@dataclass(frozen=True)
class PreparedImage:
    """An upload that passed every rule, resized and encoded, not yet stored.

    ``width`` and ``height`` are the display file's; the thumbnail's
    follow from them via ``thumbnail_size``.
    """

    display: bytes
    thumbnail: bytes
    width: int
    height: int


def thumbnail_size(width: int | None, height: int | None) -> tuple[int, int]:
    """The thumbnail's dimensions for a display file of ``width`` × ``height``.

    ``THUMBNAIL_WIDTH`` wide, never enlarged. The pipeline sizes the
    file with this and templates size the tag with it, so the two cannot
    disagree. Unknown dimensions give ``(0, 0)``.
    """
    if not width or not height:
        return (0, 0)
    target = min(THUMBNAIL_WIDTH, width)
    return (target, max(1, round(height * target / width)))


def stored_url(file: FieldFile | None) -> str | None:
    """The file's URL if the field is set *and* the file is in storage, else ``None``.

    This is the "never load a missing file" rule. A storage error is
    treated as missing: a placeholder is always better than a broken
    image.
    """
    if not file:
        return None
    try:
        if file.storage.exists(file.name):
            return file.url
    except Exception:
        logger.warning("Could not check stored image %r", file.name, exc_info=True)
    return None


def stored_picture(
    file: FieldFile | None, width: int | None, height: int | None, alt: str
) -> Picture | None:
    """A ``Picture`` of a stored file, or ``None`` if it is unset or missing."""
    url = stored_url(file)
    if url is None or not width or not height:
        return None
    return Picture(url, width, height, alt)


# --- Validation ---------------------------------------------------------------


def validate_image(upload: BinaryIO) -> PreparedImage:
    """Check an upload against every rule, then resize it — all in memory.

    The single validator for every way an image enters the store: the
    back office's forms and the seed. Rules, in the order they are
    checked (cheapest first, and the pixel count before anything is
    decoded, so a decompression bomb is refused unopened):

    1. at most ``MAX_FILE_MB`` megabytes;
    2. a real JPEG, PNG or WebP, judged by its contents, not its name;
    3. at most ``MAX_MEGAPIXELS`` megapixels;
    4. at least ``MIN_SIDE`` pixels on each side;
    5. no more than ``MAX_ASPECT`` times as long as it is wide, either way;
    6. a still image, not an animation;
    7. decodes cleanly from start to finish.

    Some things are fixed rather than refused: the EXIF rotation is
    applied, CMYK becomes RGB, and transparency is kept.

    Raises ``ValidationError`` with one plain-language sentence that
    names the file and the actual values found. Returns the display and
    thumbnail WebPs, ready for storage.
    """
    label = _label(upload)

    size = _size_in_bytes(upload)
    if size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(
            f"{label} is {size / 1024 / 1024:.1f} MB. Images can be at most "
            f"{MAX_FILE_MB} MB — export it at a smaller size, or as a JPEG, "
            "and try again.",
            code="file_too_large",
        )

    image = _open(upload, label)
    kind = ACCEPTED_FORMATS[image.format]
    width, height = image.size
    if _orientation(image) in SIDEWAYS_ORIENTATIONS:
        width, height = height, width

    megapixels = width * height / 1_000_000
    if megapixels > MAX_MEGAPIXELS:
        raise ValidationError(
            f"{label} is {width} × {height} pixels ({megapixels:.1f} megapixels). "
            f"The limit is {MAX_MEGAPIXELS} megapixels — resize it to about "
            "4000 pixels on the long side and try again.",
            code="too_many_pixels",
        )
    if min(width, height) < MIN_SIDE:
        raise ValidationError(
            f"{label} is {width} × {height} pixels. Images must be at least "
            f"{MIN_SIDE} pixels on each side, or they look blurry on the "
            "product page — use a larger version of the photo.",
            code="too_small",
        )
    if max(width, height) > MAX_ASPECT * min(width, height):
        shape = "wide as it is tall" if width > height else "tall as it is wide"
        raise ValidationError(
            f"{label} is {width} × {height} pixels — more than {MAX_ASPECT} "
            f"times as {shape}. Crop it closer to the product and try again.",
            code="bad_aspect",
        )
    frames = getattr(image, "n_frames", 1)
    if image.format != "MPO" and frames > 1:
        raise ValidationError(
            f"{label} is an animated {kind} with {frames} frames. Only still "
            "images can be used — save a single frame and try again.",
            code="animated",
        )

    try:
        image.load()
        return _prepare(image)
    except Exception as error:
        raise ValidationError(
            f"{label} looks like a {kind} file, but it is damaged or incomplete "
            "and can't be read. Try exporting or downloading it again.",
            code="unreadable",
        ) from error


def _label(upload: BinaryIO) -> str:
    """How messages name the file: its own name in quotes."""
    name = os.path.basename(getattr(upload, "name", "") or "")
    return f"“{name}”" if name else "This file"


def _size_in_bytes(upload: BinaryIO) -> int:
    size = getattr(upload, "size", None)
    if size is None:
        upload.seek(0, os.SEEK_END)
        size = upload.tell()
    upload.seek(0)
    return size


def _open(upload: BinaryIO, label: str) -> Image.Image:
    """Identify the file by its contents; refuse anything but the accepted three.

    Opening reads only the header. Pillow's own decompression-bomb guard
    (its threshold is far above ours) is turned from a warning into a
    refusal, so an absurd header cannot slip past.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return Image.open(upload, formats=["JPEG", "PNG", "WEBP"])
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError(
            f"{label} has far more than {MAX_MEGAPIXELS} megapixels — too large "
            "to process safely. Resize it to about 4000 pixels on the long side "
            "and try again.",
            code="too_many_pixels",
        ) from error
    except UnidentifiedImageError as error:
        raise ValidationError(_wrong_type(upload, label), code="wrong_type") from error
    except Exception as error:
        raise ValidationError(
            f"{label} is damaged and can't be read. Try exporting or "
            "downloading it again.",
            code="unreadable",
        ) from error


def _orientation(image: Image.Image) -> int | None:
    """The EXIF orientation, read from the header alone.

    For a PNG, ``getexif()`` decodes every pixel looking for a late
    eXIf chunk — exactly what must not happen before the size checks —
    so only EXIF found ahead of the pixel data is consulted.
    """
    try:
        if image.format != "PNG":
            return image.getexif().get(EXIF_ORIENTATION)
        raw = image.info.get("exif")
        if not raw:
            return None
        exif = Image.Exif()
        exif.load(raw)
        return exif.get(EXIF_ORIENTATION)
    except Exception:
        return None  # unreadable EXIF: judge the pixels as stored


def _wrong_type(upload: BinaryIO, label: str) -> str:
    """Say what the file actually is, when Pillow can tell."""
    upload.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            found = Image.open(upload).format
    except Exception:
        found = None
    finally:
        upload.seek(0)
    if found:
        return (
            f"{label} is in {found} format. Only JPEG, PNG and WebP images can "
            "be used — save it in one of those formats and try again."
        )
    extension = os.path.splitext(getattr(upload, "name", "") or "")[1].lower()
    named = f", even though its name ends in {extension}" if extension else ""
    return (
        f"{label} isn't a JPEG, PNG or WebP image{named}. Choose a photo "
        "saved in one of those formats."
    )


def _prepare(image: Image.Image) -> PreparedImage:
    """Rotate upright, normalise the colours, and encode both WebPs."""
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in {"RGBA", "LA", "PA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    image = image.convert("RGBA" if has_alpha else "RGB")

    display = image.copy()
    display.thumbnail(
        (DISPLAY_LONGEST_SIDE, DISPLAY_LONGEST_SIDE), Image.Resampling.LANCZOS
    )
    target = thumbnail_size(*display.size)
    thumbnail = (
        display
        if target == display.size
        else display.resize(target, Image.Resampling.LANCZOS)
    )
    return PreparedImage(
        display=_webp(display),
        thumbnail=_webp(thumbnail),
        width=display.width,
        height=display.height,
    )


def _webp(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=WEBP_QUALITY, method=4)
    return buffer.getvalue()


# --- Storage ---------------------------------------------------------------------


def _store(image: PreparedImage, folder: str) -> tuple[str, str]:
    """Write both files under one fresh random name; return their storage names.

    Random names bust caches — a replaced image never reuses its old
    URL — and old and new files can never collide mid-replace.
    """
    token = uuid.uuid4().hex
    display = default_storage.save(f"{folder}/{token}.webp", ContentFile(image.display))
    try:
        thumbnail = default_storage.save(
            f"{folder}/{token}-thumb.webp", ContentFile(image.thumbnail)
        )
    except Exception:
        _delete_now([display])
        raise
    return display, thumbnail


def _delete_now(names: list[str]) -> None:
    for name in names:
        try:
            default_storage.delete(name)
        except Exception:
            logger.warning("Could not delete stored image %r", name, exc_info=True)


def delete_files_on_commit(*names: str) -> None:
    """Delete stored files once the current transaction commits.

    Outside a transaction that is immediately. If the transaction rolls
    back, the files stay — the rows that point at them stayed too. Model
    deletion calls this (via ``post_delete``), so deleting a product, an
    extra or an order takes its files with it.
    """
    names = [name for name in names if name]
    if names:
        transaction.on_commit(partial(_delete_now, names))


# --- The main image ----------------------------------------------------------------

MAIN_IMAGE_FIELDS = [
    "image",
    "image_thumbnail",
    "image_width",
    "image_height",
    "image_alt",
]


def set_main_image(product: Product, image: PreparedImage, alt_text: str = "") -> None:
    """Make ``image`` the product's main image, replacing any it had.

    Writes the new files, saves the row, and deletes the old files only
    after the save commits. If writing or saving fails, the new files
    are removed, ``product`` is put back as it was, and the exception
    propagates — the old image is untouched on disk and in the database.
    Concurrent replacements: the last one to save wins.
    """
    before = {field: getattr(product, field) for field in MAIN_IMAGE_FIELDS}
    old_files = [product.image.name, product.image_thumbnail.name]
    display, thumbnail = _store(image, PRODUCT_FOLDER)
    try:
        with transaction.atomic():
            product.image = display
            product.image_thumbnail = thumbnail
            product.image_width = image.width
            product.image_height = image.height
            product.image_alt = alt_text
            product.save(update_fields=MAIN_IMAGE_FIELDS)
    except Exception:
        for field, value in before.items():
            setattr(product, field, value)
        _delete_now([display, thumbnail])
        raise
    _forget_pictures(product)
    delete_files_on_commit(*old_files)


def remove_main_image(product: Product) -> bool:
    """Clear the product's main image; the store falls back to its placeholder.

    Extras are unaffected — they never stand in for the main image.
    Returns ``False`` if there was nothing to remove.
    """
    if not product.image and not product.image_thumbnail:
        return False
    old_files = [product.image.name, product.image_thumbnail.name]
    product.image = ""
    product.image_thumbnail = ""
    product.image_width = None
    product.image_height = None
    product.image_alt = ""
    product.save(update_fields=MAIN_IMAGE_FIELDS)
    _forget_pictures(product)
    delete_files_on_commit(*old_files)
    return True


def _forget_pictures(product: Product) -> None:
    """Drop the instance's cached ``Picture``s so they reflect the new image."""
    for name in ("card_image", "display_image", "gallery"):
        product.__dict__.pop(name, None)


# --- Extras --------------------------------------------------------------------------


def extras_limit_message(product: Product) -> str:
    """The sentence shown when a product already has ``MAX_EXTRAS`` extras."""
    return (
        f"{product.name} already has {MAX_EXTRAS} extra images, the most a "
        "product can have. Remove one before adding another."
    )


def add_extra_image(
    product: Product, image: PreparedImage, alt_text: str = ""
) -> ProductImage:
    """Append ``image`` to the end of the product's extras.

    Extras are shown after the main image and never affect it. Raises
    ``ValidationError`` if the product already has ``MAX_EXTRAS``; on any
    other failure the new files are removed and the exception propagates.
    """
    if product.extra_images.count() >= MAX_EXTRAS:
        raise ValidationError(extras_limit_message(product), code="extras_limit")
    display, thumbnail = _store(image, PRODUCT_FOLDER)
    try:
        with transaction.atomic():
            last = product.extra_images.aggregate(last=Max("sort_order"))["last"]
            extra = product.extra_images.create(
                image=display,
                thumbnail=thumbnail,
                width=image.width,
                height=image.height,
                alt_text=alt_text,
                sort_order=0 if last is None else last + 1,
            )
    except Exception:
        _delete_now([display, thumbnail])
        raise
    return extra


def remove_extra_image(extra: ProductImage) -> None:
    """Delete one extra; its files go once the deletion commits."""
    extra.delete()


def move_extra(extra: ProductImage, direction: Literal["up", "down"]) -> bool:
    """Swap an extra with its neighbour; ``up`` moves it earlier in the gallery.

    Renumbers the product's extras 0, 1, 2… as it goes, so gaps left by
    removals (or equal positions) can't make a move silently do nothing.
    Returns ``False`` if the extra is already at that end, or has been
    removed meanwhile.
    """
    with transaction.atomic():
        extras = list(extra.product.extra_images.select_for_update())
        pks = [other.pk for other in extras]
        if extra.pk not in pks:
            return False
        index = pks.index(extra.pk)
        target = index - 1 if direction == "up" else index + 1
        if not 0 <= target < len(extras):
            return False
        extras[index], extras[target] = extras[target], extras[index]
        for position, other in enumerate(extras):
            if other.sort_order != position:
                other.sort_order = position
                other.save(update_fields=["sort_order"])
    return True


# --- Order snapshots -------------------------------------------------------------------


def snapshot_for_order(order: Order) -> int:
    """Copy each line's product thumbnail onto the line, as it looks right now.

    An order is a snapshot, so its lines keep their own copy of the
    image, just as they keep their own name and price. A line whose
    product has no image (or whose file is missing) gets none, and shows
    the placeholder.

    Never raises: a failed copy must never fail an order. ``place_order``
    runs this after its transaction commits, so it cannot roll one back
    either. Returns how many lines got an image.
    """
    copied = 0
    try:
        items = list(order.items.select_related("product"))
    except Exception:
        logger.warning(
            "Could not snapshot images for order %s", order.pk, exc_info=True
        )
        return 0
    for item in items:
        try:
            copied += _snapshot_line(item)
        except Exception:
            logger.warning(
                "Could not snapshot the image for order line %s", item.pk, exc_info=True
            )
    return copied


def _snapshot_line(item) -> bool:
    product = item.product
    if product is None or item.image or stored_url(product.image_thumbnail) is None:
        return False
    source = product.image_thumbnail
    with source.storage.open(source.name, "rb") as file:
        data = file.read()
    name = default_storage.save(
        f"{ORDER_FOLDER}/{uuid.uuid4().hex}.webp", ContentFile(data)
    )
    try:
        item.image = name
        item.image_width, item.image_height = thumbnail_size(
            product.image_width, product.image_height
        )
        item.save(update_fields=["image", "image_width", "image_height"])
    except Exception:
        item.image = ""
        _delete_now([name])
        raise
    return True
