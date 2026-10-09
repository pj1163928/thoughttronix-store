"""Project-wide pytest fixtures.

Shared test data lives here as plain fixtures — no factories. The suite
grows with the project; tests never invoke the seed command.
"""

import io
from datetime import timedelta
from decimal import Decimal

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from accounts.models import Address, TwoFactorDevice
from orders.models import Cart, CartItem, DiscountCode
from products.models import Category, Product, Tag


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    """Every test writes images to its own throwaway folder, never ./media."""
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def make_image():
    """Build an in-memory upload: ``make_image(800, 1000, "PNG", name="x.png")``.

    Extra keyword arguments go to Pillow's ``save`` (e.g. ``exif=``,
    ``save_all=`` and ``append_images=`` for an animation). ``mode`` and
    ``color`` shape the pixels.
    """

    def build(
        width=800,
        height=1000,
        format="PNG",
        *,
        name=None,
        mode="RGB",
        color=None,
        **save_options,
    ):
        image = Image.new(mode, (width, height), color or _default_color(mode))
        buffer = io.BytesIO()
        image.save(buffer, format, **save_options)
        extension = {"JPEG": "jpg"}.get(format, format.lower())
        return SimpleUploadedFile(
            name or f"photo.{extension}",
            buffer.getvalue(),
            content_type=f"image/{extension}",
        )

    return build


def _default_color(mode):
    return {
        "RGBA": (40, 80, 200, 128),
        "CMYK": (0, 128, 255, 0),
        "L": 128,
        "P": 3,
    }.get(mode, (40, 80, 200))


@pytest.fixture
def customer(db):
    return get_user_model().objects.create_user(
        username="customer", password="customer123"
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="employee",
        password="employee123",
        is_staff=True,
        job_title="Junior Thought Curator",
    )


@pytest.fixture
def enrol_two_factor(db):
    """Turn two-factor on for a user: ``enrol_two_factor(user)`` -> its device.

    Superusers need this before they can open any page but two-factor
    setup. The device is confirmed with a fresh secret; make codes from
    it with ``pyotp.TOTP(device.secret)``.
    """

    def enrol(user):
        return TwoFactorDevice.objects.create(
            user=user, secret=pyotp.random_base32(), confirmed_at=timezone.now()
        )

    return enrol


@pytest.fixture
def category(db):
    return Category.objects.create(name="Home Assistants", slug="home-assistants")


@pytest.fixture
def product(category):
    return Product.objects.create(
        name="Seraphine Home Hub",
        slug="seraphine-home-hub",
        tagline="She's always listening. In a good way.",
        description="The flagship Seraphine hub with a seven-microphone array.",
        price=Decimal("349.99"),
        category=category,
    )


@pytest.fixture
def unavailable_product(category):
    return Product.objects.create(
        name="EchoPatch",
        slug="echopatch",
        tagline="Never miss a word. Anyone's.",
        price=Decimal("139.00"),
        is_available=False,
        category=category,
    )


@pytest.fixture
def featured_product(category):
    return Product.objects.create(
        name="Cogitator Crown",
        slug="cogitator-crown",
        tagline="Wear your thoughts on your head.",
        price=Decimal("899.00"),
        is_featured=True,
        category=category,
    )


@pytest.fixture
def tag(db):
    return Tag.objects.create(name="bestseller", slug="bestseller")


@pytest.fixture
def cart(customer):
    return Cart.for_user(customer)


@pytest.fixture
def cart_item(cart, product):
    return CartItem.objects.create(cart=cart, product=product, quantity=2)


@pytest.fixture
def address(customer):
    """Casey's home address — her first, so the default for both roles."""
    saved = Address.objects.create(
        user=customer,
        label="Home",
        name="Casey Monroe",
        street="214 Synapse Street",
        city="Canyon",
        state="TX",
        zip="79015",
    )
    saved.make_default(shipping=True, billing=True)
    return saved


@pytest.fixture
def second_address(customer, address):
    """A second address, newer than ``address`` and default for nothing."""
    return Address.objects.create(
        user=customer,
        label="Work",
        name="Casey Monroe",
        street="77 Cortex Lane",
        line2="Suite 300",
        city="Amarillo",
        state="TX",
        zip="79101",
    )


@pytest.fixture
def percent_code(db):
    """10% off the whole order, open-ended, no limits."""
    return DiscountCode.objects.create(
        code="THOUGHTS10",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("10"),
        per_user_limit=None,
    )


@pytest.fixture
def amount_code(db):
    """$20 off the whole order, open-ended, no limits."""
    return DiscountCode.objects.create(
        code="MINDFUL20",
        kind=DiscountCode.Kind.AMOUNT,
        value=Decimal("20.00"),
        per_user_limit=None,
    )


@pytest.fixture
def product_code(product):
    """50% off Seraphine only — the worked example from the design."""
    code = DiscountCode.objects.create(
        code="SERAPHINE50",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("50"),
        applies_to=DiscountCode.Scope.SELECTED,
        per_user_limit=None,
    )
    code.products.add(product)
    return code


@pytest.fixture
def expired_code(db):
    """A code whose promotion ended yesterday."""
    return DiscountCode.objects.create(
        code="LASTQUARTER",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("25"),
        ends_at=timezone.now() - timedelta(days=1),
        per_user_limit=None,
    )


@pytest.fixture
def once_per_customer_code(db):
    """The default shape of a new code: one use per account, no overall cap."""
    return DiscountCode.objects.create(
        code="ONCEONLY", kind=DiscountCode.Kind.PERCENT, value=Decimal("10")
    )
