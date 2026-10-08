import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.crypto import salted_hmac

from products.images import (
    AVATAR_FOLDER,
    avatar_picture,
    delete_files_on_commit,
)

from .validators import username_no_at_validator, zip_validator

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


class UserManager(DjangoUserManager):
    def with_email(self, email):
        """Accounts using ``email``, compared case-insensitively.

        A blank email matches nobody: accounts from before email was
        required all have ``""``, and they don't share an address.
        """
        if not email:
            return self.none()
        return self.filter(email__iexact=email)

    def get_by_identifier(self, identifier):
        """The one account whose username or email is ``identifier``.

        Both comparisons ignore case. The match is unambiguous: usernames
        can't contain ``@``, so no username is anyone's email, and each is
        unique case-insensitively. Raises ``DoesNotExist`` when nobody
        matches, as ``get`` does.
        """
        try:
            return self.get(username__iexact=identifier)
        except self.model.DoesNotExist:
            return self.with_email(identifier).get()


class User(AbstractUser):
    """The store's user model.

    Roles use Django's own vocabulary and nothing else: customers are
    plain users, employees are ``is_staff``, the admin is ``is_superuser``.

    Usernames and emails are each unique case-insensitively, enforced by
    functional constraints so that no path — sign-up, a rename, the admin,
    a shell — can slip a ``Casey`` past a ``casey``. Emails are stored as
    entered; only comparisons ignore case. Blank emails are exempt,
    because accounts created before sign-up asked for one have ``""``.
    """

    username = models.CharField(
        "username",
        max_length=150,
        unique=True,
        help_text="Required. 150 characters or fewer. Letters, digits and ./+/-/_ only.",
        validators=[UnicodeUsernameValidator(), username_no_at_validator],
        error_messages={"unique": "A user with that username already exists."},
    )
    # Nullable per the PRD: an absent job title is unknown, not empty.
    job_title = models.CharField(max_length=150, null=True, blank=True)  # noqa: DJ001
    # Mixed into the session auth hash beside the password, so rotating it
    # signs out every session that isn't refreshed — exactly as a password
    # change does, without changing the password. Not a secret.
    session_key = models.CharField(max_length=32, blank=True, editable=False)
    # When the owner proved they receive mail at ``email``. Null until
    # then; an unverified account works exactly like a verified one.
    email_verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    # A square profile picture, written only by ``products.images``.
    # Templates read ``avatar_picture``, never this field.
    avatar = models.ImageField(upload_to=AVATAR_FOLDER, blank=True, editable=False)

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="unique_username_ci",
                violation_error_message="A user with that username already exists.",
            ),
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="unique_email_ci",
                violation_error_message=(
                    "An account with that email address already exists."
                ),
            ),
        ]

    def clean(self):
        # AbstractUser.clean lowercases the email's domain. Emails are
        # stored exactly as entered and compared case-insensitively, so
        # put back what was typed.
        email = self.email
        super().clean()
        self.email = email

    def _get_session_auth_hash(self, secret=None):
        # Django's own hash covers the password alone; adding the session
        # key lets ``rotate_session_key`` end other sessions too. Both
        # ``get_session_auth_hash`` and its ``SECRET_KEY_FALLBACKS``
        # variant come through here.
        return salted_hmac(
            "accounts.User.get_session_auth_hash",
            f"{self.password}:{self.session_key}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    def rotate_session_key(self):
        """Invalidate every session signed in as this user.

        The caller keeps its own session by passing the request to
        ``update_session_auth_hash`` afterwards.
        """
        self.session_key = secrets.token_hex(16)
        self.save(update_fields=["session_key"])

    @property
    def display_name(self):
        """The person's name if they've given one, otherwise their username."""
        return self.get_full_name() or self.get_username()

    @property
    def avatar_picture(self):
        """Their profile picture as a ``Picture``, or the silhouette placeholder."""
        return avatar_picture(self, f"Profile picture of {self.display_name}")

    def greeting(self, now=None):
        """ "Good morning, Casey", by the hour in the store's time zone.

        Uses the first name when there is one, else the username. ``now``
        defaults to the current time; tests pass a fixed one.
        """
        hour = timezone.localtime(now).hour
        if 5 <= hour < 12:
            part = "morning"
        elif 12 <= hour < 18:
            part = "afternoon"
        else:
            part = "evening"
        return f"Good {part}, {self.first_name or self.get_username()}"

    @property
    def email_verified(self):
        """Whether the account has an email and its owner has confirmed it."""
        return bool(self.email) and self.email_verified_at is not None

    @property
    def password_last_changed(self):
        """When the password was last changed or reset, or ``None`` if never.

        Read from the audit log rather than a column of its own, so it
        can't disagree with the history the Account page shows beside it.
        """
        return (
            self.security_events.password_changes()
            .values_list("created_at", flat=True)
            .first()
        )


@receiver(post_delete, sender=User)
def delete_avatar_file(sender, instance, **kwargs):
    """A deleted account takes its profile picture with it (on commit)."""
    delete_files_on_commit(instance.avatar.name)


class SecurityEventQuerySet(models.QuerySet):
    def password_changes(self):
        """Events that set a new password: a change, or a completed reset."""
        return self.filter(
            kind__in=[
                SecurityEvent.Kind.PASSWORD_CHANGED,
                SecurityEvent.Kind.PASSWORD_RESET_COMPLETED,
            ]
        )


class SecurityEvent(models.Model):
    """One line of the security audit log: what happened to an account.

    Written only through ``accounts.security.record_event`` and never
    edited afterwards — the admin offers no add, change or delete, to
    superusers included. ``user`` is the account the event happened to;
    ``actor`` is who did it: the owner themselves, a superuser applying an
    override, or nobody (a failed sign-in, a server-side command).

    Both links are ``SET_NULL`` where the rest of the codebase cascades,
    because an audit log that disappears with the account it describes
    isn't an audit log. ``username`` is a snapshot taken when the event
    was recorded, so a deleted or renamed account still reads correctly.

    Passwords, codes, tokens and secrets are never stored, in ``details``
    or anywhere else on the row.
    """

    class Kind(models.TextChoices):
        SIGN_UP = "sign_up", "Signed up"
        SIGN_IN_SUCCEEDED = "sign_in_succeeded", "Signed in"
        SIGN_IN_FAILED = "sign_in_failed", "Sign-in failed"
        TWO_FACTOR_CODE_FAILED = "2fa_code_failed", "Two-factor code failed"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        PASSWORD_RESET_REQUESTED = (
            "password_reset_requested",
            "Password reset requested",
        )
        PASSWORD_RESET_COMPLETED = (
            "password_reset_completed",
            "Password reset completed",
        )
        EMAIL_CHANGE_REQUESTED = "email_change_requested", "Email change requested"
        EMAIL_CHANGE_CONFIRMED = "email_change_confirmed", "Email changed"
        EMAIL_VERIFIED = "email_verified", "Email verified"
        USERNAME_CHANGED = "username_changed", "Username changed"
        TWO_FACTOR_ENABLED = "2fa_enabled", "Two-factor turned on"
        TWO_FACTOR_DISABLED = "2fa_disabled", "Two-factor turned off"
        TWO_FACTOR_RESET = "2fa_reset", "Two-factor reset"
        RECOVERY_CODES_REGENERATED = (
            "recovery_codes_regenerated",
            "Recovery codes regenerated",
        )
        RECOVERY_CODE_USED = "recovery_code_used", "Recovery code used"
        ACCOUNT_LOCKED = "account_locked", "Account locked"
        ACCOUNT_UNLOCKED = "account_unlocked", "Account unlocked"
        COOLDOWN_STARTED = "cooldown_started", "Sign-in paused"
        COOLDOWN_CLEARED = "cooldown_cleared", "Sign-in cooldown cleared"
        OTHER_SESSIONS_ENDED = "other_sessions_ended", "Signed out of other devices"
        SESSION_ENDED = "session_ended", "Signed out a device"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_actions",
    )
    username = models.CharField(
        max_length=150,
        blank=True,
        help_text="The account's username when the event was recorded.",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    # A default rather than auto_now_add, so tests can pin the clock and
    # the cooldown's 15-minute window can be exercised without sleeping.
    created_at = models.DateTimeField(default=timezone.now)
    # REMOTE_ADDR only: forwarded headers are spoofable without a known proxy.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    objects = SecurityEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"], name="securityevent_user_recent"
            ),
        ]

    def __str__(self):
        who = self.username or "unknown account"
        return f"{self.get_kind_display()} — {who}"

    @property
    def by_support(self):
        """Whether someone other than the owner did this — an admin override.

        The Account page shows such events as "by ThoughtTronix support"
        and never names the admin, so templates read this rather than
        ``actor``. An event with no actor (a failed sign-in, a server-side
        command) isn't support acting, and reads as plain history.
        """
        return self.actor_id is not None and self.actor_id != self.user_id


