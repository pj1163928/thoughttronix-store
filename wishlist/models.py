from django.conf import settings
from django.db import models
from django.utils import timezone

from products.models import Product


class Wishlist(models.Model):
    """A customer's wishlist — one per user, created lazily on first touch.

    Private by construction. Nothing names a wishlist from outside: there
    is no URL with a wishlist's pk or its owner's username in it, no
    back-office page, no dashboard figure, and deliberately no admin
    registration. Every lookup starts from the signed-in user
    (``WishlistItem.objects.of``), so the only wishlist a request can
    ever read or change is its own.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist",
    )

    def __str__(self):
        return f"Wishlist for {self.user.username}"

    @classmethod
    def for_user(cls, user):
        """Return the user's wishlist, creating it on first touch."""
        wishlist, _ = cls.objects.get_or_create(user=user)
        return wishlist

    def add(self, product):
        """Save a product. Saving one that is already here changes nothing."""
        item, _ = self.items.get_or_create(product=product)
        return item

    def remove(self, product):
        """Drop a product. Dropping one that isn't here changes nothing."""
        self.items.filter(product=product).delete()


class WishlistItemQuerySet(models.QuerySet):
    def of(self, user):
        """``user``'s saved products — the one way into wishlist rows.

        Anonymous visitors have no wishlist, so they get an empty set
        rather than an error, and a template can ask on any page.
        """
        if not user.is_authenticated:
            return self.none()
        return self.filter(wishlist__user=user)

    def holds(self, product):
        """Whether ``product`` is among these rows — the product page's state."""
        return self.filter(product=product).exists()

    def with_products(self):
        """Load each line's product and category — what a row and its placeholder read."""
        return self.select_related("product__category")


class WishlistItem(models.Model):
    """One saved product; the wishlist–product pair is unique.

    Unlike a cart line there is no quantity: a product is on the list or
    it isn't, which is what makes add and remove safe to repeat. Any
    product can be saved, an unavailable one included — wanting something
    you can't buy yet is what a wishlist is for. Adding a product to the
    cart leaves it here; only the customer takes it off.
    """

    wishlist = models.ForeignKey(
        Wishlist, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    added_at = models.DateTimeField(default=timezone.now)

    objects = WishlistItemQuerySet.as_manager()

    class Meta:
        ordering = ["-added_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["wishlist", "product"], name="unique_wishlist_product"
            )
        ]

    def __str__(self):
        return self.product.name
