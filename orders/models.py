from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from products.models import Product

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

code_validator = RegexValidator(
    r"^[A-Za-z0-9]{3,20}$",
    "Use 3–20 letters and digits, like SUMMER50.",
)


def to_cents(amount):
    """Round a money figure to cents, halves going up."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


class DiscountCodeQuerySet(models.QuerySet):
    def live(self, at=None):
        """Codes a customer could use right now: active and inside their window."""
        at = at or timezone.now()
        return (
            self.filter(is_active=True)
            .filter(models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=at))
            .filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=at))
        )

    def find(self, raw):
        """Look up a code as the customer typed it; ``None`` if there is no such code."""
        normalized = DiscountCode.normalize(raw)
        if not normalized:
            return None
        return self.filter(code=normalized).first()


class DiscountCode(models.Model):
    """A promotional code that lowers an order's total.

    A code discounts either the whole order or a single product's line —
    ``product`` is null for the former. The two kinds differ in how they
    treat quantity, deliberately: a percentage is proportional, so it
    scales with the units bought, while a fixed amount means what it
    says and comes off once, capped at what it is discounting.

    Codes are never deleted. ``is_active`` retires one, and neither
    retiring nor editing a code touches an order that already used it —
    orders keep their own snapshot of what they were given.
    """

    class Kind(models.TextChoices):
        PERCENT = "PERCENT", "Percent off"
        AMOUNT = "AMOUNT", "Amount off"

    code = models.CharField(
        max_length=20,
        unique=True,
        validators=[code_validator],
        help_text="What the customer types. Stored and matched in capitals.",
    )
    kind = models.CharField(max_length=7, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(CENT)],
        help_text="A percentage for “Percent off”, dollars for “Amount off”.",
    )
    # CASCADE, not SET_NULL: a code for a deleted product must not quietly
    # become a code for everything. Orders keep their snapshot regardless.
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="discount_codes",
        help_text="Leave blank to discount the whole order.",
    )
    starts_at = models.DateTimeField(
        null=True, blank=True, help_text="Blank means it is live immediately."
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The first moment the code no longer works. Blank means it runs until retired.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to retire the code. Past orders are unaffected.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    objects = DiscountCodeQuerySet.as_manager()

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.normalize(self.code)
        return super().save(*args, **kwargs)

    @staticmethod
    def normalize(raw):
        """The stored form of a typed code: trimmed and capitalised."""
        return (raw or "").strip().upper()

    def clean(self):
        """The two rules that depend on more than one field."""
        errors = {}
        if self.kind == self.Kind.PERCENT and self.value and self.value > 100:
            errors["value"] = "A percentage can't be more than 100."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "The end must come after the start."
        if errors:
            raise ValidationError(errors)

    def is_live(self, at=None):
        """Whether the code is active and inside its window at ``at`` (default now)."""
        at = at or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and at < self.starts_at:
            return False
        return not (self.ends_at and at >= self.ends_at)

    @property
    def status(self):
        """One word for the back office: retired, scheduled, expired, or live."""
        now = timezone.now()
        if not self.is_active:
            return "retired"
        if self.starts_at and now < self.starts_at:
            return "scheduled"
        if self.ends_at and now >= self.ends_at:
            return "expired"
        return "live"

    @property
    def amount_label(self):
        """The size of the discount, e.g. ``50%`` or ``$20.00``."""
        if self.kind == self.Kind.PERCENT:
            return f"{self.value.normalize():f}%"
        return f"${self.value}"

    @property
    def label(self):
        """What the code does, in words: “50% off Seraphine”."""
        target = self.product.name if self.product else "your order"
        return f"{self.amount_label} off {target}"

    def discount_for(self, cart):
        """How much this code takes off ``cart`` — never more than it discounts.

        Returns ``0.00`` when nothing in the cart matches, so a code for a
        product the customer has since removed simply stops discounting
        instead of erroring.
        """
        lines = [
            line
            for line in cart.lines()
            if self.product_id is None or line.product_id == self.product_id
        ]
        base = sum((line.line_total for line in lines), ZERO)
        if base <= ZERO:
            return ZERO
        if self.kind == self.Kind.PERCENT:
            discount = to_cents(base * self.value / 100)
        else:
            discount = to_cents(self.value)
        return min(discount, base)


class Cart(models.Model):
    """A customer's cart — one per user, created lazily on first touch."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    discount_code = models.ForeignKey(
        DiscountCode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carts",
    )

    def __str__(self):
        return f"Cart for {self.user.username}"

    @classmethod
    def for_user(cls, user):
        """Return the user's cart, creating it on first touch."""
        cart, _ = cls.objects.get_or_create(user=user)
        return cart

    def add(self, product):
        """Add a product to the cart; a duplicate add increments its line."""
        item, created = self.items.get_or_create(product=product)
        if not created:
            item.quantity += 1
            item.save()
        return item

    def lines(self):
        """Line items with their products loaded, ready for display."""
        return self.items.select_related("product")

    def subtotal(self):
        """The cart's contents at list price, before any discount."""
        return sum((item.line_total for item in self.lines()), ZERO)

    def discount_amount(self):
        """What the applied code takes off, or zero if there isn't a usable one.

        Liveness is re-checked on every read: a code applied yesterday may
        have expired overnight, and the cart must never show a discount it
        would not actually get.
        """
        code = self.discount_code
        if code is None or not code.is_live():
            return ZERO
        return code.discount_for(self)

    def total(self):
        """What the customer would pay: subtotal less any discount."""
        return self.subtotal() - self.discount_amount()

    def item_count(self):
        """Total units across all lines — the navbar badge number."""
        return self.items.aggregate(count=models.Sum("quantity"))["count"] or 0