class UserSessionQuerySet(models.QuerySet):
    def active(self, now=None):
        """Sessions used within the session lifetime, most recently used first.

        A session left idle for ``SESSION_COOKIE_AGE`` has expired (each
        one's expiry slides forward as it is used, see
        ``accounts.security.track_session``), so its row describes nothing
        and is left out.
        """
        return self.filter(last_seen_at__gt=_session_cutoff(now)).order_by(
            "-last_seen_at", "-pk"
        )

    def expired(self, now=None):
        return self.filter(last_seen_at__lte=_session_cutoff(now))


def _session_cutoff(now=None):
    return (now or timezone.now()) - timedelta(seconds=settings.SESSION_COOKIE_AGE)


class UserSession(models.Model):
    """One browser signed in to an account — a "device" on the Account page.

    Created at sign-in, and its id kept in that browser's session. Every
    signed-in request looks for the row; deleting it is how one device is
    signed out from another, because the next request from that browser
    finds nothing and is signed out. The Django session key itself is
    never stored: it is a bearer credential, and the row's id is enough.

    The IP and user agent are what the owner needs to recognise the
    device, refreshed as it is used.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_sessions",
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    objects = UserSessionQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "-last_seen_at"], name="usersession_user_recent"
            ),
        ]

    def __str__(self):
        return f"{self.label} — {self.user}"

    @property
    def label(self):
        """A readable name for the device, such as "Firefox on Windows"."""
        browser = _first_match(self.user_agent, _BROWSERS)
        system = _first_match(self.user_agent, _SYSTEMS)
        if browser and system:
            return f"{browser} on {system}"
        return browser or system or "Unknown browser"

    @property
    def is_phone(self):
        """Whether the device is a phone, so the Account page can draw one."""
        return _first_match(self.user_agent, _SYSTEMS) in {"iPhone", "Android"}


# User-agent markers, checked in order: Edge and Opera also say "Chrome",
# Chrome also says "Safari", iPhones also say "Mac OS X", and Android also
# says "Linux", so the more specific marker has to come first.
_BROWSERS = [
    ("Edg", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("CriOS/", "Chrome"),
    ("Safari/", "Safari"),
]
_SYSTEMS = [
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
]


def _first_match(user_agent, markers):
    return next((name for marker, name in markers if marker in user_agent), None)


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
