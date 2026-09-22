"""Order placement — one of the codebase's two deliberate deep modules.

The interface is the product: one function that turns a cart and a
validated checkout into an order, all-or-nothing. Callers never touch
``Order`` construction directly.
"""

from collections.abc import Mapping
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction

from .models import ZERO, Cart, Order, OrderItem

ADDRESS_FIELDS = [
    "email",
    "shipping_name",
    "shipping_street",
    "shipping_line2",
    "shipping_city",
    "shipping_state",
    "shipping_zip",
    "billing_name",
    "billing_street",
    "billing_line2",
    "billing_city",
    "billing_state",
    "billing_zip",
]


@transaction.atomic
def place_order(
    cart: Cart,
    user: AbstractBaseUser,
    checkout_data: Mapping[str, Any],
) -> Order:
    """Create an order from the cart's contents, then empty the cart.

    ``checkout_data`` is the ``cleaned_data`` of a valid ``CheckoutForm``.
    Addresses and line prices are denormalized onto the order — an order
    is a snapshot, immune to later catalog or address edits. Of the card,
    only the last four digits are stored; the full number and CVV never
    touch the database.

    A discount code applied to the cart is re-checked here rather than
    trusted: this is the last moment before money is decided, and a code
    can expire between the cart page and this call. What it took off is
    frozen onto the order, so retiring or editing that code afterwards
    leaves this order exactly as it was placed.

    All-or-nothing: runs in a transaction, so a failure partway through
    leaves no partial order and the cart intact.

    Raises ``ValueError`` if the cart is empty, holds a product that is
    no longer available, or carries a code that is no longer live.
    """
    lines = list(cart.lines())
    if not lines:
        raise ValueError("Cannot place an order from an empty cart.")
    unavailable = [line.product.name for line in lines if not line.product.is_available]
    if unavailable:
        raise ValueError(
            f"No longer available: {', '.join(unavailable)}. "
            "Remove them from the cart to check out."
        )

    code = cart.discount_code
    if code is not None and not code.is_live():
        raise ValueError(
            f"{code.code} is no longer valid. Remove it from your cart to check out."
        )
    discount = code.discount_for(cart) if code else ZERO

    card_digits = checkout_data["card_number"].replace(" ", "").replace("-", "")
    order = Order.objects.create(
        user=user,
        total=cart.subtotal() - discount,
        card_last4=card_digits[-4:],
        discount_code_used=code,
        discount_code=code.code if code else "",
        discount_amount=discount,
        **{name: checkout_data[name] for name in ADDRESS_FIELDS},
    )
    for line in lines:
        OrderItem.objects.create(
            order=order,
            product=line.product,
            product_name=line.product.name,
            unit_price=line.product.price,
            quantity=line.quantity,
        )
    cart.items.all().delete()
    cart.discount_code = None
    cart.save(update_fields=["discount_code"])
    return order