class CartItem(models.Model):
    """One product line in a cart; the cart–product pair is unique."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"], name="unique_cart_product"
            )
        ]

    def __str__(self):
        return f"{self.quantity} × {self.product.name}"

    @property
    def line_total(self):
        return self.product.price * self.quantity

    def increment(self):
        self.quantity += 1
        self.save()

    def decrement(self):
        """Step the quantity down, stopping at one — removal is explicit."""
        if self.quantity > 1:
            self.quantity -= 1
            self.save()


class Order(models.Model):
    """A placed order — a snapshot, never a live view of the catalog.

    Addresses are flat denormalized fields: the order must not change if
    the customer later edits anything. Of the card, only the last four
    digits survive checkout.

    A discount is denormalized the same way, and for the same reason: the
    code's name and the dollars it took off are frozen here, so retiring
    or editing that code later cannot rewrite what this order was given.
    The ``discount_code_used`` link is a convenience for reporting and is
    allowed to go null.
    """

    class Status(models.TextChoices):
        PLACED = "PLACED", "Placed"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PLACED
    )
    total = models.DecimalField(max_digits=10, decimal_places=2)
    email = models.EmailField()

    shipping_name = models.CharField(max_length=100)
    shipping_street = models.CharField(max_length=200)
    shipping_line2 = models.CharField(max_length=200, blank=True)
    shipping_city = models.CharField(max_length=100)
    shipping_state = models.CharField(max_length=2)
    shipping_zip = models.CharField(max_length=10)

    billing_name = models.CharField(max_length=100)
    billing_street = models.CharField(max_length=200)
    billing_line2 = models.CharField(max_length=200, blank=True)
    billing_city = models.CharField(max_length=100)
    billing_state = models.CharField(max_length=2)
    billing_zip = models.CharField(max_length=10)

    card_last4 = models.CharField(max_length=4)

    discount_code_used = models.ForeignKey(
        DiscountCode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    discount_code = models.CharField(max_length=20, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    # default (not auto_now_add) so the seed can backdate orders.
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    @property
    def number(self):
        """The customer-facing order number, e.g. ``TT-2026-00042``."""
        return f"TT-{self.created_at.year}-{self.pk:05d}"

    @property
    def subtotal(self):
        """The order's lines at their purchase prices, before the discount."""
        return sum((item.line_total for item in self.items.all()), ZERO)


class OrderItem(models.Model):
    """One line of an order, priced as of purchase time.

    Name and unit price are denormalized: order history must not change
    when the catalog does. The product FK survives for linking while the
    product exists.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity
