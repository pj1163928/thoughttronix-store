from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from orders.models import Order, OrderItem
from products.images import avatar_picture
from products.models import Product

COMMENT_MIN = 10
COMMENT_MAX = 2000

# The product page's sort menu, in menu order: querystring value -> its label
# and ordering. Every ordering ends newest first, so ties read newest first.
NEWEST = ("-created_at", "-pk")
SORTS = {
    "newest": {"label": "Newest", "ordering": NEWEST},
    "highest": {"label": "Highest rated", "ordering": ("-rating", *NEWEST)},
    "lowest": {"label": "Lowest rated", "ordering": ("rating", *NEWEST)},
}
DEFAULT_SORT = "newest"

# The back office's Reviews tab sorts, in menu order. Reviewer A–Z is by the
# author's real name, first then last; accounts without a first name go
# last, by username. Every ordering ends newest first.
REVIEWER_ORDER = ("nameless", Lower("user__first_name"), Lower("user__last_name"))
MANAGE_SORTS = {
    "reviewer": {
        "label": "Reviewer A–Z",
        "ordering": (*REVIEWER_ORDER, Lower("user__username"), *NEWEST),
    },
    "product": {
        "label": "Product A–Z",
        "ordering": (Lower("product__name"), *NEWEST),
    },
    "newest": {"label": "Newest", "ordering": NEWEST},
}
DEFAULT_MANAGE_SORT = "reviewer"

# The fields the Reviews tab's search box looks in.
SEARCH_FIELDS = (
    "user__username",
    "user__first_name",
    "user__last_name",
    "product__name",
    "headline",
    "comment",
)


@dataclass(frozen=True)
class RatingSummary:
    """A product's customer numbers: how many counted reviews, and their average.

    ``average`` is in stars (1.0–5.0), or ``None`` with no counted reviews.
    """

    count: int
    average: float | None

    @property
    def half_stars(self):
        """The average rounded half up to a whole half star, for a star row."""
        if self.average is None:
            return 0
        exact = Decimal(str(self.average)) * 2
        return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    @property
    def average_display(self):
        """The average to one decimal place, rounded half up: "4.0", "3.8"."""
        if self.average is None:
            return ""
        exact = Decimal(str(self.average))
        return str(exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class ReviewQuerySet(models.QuerySet):
    def by(self, user):
        """``user``'s own reviews; none for an anonymous visitor."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(user=user)

    def changeable_by(self, user):
        """The reviews ``user`` may change: their own, or every one for staff.

        The one permission rule behind every edit, delete and removal.
        Anything outside it is a 404. Whether ``user`` wrote the review
        then decides which change applies (author edit or staff edit,
        delete or remove).
        """
        if not user.is_authenticated:
            return self.none()
        if user.is_staff:
            return self
        return self.filter(user=user)

    def live(self):
        """Reviews staff haven't removed: the ones the public may see."""
        return self.filter(removed_at__isnull=True)

    def removed(self):
        """Reviews staff have taken down: hidden from the public, kept for the back office."""
        return self.filter(removed_at__isnull=False)

    def filtered(self, q="", product=None, rating=None, author="", status=""):
        """The back office's Reviews tab search and filters, applied only where given.

        ``q`` a search (see ``searched``); ``product`` a ``Product``;
        ``rating`` a stored half-star value; ``author`` ``"customer"`` or
        ``"staff"`` (by the ``by_staff`` snapshot); ``status`` ``"live"``
        or ``"removed"``. Each one left empty leaves the list alone, and
        they compose.
        """
        reviews = self.searched(q)
        if product is not None:
            reviews = reviews.filter(product=product)
        if rating is not None:
            reviews = reviews.filter(rating=rating)
        if author:
            reviews = reviews.filter(by_staff=author == "staff")
        if status == "live":
            reviews = reviews.live()
        elif status == "removed":
            reviews = reviews.removed()
        return reviews

    def searched(self, q):
        """Reviews matching every word of ``q``, each word in any ``SEARCH_FIELDS``.

        Case-insensitive. Each word may match a different field, so "dana
        seraphine" finds Dana's review of Seraphine, and "dana cole" finds
        Dana Cole by first and last name. A blank ``q`` matches everything.
        """
        reviews = self
        for word in (q or "").split():
            matches = models.Q()
            for field in SEARCH_FIELDS:
                matches |= models.Q(**{f"{field}__icontains": word})
            reviews = reviews.filter(matches)
        return reviews

    def sorted_for_staff(self, sort):
        """These reviews in the Reviews tab's ``sort`` order: a key of ``MANAGE_SORTS``.

        An unknown ``sort`` is Reviewer A–Z, the tab's default.
        """
        ordering = MANAGE_SORTS.get(sort, MANAGE_SORTS[DEFAULT_MANAGE_SORT])
        return self.annotate(
            nameless=models.Case(
                models.When(user__first_name="", then=True),
                default=False,
                output_field=models.BooleanField(),
            )
        ).order_by(*ordering["ordering"])

    def newer_than(self, review):
        """These reviews ahead of ``review`` in Newest order: its place in that list."""
        return self.filter(
            models.Q(created_at__gt=review.created_at)
            | models.Q(created_at=review.created_at, pk__gt=review.pk)
        )

    def counted(self):
        """The counted set: live customer reviews.

        Every average, count, sort and filter uses only these. Staff
        reviews are shown, badged, but never counted, so the store's own
        people can't move a product's numbers.
        """
        return self.live().filter(by_staff=False)

    def listed_for(self, user):
        """The public list for ``user``: every live review but their own.

        Their own review lives in the "Your review" slot instead.
        """
        reviews = self.live().select_related("user")
        if user.is_authenticated:
            reviews = reviews.exclude(user=user)
        return reviews

    def sorted_by(self, sort):
        """These reviews in the list's ``sort`` order: a key of ``SORTS``.

        Equal ratings fall back to newest first. An unknown ``sort`` is
        Newest, so a hand-edited querystring still gets a list.
        """
        ordering = SORTS.get(sort, SORTS[DEFAULT_SORT])["ordering"]
        return self.order_by(*ordering)

    def rating_summary(self):
        """The counted set's size and average rating in stars."""
        numbers = self.counted().aggregate(
            count=models.Count("pk"), average=models.Avg("rating")
        )
        average = numbers["average"]
        return RatingSummary(
            count=numbers["count"],
            average=None if average is None else average / 2,
        )


class Review(models.Model):
    """One customer's review of one product: a rating, a headline and a comment.

    ``rating`` is stored as a whole number of half stars, 2–10, so
    averages, sorting and the check constraint stay exact; ``stars``
    halves it for display. Each user may hold one review per product,
    which is what turns a double-submit or a stale tab into "here is the
    review you already wrote" rather than a second row.

    ``by_staff`` is a snapshot of the author's ``is_staff`` on the day
    the review was first written. It is never recomputed, so a staff
    member who leaves keeps their staff badge on what they wrote, and a
    customer who joins the staff doesn't gain one.

    Deliberately not registered in the Django admin: the back office's
    Reviews tab is the one place reviews are moderated.
    """

    class Rating(models.IntegerChoices):
        ONE = 2, "1 star"
        ONE_HALF = 3, "1½ stars"
        TWO = 4, "2 stars"
        TWO_HALF = 5, "2½ stars"
        THREE = 6, "3 stars"
        THREE_HALF = 7, "3½ stars"
        FOUR = 8, "4 stars"
        FOUR_HALF = 9, "4½ stars"
        FIVE = 10, "5 stars"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="reviews"
    )
    rating = models.PositiveSmallIntegerField(choices=Rating.choices)
    headline = models.CharField(max_length=100, blank=True)
    # Blank only once its author deletes the text of a removed review;
    # ``clean`` holds a live review to the length rule.
    comment = models.TextField(blank=True)
    # default (not auto_now_add) so the seed can backdate reviews.
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    by_staff = models.BooleanField(default=False, editable=False)
    edited_at = models.DateTimeField(null=True, blank=True, editable=False)
    moderated_at = models.DateTimeField(null=True, blank=True, editable=False)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    removed_at = models.DateTimeField(null=True, blank=True, editable=False)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=2, rating__lte=10),
                name="review_rating_one_to_five_stars",
            ),
            models.UniqueConstraint(
                fields=["user", "product"], name="unique_review_per_user_product"
            ),
        ]

    def __str__(self):
        return f"{self.get_rating_display()} for {self.product.name}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.by_staff = self.user.is_staff
        return super().save(*args, **kwargs)

    def clean(self):
        """A live review's comment: 10 to 2,000 characters once trimmed."""
        self.comment = (self.comment or "").strip()
        self.headline = (self.headline or "").strip()
        if self.removed_at is not None:
            return
        length = len(self.comment)
        if length < COMMENT_MIN:
            raise ValidationError({"comment": "Write at least 10 characters."})
        if length > COMMENT_MAX:
            raise ValidationError(
                {"comment": f"Keep it to 2,000 characters (this has {length:,})."}
            )

    def remove(self, staff):
        """Take this review down: hidden everywhere and out of every number.

        The row stays, so it still holds the one-review-per-product
        constraint and its author can't simply post it again.
        """
        self.removed_at = timezone.now()
        self.removed_by = staff
        self.save(update_fields=["removed_at", "removed_by", "updated_at"])

    @property
    def can_restore(self):
        """Whether staff may put this review back: removed, with its text still there.

        Once its author has deleted the text there is nothing to show, and
        an empty review must never go back on the page.
        """
        return self.removed_at is not None and bool(self.comment)

    def restore(self):
        """Undo a removal: the review is back on the page and in every number.

        Does nothing unless ``can_restore``, so a stale Restore button
        can't bring back a review whose author has since deleted its text.
        """
        if not self.can_restore:
            return
        self.removed_at = None
        self.removed_by = None
        self.save(update_fields=["removed_at", "removed_by", "updated_at"])

    def delete_text(self):
        """The author's delete of a removed review: blank its words, keep the row.

        The row must stay, or its author could post the removed review
        again. Saved without ``full_clean``: the comment-length rule is for
        live reviews only.
        """
        self.headline = ""
        self.comment = ""
        self.save(update_fields=["headline", "comment", "updated_at"])

    @property
    def author_name(self):
        """How the public page names the author: "Dana C.".

        First name and last initial, or "A ThoughtTronix customer" for an
        account with no first name. Never the username, which is a
        sign-in identifier, and never the full name.
        """
        first = self.user.first_name.strip()
        if not first:
            return "A ThoughtTronix customer"
        last = self.user.last_name.strip()
        return f"{first} {last[0]}." if last else first

    @property
    def author_picture(self):
        """The author's profile picture, or the silhouette, labelled by ``author_name``.

        Not ``User.avatar_picture``: its alt text carries the full name,
        which the public page never shows.
        """
        return avatar_picture(self.user, f"Profile picture of {self.author_name}")

    @property
    def edit_label(self):
        """How the public page says the text has changed since it was posted.

        "Edited by ThoughtTronix staff" once staff have corrected it, which
        wins over the author's own "Edited" when both apply; blank if
        neither has. Never the staff member's name: the public page keeps
        them anonymous.
        """
        if self.moderated_at:
            return "Edited by ThoughtTronix staff"
        if self.edited_at:
            return "Edited"
        return ""

    @property
    def stars(self):
        """The rating in stars, 1.0 to 5.0."""
        return self.rating / 2

    @staticmethod
    def can_write(user, product):
        """Whether ``user`` has bought ``product``, and so may write a review of it.

        The same "counts as sold" rule as discount limits and the
        dashboard: an order line for the product on any order that isn't
        cancelled. Staff qualify on the same terms, and an unavailable
        product can still be reviewed by those who bought it. This guards
        creation only — a later cancellation leaves an existing review,
        and its author's rights over it, untouched.
        """
        if not user.is_authenticated:
            return False
        return (
            OrderItem.objects.filter(order__user=user, product=product)
            .exclude(order__status=Order.Status.CANCELLED)
            .exists()
        )
