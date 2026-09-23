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

    def active(self, at=None):
        """Codes with a future: live now, or scheduled to start.

        Deliberately wider than ``live`` and deliberately narrower than
        ``is_active``. A code that has not started yet still belongs in
        the back office's default view — it is a promotion someone is
        waiting on. An expired one does not, even though its ``is_active``
        flag is still ``True``: nothing will ever make it work again.
        """
        at = at or timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=at)
        )

    def inactive(self, at=None):
        """The exact complement of ``active``: retired codes and expired ones."""
        at = at or timezone.now()
        return self.filter(models.Q(is_active=False) | models.Q(ends_at__lte=at))

    def with_usage(self):
        """Annotate ``used`` — the redemptions counting against the limits.

        The same two rules ``DiscountCode.counted_orders`` applies, in SQL:
        cancelled orders release their use, and a code whose count was
        reset on reinstatement only counts orders placed since.
        """
        counted = ~models.Q(orders__status=Order.Status.CANCELLED) & (
            models.Q(counting_since__isnull=True)
            | models.Q(orders__created_at__gte=models.F("counting_since"))
        )
        return self.annotate(used=models.Count("orders", filter=counted, distinct=True))

    def find(self, raw):
        """Look up a code as the customer typed it; ``None`` if there is no such code."""
        normalized = DiscountCode.normalize(raw)
        if not normalized:
            return None
        return self.filter(code=normalized).first()


