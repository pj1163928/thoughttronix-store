"""Back-office forms for the catalog models.

ModelForms inherit the models' own rules (name required, slug unique);
the explicit ``price`` declaration adds the one rule the model doesn't
carry — the price must be positive. Widgets get their DaisyUI classes
in one shared ``__init__`` loop, as on ``CheckoutForm``.
"""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .images import MAX_EXTRAS, extras_limit_message, validate_image
from .models import Category, Product, Tag


class StyledModelForm(forms.ModelForm):
    """Base form that dresses every widget in DaisyUI classes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "toggle toggle-primary"
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                # The boxes are styled individually; the scrolling frame
                # around them belongs to the template, not the widget.
                widget.attrs["class"] = "checkbox checkbox-sm checkbox-primary"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "textarea w-full"
                widget.attrs.setdefault("rows", 6)
            elif isinstance(widget, forms.SelectMultiple):
                widget.attrs["class"] = "select h-auto w-full"
                widget.attrs.setdefault("size", 8)
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "select w-full"
            else:
                widget.attrs["class"] = "input w-full"


class ProductForm(StyledModelForm):
    price = forms.DecimalField(
        label="Price (USD)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "slug",
            "tagline",
            "description",
            "price",
            "category",
            "tags",
            "is_available",
            "is_featured",
        ]


class CategoryForm(StyledModelForm):
    class Meta:
        model = Category
        fields = ["name", "slug"]


class TagForm(StyledModelForm):
    class Meta:
        model = Tag
        fields = ["name", "slug"]


class ImageUploadForm(forms.Form):
    """One image upload for the Images page: the file and optional alt text.

    A plain ``FileField`` rather than Django's ``ImageField``, whose own
    Pillow check would answer first with a generic "upload a valid
    image". ``clean_image`` hands the file to ``validate_image`` instead,
    so every rejection says what was actually wrong, and a valid upload
    arrives in ``cleaned_data`` already resized — a ``PreparedImage``
    the view passes straight to the pipeline.
    """

    image = forms.FileField(
        label="Image file",
        help_text="JPEG, PNG or WebP · at least 600 pixels on each side · up to 10 MB",
    )
    alt_text = forms.CharField(
        label="Alt text (optional)",
        max_length=200,
        required=False,
        help_text="Describe what the picture shows, for customers using screen "
        "readers. Left blank, the product's name is used.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].widget.attrs.update(
            {"class": "file-input w-full", "accept": "image/jpeg,image/png,image/webp"}
        )
        self.fields["alt_text"].widget.attrs["class"] = "input w-full"

    def clean_image(self):
        return validate_image(self.cleaned_data["image"])


class ExtraImageForm(ImageUploadForm):
    """An extra image upload, refused up front once the product has the most allowed."""

    def __init__(self, *args, product, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)

    def clean_image(self):
        if self.product.extra_images.count() >= MAX_EXTRAS:
            raise ValidationError(extras_limit_message(self.product))
        return super().clean_image()
