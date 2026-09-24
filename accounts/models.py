from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone

from .validators import zip_validator

US_STATES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]

# The fields that make up an address, in the order they read. Checkout's
# own fields are these names behind a ``shipping_``/``billing_`` prefix,
# so moving values between the two is a prefix strip and nothing more —
# which is why the ZIP field here is ``zip`` and not ``zip_code``.
ADDRESS_FIELDS = ["name", "street", "line2", "city", "state", "zip"]


class User(AbstractUser):
    """The store's user model.

    Roles use Django's own vocabulary and nothing else: customers are
    plain users, employees are ``is_staff``, the admin is ``is_superuser``.
    """

    # Nullable per the PRD: an absent job title is unknown, not empty.
    job_title = models.CharField(max_length=150, null=True, blank=True)  # noqa: DJ001


class AddressQuerySet(models.QuerySet):
    def matching(self, values):
        """The addresses equal to ``values``, compared case-insensitively.

        Exact string equality would call "742 Evergreen" and "742
        evergreen" two different places and let a duplicate through, so
        every field is compared with ``iexact``. The label is excluded
        deliberately: it is a nickname, not an identity, and a customer
        who renames their house has not moved.
        """
        return self.filter(
            **{f"{field}__iexact": values[field] for field in ADDRESS_FIELDS}
        )

    def remember(self, user, checkout_data, prefix):
        """Save one of checkout's addresses to ``user``'s book, if it is new.

        ``prefix`` is ``"shipping_"`` or ``"billing_"``; the matching
        fields are lifted out of a valid ``CheckoutForm``'s
        ``cleaned_data``. An address the customer already has is
        returned untouched rather than duplicated — they were buying
        something, not editing their address book, so their existing
        label survives.

        Called *after* ``place_order`` returns and outside its
        transaction: remembering an address is a courtesy, and it must
        never be able to take down the order that was just placed.
        """
        values = {field: checkout_data[f"{prefix}{field}"] for field in ADDRESS_FIELDS}
        mine = self.filter(user=user)
        existing = mine.matching(values).first()
        if existing is not None:
            return existing

        first = not mine.exists()
        address = self.create(user=user, **values)
        if first:
            # The first address a customer saves is their default for
            # both roles, so checkout always has something to pre-select.
            address.make_default(shipping=True, billing=True)
        return address


class Address(models.Model):
    """One address in a customer's book, usable for shipping or billing.

    Rows are deliberately role-free: nothing here says "shipping" or
    "billing". A role is something an *order* has, frozen into its own
    column names at checkout, and an address is only ever asked to play
    one. What the model does carry is a *preference* — which address to
    pre-select for each role — because that is changeable and optional
    in a way a permanent kind would not be.

    No order points at an address. ``Order`` keeps its own flat copy of
    every field (see ``orders.models.Order``), so editing an address
    cannot rewrite history and deleting one cannot damage it. That is
    what makes this model safe to delete from freely.

    Two invariants hold, both by construction rather than by repair:
    a customer with at least one address has exactly one default per
    role, and ``make_default`` is the only thing that ever moves one.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    label = models.CharField(
        max_length=50,
        blank=True,
        help_text="What you call this address — “Home”, “Work”. Optional.",
    )
    name = models.CharField(max_length=100)
    street = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, choices=US_STATES)
    zip = models.CharField(max_length=10, validators=[zip_validator])
    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)
    # Not auto_now_add: the seed backdates address books the same way it
    # backdates orders, and "most recently added" decides who inherits a
    # default when the address holding it is deleted.
    created_at = models.DateTimeField(default=timezone.now)

    objects = AddressQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "addresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default_shipping=True),
                name="one_default_shipping_per_user",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default_billing=True),
                name="one_default_billing_per_user",
            ),
        ]

    def __str__(self):
        return self.display_name

    @property
    def summary(self):
        """The address on one line: “77 Cortex Lane, Amarillo, TX 79101”."""
        parts = [self.street]
        if self.line2:
            parts.append(self.line2)
        parts.append(f"{self.city}, {self.state} {self.zip}")
        return ", ".join(parts)

    @property
    def display_name(self):
        """What the picker shows: the customer's own name for it, or the street."""
        return self.label or self.summary

    @property
    def default_for(self):
        """Which roles this address holds, in words — the list page's badge."""
        roles = []
        if self.is_default_shipping:
            roles.append("shipping")
        if self.is_default_billing:
            roles.append("billing")
        return " and ".join(roles)

    @transaction.atomic
    def make_default(self, *, shipping=False, billing=False):
        """Take over the named roles, stepping the previous holder aside.

        The only verb the defaults have. Order matters: the sibling is
        cleared *before* this row is set, because two rows holding one
        role is exactly what the unique constraints forbid — and the
        transaction is what keeps that window from ever being observed.

        There is deliberately no way to *clear* a default. The one
        gesture that would try — unticking the box on the address that
        currently holds the role — is disabled on the form instead,
        because its only honest outcome is a customer with addresses and
        nothing pre-selected at checkout.
        """
        siblings = Address.objects.filter(user=self.user).exclude(pk=self.pk)
        if shipping:
            siblings.filter(is_default_shipping=True).update(is_default_shipping=False)
            self.is_default_shipping = True
        if billing:
            siblings.filter(is_default_billing=True).update(is_default_billing=False)
            self.is_default_billing = True
        self.save(update_fields=["is_default_shipping", "is_default_billing"])

    @transaction.atomic
    def delete(self, *args, **kwargs):
        """Delete, then hand any vacated default to the newest survivor.

        Deleting is safe at any time — no order refers to an address —
        but it can leave a customer holding addresses with none of them
        pre-selected. Promoting the most recently added survivor is the
        same rule that gives a customer's *first* address both roles,
        applied on the way out instead of the way in.
        """
        roles = {
            "shipping": self.is_default_shipping,
            "billing": self.is_default_billing,
        }
        user = self.user
        result = super().delete(*args, **kwargs)
        if any(roles.values()):
            heir = Address.objects.filter(user=user).first()
            if heir is not None:
                heir.make_default(**roles)
        return result