class DiscountCode(models.Model):
    """A promotional code that lowers an order's total.

    A code discounts either the whole order or a chosen set of products —
    ``applies_to`` says which, and ``products`` holds the set. The two
    kinds differ in how they treat quantity, deliberately: a percentage
    is proportional, so it scales with the units bought, while a fixed
    amount means what it says and comes off once, capped at what it is
    discounting.

    The scope is an explicit field rather than "empty means everything"
    for one reason: staff can delete products. A ``SELECTED`` code whose
    last product is deleted discounts *nothing*, which is a promotion
    that quietly stops working — where the implicit spelling would have
    turned it into a discount on the entire store instead.

    ``per_user_limit`` and ``total_limit`` cap redemptions; ``None``
    means no cap. Uses are counted from the orders themselves rather
    than a running total, so the number can never drift from reality —
    see ``counted_orders`` for the two rules that shape that count.

    Codes are never deleted. ``is_active`` retires one, and neither
    retiring nor editing a code touches an order that already used it —
    orders keep their own snapshot of what they were given.
    """

    class Kind(models.TextChoices):
        PERCENT = "PERCENT", "Percent off"
        AMOUNT = "AMOUNT", "Amount off"

    class Scope(models.TextChoices):
        ALL = "ALL", "The whole order"
        SELECTED = "SELECTED", "Only the products I choose"

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
    applies_to = models.CharField(
        max_length=8,
        choices=Scope.choices,
        default=Scope.ALL,
        help_text="Whether the discount covers everything in the cart or a chosen few.",
    )
    products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="discount_codes",
        help_text="Only used when the discount covers chosen products.",
    )
    per_user_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=1,
        help_text="How many times one customer may use it. Blank means unlimited.",
    )
    total_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="How many times it may be used across all customers. "
        "Blank means unlimited.",
    )
    # Set when staff reinstate a code and choose to start its count over.
    # The orders are untouched; only what counts towards the limits moves.
    counting_since = models.DateTimeField(null=True, blank=True, editable=False)
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

    def counted_orders(self):
        """The orders that count against this code's limits.

        Two rules, both deliberate. A cancelled order releases its use —
        the customer never received the goods, so they get their
        redemption back. And when staff reinstate a code and reset its
        count, ``counting_since`` draws a line: earlier orders keep their
        frozen discount but no longer occupy a slot in the new run.
        """
        orders = self.orders.exclude(status=Order.Status.CANCELLED)
        if self.counting_since:
            orders = orders.filter(created_at__gte=self.counting_since)
        return orders

    def times_used(self):
        """How many redemptions count against ``total_limit``."""
        return self.counted_orders().count()

    def times_used_by(self, user):
        """How many of this customer's redemptions count against ``per_user_limit``."""
        if user is None or not user.is_authenticated:
            return 0
        return self.counted_orders().filter(user=user).count()

    def unusable_reason(self, user=None, at=None):
        """Why this code cannot be used, as a sentence for the customer — or ``None``.

        The single answer to "may this cart have this discount?", called
        from the cart box, from the cart's own total, from the checkout
        guard and from ``place_order``. Every rejection names the code and
        says what is actually wrong with it, so no caller has to invent
        wording of its own — or, worse, its own copy of the rules.

        ``user`` may be omitted when only the code's own state matters;
        the per-customer limit is then skipped.
        """
        at = at or timezone.now()
        if not self.is_active:
            return f"{self.code} is no longer available."
        if self.starts_at and at < self.starts_at:
            starts = timezone.localtime(self.starts_at).strftime("%B %-d")
            return f"{self.code} doesn't start until {starts}."
        if self.ends_at and at >= self.ends_at:
            ended = timezone.localtime(self.ends_at).strftime("%B %-d")
            return f"{self.code} expired on {ended}."
        if self.total_limit is not None and self.times_used() >= self.total_limit:
            return f"{self.code} has been fully claimed."
        if user is not None and self.per_user_limit is not None:
            if self.times_used_by(user) >= self.per_user_limit:
                if self.per_user_limit == 1:
                    return f"You've already used {self.code}."
                return (
                    f"You've already used {self.code} "
                    f"{self.per_user_limit} times, which is the limit."
                )
        return None

    @property
    def amount_label(self):
        """The size of the discount, e.g. ``50%`` or ``$20.00``."""
        if self.kind == self.Kind.PERCENT:
            return f"{self.value.normalize():f}%"
        return f"${self.value}"

    @property
    def target_label(self):
        """What the code covers, in words: “your order”, “Seraphine and Halo”.

        Names up to two products and counts the rest, so the phrase stays
        a phrase whether the code covers one product or twenty-five. It
        reads inside a table cell, a cart note and a form error alike.
        """
        if self.applies_to == self.Scope.ALL:
            return "your order"
        names = list(self.products.values_list("name", flat=True))
        if not names:
            return "no products"
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return f"{names[0]}, {names[1]} and {len(names) - 2} more"

    @property
    def covers_one_product(self):
        """Whether ``target_label`` reads as a singular — the template's grammar."""
        return self.applies_to == self.Scope.SELECTED and self.products.count() == 1

    @property
    def label(self):
        """What the code does, in words: “50% off Seraphine”."""
        return f"{self.amount_label} off {self.target_label}"

    def covered_lines(self, cart):
        """The cart lines this code applies to — all of them, or the chosen ones."""
        if self.applies_to == self.Scope.ALL:
            return list(cart.lines())
        covered = set(self.products.values_list("pk", flat=True))
        return [line for line in cart.lines() if line.product_id in covered]

    def discount_for(self, cart):
        """How much this code takes off ``cart`` — never more than it discounts.

        Returns ``0.00`` when nothing in the cart matches, so a code for a
        product the customer has since removed — or one whose products
        have all been deleted from the catalog — simply stops discounting
        instead of erroring or widening to the whole order.
        """
        base = sum((line.line_total for line in self.covered_lines(cart)), ZERO)
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

    def discount_problem(self):
        """Why the attached code isn't discounting, as a sentence — or ``None``.

        The cart page's warning line, and the reason ``discount_amount``
        returns zero. Kept as its own method because a template cannot
        call ``unusable_reason`` with an argument.
        """
        code = self.discount_code
        if code is None:
            return None
        return code.unusable_reason(self.user)

    def discount_amount(self):
        """What the applied code takes off, or zero if there isn't a usable one.

        Eligibility is re-checked on every read: a code applied yesterday
        may have expired overnight, and one applied this morning may have
        been claimed by someone else since. The cart must never show a
        discount it would not actually get.
        """
        code = self.discount_code
        if code is None or self.discount_problem():
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
