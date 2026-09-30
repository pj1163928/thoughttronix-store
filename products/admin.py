from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Category, Product, ProductImage, Tag


def image_preview(picture):
    """A small read-only ``<img>`` for the admin, from a resolved ``Picture``.

    The image fields themselves are ``editable=False``, so the admin can
    show images but never accept one — every upload goes through the
    back office's Images page and its validator.
    """
    label = " (placeholder)" if picture.is_placeholder else ""
    return format_html(
        '<img src="{}" alt="{}" width="96" style="height:auto;border-radius:4px">'
        "<br><small>{}{}</small>",
        picture.url,
        picture.alt,
        picture.alt,
        label,
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    """Extras, shown read-only; they are managed on the back office's Images page."""

    model = ProductImage
    extra = 0
    fields = ("preview", "alt_text", "sort_order")
    readonly_fields = ("preview", "alt_text", "sort_order")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Image")
    def preview(self, extra):
        return image_preview(extra.preview)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "is_available", "is_featured")
    list_filter = ("category", "is_available", "is_featured", "tags")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("main_image",)
    inlines = [ProductImageInline]

    @admin.display(description="Main image")
    def main_image(self, product):
        if product.pk is None:
            return "Save the product first, then add images in the back office."
        return format_html(
            '{}<p><a href="{}">Manage images in the back office →</a></p>',
            image_preview(product.card_image),
            reverse("products:manage_product_images", kwargs={"pk": product.pk}),
        )
