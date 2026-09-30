from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.functional import cached_property

from .images import (
    PRODUCT_FOLDER,
    Picture,
    Slide,
    delete_files_on_commit,
    stored_picture,
    thumbnail_size,
)

# Categories with a dedicated placeholder illustration; anything else
# falls back to default.svg. Placeholders are static files chosen by
# category, shown whenever a product has no image of its own — or has
# one whose file has gone missing.
PLACEHOLDER_CATEGORIES = {
    "home-assistants",
    "neural-implants",
    "neural-wearables",
    "accessories",
    "defense",
    "legacy-products",
}

DEFAULT_PLACEHOLDER = "images/placeholders/default.svg"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("products:category", kwargs={"slug": self.slug})

    @property
    def placeholder_image(self):
        """Static path of the placeholder image shown for this category's products."""
        if self.slug in PLACEHOLDER_CATEGORIES:
            return f"images/placeholders/{self.slug}.svg"
        return DEFAULT_PLACEHOLDER


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def available(self):
        return self.filter(is_available=True)

    def search(self, text):
        """Simple icontains search over name and description."""
        return self.filter(
            models.Q(name__icontains=text) | models.Q(description__icontains=text)
        )


class Product(models.Model):
    """A catalog product.

    The image fields are written only by ``products/images.py`` — they
    are ``editable=False``, so no form, and not the Django admin, offers
    a second way in. Templates never read them either: they ask for
    ``card_image``, ``display_image`` or ``gallery``, which check the
    file is really in storage and fall back to the category placeholder.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")

    # The main image: a display WebP and its thumbnail, sized by the pipeline.
    image = models.ImageField(
        "main image", upload_to=PRODUCT_FOLDER, blank=True, editable=False
    )
    image_thumbnail = models.ImageField(
        upload_to=PRODUCT_FOLDER, blank=True, editable=False
    )
    image_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    image_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    image_alt = models.CharField(
        "main image alt text", max_length=200, blank=True, editable=False
    )

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("products:detail", kwargs={"slug": self.slug})

    @property
    def image_alt_text(self):
        """The main image's alt text, falling back to the product's name."""
        return self.image_alt or self.name

    @property
    def placeholder(self):
        """This product's category placeholder, as a ``Picture``."""
        return Picture.placeholder(self.category.placeholder_image, self.name)

    @cached_property
    def card_image(self):
        """What a card, cart line or list row shows: the thumbnail, or the placeholder."""
        return (
            stored_picture(
                self.image_thumbnail,
                *thumbnail_size(self.image_width, self.image_height),
                self.image_alt_text,
            )
            or self.placeholder
        )

    @cached_property
    def display_image(self):
        """What the product page shows: the full display file, or the placeholder."""
        return (
            stored_picture(
                self.image, self.image_width, self.image_height, self.image_alt_text
            )
            or self.placeholder
        )

    @property
    def has_image(self):
        """Whether the store shows a real image for this product, not the placeholder."""
        return not self.card_image.is_placeholder

    @cached_property
    def gallery(self):
        """The product page's slides: the main image first, then each extra.

        An extra whose files are missing is left out rather than shown
        as a placeholder in the middle of the carousel. Extras without
        their own alt text are described by position, e.g. "Seraphine —
        image 2 of 3".
        """
        extras = list(self.extra_images.all())
        total = 1 + len(extras)
        slides = [Slide(self.display_image, self.card_image)]
        for position, extra in enumerate(extras, start=2):
            alt = extra.alt_text or f"{self.name} — image {position} of {total}"
            slide = extra.slide(alt)
            if slide is not None:
                slides.append(slide)
        return slides


class ProductImage(models.Model):
    """One extra image in a product's gallery — never the main image.

    Extras are shown after ``Product.image`` on the product page and
    never replace it; removing the main image leaves the placeholder,
    not the first extra. ``products.images.MAX_EXTRAS`` caps how many
    one product can have.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="extra_images"
    )
    image = models.ImageField(upload_to=PRODUCT_FOLDER, editable=False)
    thumbnail = models.ImageField(upload_to=PRODUCT_FOLDER, editable=False)
    width = models.PositiveIntegerField(editable=False)
    height = models.PositiveIntegerField(editable=False)
    alt_text = models.CharField(max_length=200, blank=True, editable=False)
    sort_order = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return f"Extra image for {self.product}"

    def slide(self, alt):
        """This extra as a gallery ``Slide`` — or ``None`` if either file is missing."""
        display = stored_picture(self.image, self.width, self.height, alt)
        thumbnail = stored_picture(
            self.thumbnail, *thumbnail_size(self.width, self.height), alt
        )
        if display is None or thumbnail is None:
            return None
        return Slide(display, thumbnail)

    @cached_property
    def preview(self):
        """The back office's view of this extra: its thumbnail, or the placeholder."""
        alt = self.alt_text or f"Extra image for {self.product.name}"
        return (
            stored_picture(
                self.thumbnail, *thumbnail_size(self.width, self.height), alt
            )
            or self.product.placeholder
        )


@receiver(post_delete, sender=Product)
def delete_product_image_files(sender, instance, **kwargs):
    """A deleted product takes its main image files with it (on commit)."""
    delete_files_on_commit(instance.image.name, instance.image_thumbnail.name)


@receiver(post_delete, sender=ProductImage)
def delete_extra_image_files(sender, instance, **kwargs):
    """A deleted extra — directly or with its product — takes its files with it."""
    delete_files_on_commit(instance.image.name, instance.thumbnail.name)
