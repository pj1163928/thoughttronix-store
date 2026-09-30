"""Back-office forms for the catalog models.

ModelForms inherit the models' own rules (name required, slug unique);
the explicit ``price`` declaration adds the one rule the model doesn't
carry — the price must be positive. Many-to-many choices (tags, a
discount's products) render as checkbox lists, never multi-selects. Widgets get their DaisyUI classes
in one shared ``__init__`` loop, as on ``CheckoutForm``.
"""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from . import images
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


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A file field that accepts several files at once; cleans to a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, list | tuple) else [data]
        clean_one = super().clean
        return [clean_one(file, initial) for file in files]


class ProductForm(StyledModelForm):
    """The product's details, plus its images and the choice of main image.

    The slug is not asked for: ``Product.save`` makes one from the name.

    Images normally arrive before the form is submitted: the Upload
    button sends them over HTMX to be validated and held, and they come
    back as previews with a "main image" radio button each (see
    ``_image_picker.html``). ``upload`` is the backstop for files still in
    the input when Save is pressed — each is checked by ``validate_image``
    on its own, and the ones that passed land in ``accepted_images`` even
    when the form as a whole is invalid, ready for the view to hold.

    ``held_count`` is how many images are already held; they count
    against the product's room. ``main_image`` is the chosen radio value
    (see ``products.images.attach_uploads``). The two image fields are
    drawn by the picker, not the field loop — see ``detail_fields``.
    """

    IMAGE_FIELDS = ("upload", "main_image")

    price = forms.DecimalField(
        label="Price (USD)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    upload = MultipleFileField(label="Images", required=False)
    main_image = forms.CharField(required=False, max_length=64)

    class Meta:
        model = Product
        fields = [
            "name",
            "tagline",
            "description",
            "price",
            "category",
            "tags",
            "is_available",
            "is_featured",
        ]
        widgets = {"tags": forms.CheckboxSelectMultiple}

    def __init__(self, *args, held_count=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.held_count = held_count
        self.accepted_images = []

    def detail_fields(self):
        """Every field but the two the image picker draws itself."""
        return [field for field in self if field.name not in self.IMAGE_FIELDS]

    def clean_upload(self):
        files = self.cleaned_data["upload"]
        room = images.image_room(self.instance) - self.held_count
        if len(files) > room:
            raise ValidationError(images.too_many_message(len(files), room))
        problems = []
        for file in files:
            try:
                self.accepted_images.append(validate_image(file))
            except ValidationError as problem:
                problems.extend(problem.messages)
        if problems:
            raise ValidationError(problems)
        return self.accepted_images


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
