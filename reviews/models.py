from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product

COMMENT_MIN = 10
COMMENT_MAX = 2000


class ReviewQuerySet(models.QuerySet):
    def by(self, user):
        """``user``'s own reviews; none for an anonymous visitor."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(user=user)


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
