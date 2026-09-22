"""Project-wide pytest fixtures.

Shared test data lives here as plain fixtures — no factories. The suite
grows with the project; tests never invoke the seed command.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from orders.models import Cart, CartItem, DiscountCode
from products.models import Category, Product, Tag


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
def percent_code(db):
    """10% off the whole order, open-ended."""
    return DiscountCode.objects.create(
        code="THOUGHTS10", kind=DiscountCode.Kind.PERCENT, value=Decimal("10")
    )


@pytest.fixture
def amount_code(db):
    """$20 off the whole order, open-ended."""
    return DiscountCode.objects.create(
        code="MINDFUL20", kind=DiscountCode.Kind.AMOUNT, value=Decimal("20.00")
    )


@pytest.fixture
def product_code(product):
    """50% off Seraphine only — the worked example from the design."""
    return DiscountCode.objects.create(
        code="SERAPHINE50",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("50"),
        product=product,
    )


@pytest.fixture
def expired_code(db):
    """A code whose promotion ended yesterday."""
    return DiscountCode.objects.create(
        code="LASTQUARTER",
        kind=DiscountCode.Kind.PERCENT,
        value=Decimal("25"),
        ends_at=timezone.now() - timedelta(days=1),
    )
