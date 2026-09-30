from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from accounts.mixins import StaffRequiredMixin

from . import images
from .forms import (
    CategoryForm,
    ExtraImageForm,
    ImageUploadForm,
    ProductForm,
    TagForm,
)
from .models import Category, Product, Tag

# Said when storage itself fails mid-upload. The pipeline has already
# removed whatever it wrote, so "nothing changed" is the literal truth.
STORAGE_FAILED = (
    "The image couldn't be saved, so nothing was changed. Please try again."
)


class CatalogView(ListView):
    """The public product catalog: search, tag and category filters, pagination.

    Filters arrive as querystring parameters (``q``, ``tag``, ``category``)
    and compose freely.
    """

    template_name = "products/catalog.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        products = Product.objects.select_related("category").prefetch_related("tags")
        query = self.request.GET.get("q", "").strip()
        if query:
            products = products.search(query)
        tag_slug = self.request.GET.get("tag", "")
        if tag_slug:
            products = products.filter(tags__slug=tag_slug)
        category_slug = self.request.GET.get("category", "")
        if category_slug:
            products = products.filter(category__slug=category_slug)
        return products

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        context["active_tag"] = self.request.GET.get("tag", "")
        context["categories"] = Category.objects.all()
        context["tags"] = Tag.objects.all()
        return context


class CategoryView(CatalogView):
    """Browse a single category — the catalog scoped to one shelf."""

    def get_queryset(self):
        self.category = get_object_or_404(Category, slug=self.kwargs["slug"])
        return super().get_queryset().filter(category=self.category)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category"] = self.category
        return context


class ProductDetailView(DetailView):
    """A single product at its slug URL."""

    template_name = "products/detail.html"
    context_object_name = "product"
    queryset = Product.objects.select_related("category").prefetch_related(
        "tags", "extra_images"
    )


# --- The back office --------------------------------------------------------
#
# Staff-only catalog management. Every view gates on StaffRequiredMixin;
# URLs use pks per the URL conventions. The ``section`` context entry
# drives the active tab in the staff shell (backoffice/base.html).


class ManageProductListView(StaffRequiredMixin, ListView):
    """The back-office product list — every product, available or not."""

    template_name = "products/manage_products.html"
    context_object_name = "products"
    extra_context = {"section": "products"}

    def get_queryset(self):
        return Product.objects.select_related("category")


class ManageProductCreateView(StaffRequiredMixin, SuccessMessageMixin, CreateView):
    """Create a product, then go straight to its Images page to add a picture."""

    model = Product
    form_class = ProductForm
    template_name = "products/manage_product_form.html"
    success_message = "“%(name)s” created. Now give it an image."
    extra_context = {"section": "products"}

    def get_success_url(self):
        return reverse("products:manage_product_images", kwargs={"pk": self.object.pk})


class ManageProductUpdateView(StaffRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "products/manage_product_form.html"
    success_url = reverse_lazy("products:manage_products")
    success_message = "“%(name)s” saved."
    extra_context = {"section": "products"}


class ManageProductDeleteView(StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    model = Product
    context_object_name = "product"
    template_name = "products/manage_product_confirm_delete.html"
    success_url = reverse_lazy("products:manage_products")
    success_message = "Product deleted."
    extra_context = {"section": "products"}


class ProductImagesMixin(StaffRequiredMixin):
    """Shared by every Images-page view: the product, and the way back to its page."""

    extra_context = {"section": "products"}

    @cached_property
    def product(self):
        return get_object_or_404(
            Product.objects.select_related("category").prefetch_related("extra_images"),
            pk=self.kwargs["pk"],
        )

    def back_to_images(self):
        return redirect("products:manage_product_images", pk=self.product.pk)


class ManageProductImagesView(ProductImagesMixin, TemplateView):
    """A product's Images page: its main image, its extras, and every action on them.

    Separate from the product form on purpose. An upload shares its POST
    with nothing else, so an unrelated field failing validation can never
    make an employee lose — and re-pick — a file they already chose.
    """

    template_name = "products/manage_product_images.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extras = list(self.product.extra_images.all())
        context.setdefault("main_form", ImageUploadForm(prefix="main"))
        context.setdefault(
            "extra_form", ExtraImageForm(product=self.product, prefix="extra")
        )
        context["product"] = self.product
        context["extras"] = extras
        context["max_extras"] = images.MAX_EXTRAS
        context["can_add_extra"] = len(extras) < images.MAX_EXTRAS
        if not context["can_add_extra"]:
            context["extras_limit"] = images.extras_limit_message(self.product)
        return context


class UploadMainImageView(ManageProductImagesView):
    """POST-only: add or replace the main image; a rejected file re-renders the page."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        form = ImageUploadForm(request.POST, request.FILES, prefix="main")
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(main_form=form))
        replacing = self.product.has_image
        try:
            images.set_main_image(
                self.product, form.cleaned_data["image"], form.cleaned_data["alt_text"]
            )
        except OSError:
            messages.error(request, STORAGE_FAILED)
            return self.back_to_images()
        verb = "replaced" if replacing else "added"
        messages.success(request, f"Main image {verb} for “{self.product.name}”.")
        return self.back_to_images()


class AddExtraImageView(ManageProductImagesView):
    """POST-only: append an extra image; a rejected file re-renders the page."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        form = ExtraImageForm(
            request.POST, request.FILES, product=self.product, prefix="extra"
        )
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(extra_form=form))
        try:
            images.add_extra_image(
                self.product, form.cleaned_data["image"], form.cleaned_data["alt_text"]
            )
        except ValidationError as problem:
            # Another tab filled the last slot between the form and here.
            messages.error(request, problem.messages[0])
            return self.back_to_images()
        except OSError:
            messages.error(request, STORAGE_FAILED)
            return self.back_to_images()
        messages.success(request, f"Extra image added to “{self.product.name}”.")
        return self.back_to_images()


class RemoveMainImageView(ProductImagesMixin, TemplateView):
    """GET asks for confirmation; POST removes the main image, leaving the placeholder."""

    template_name = "products/manage_product_image_confirm_remove.html"

    def get(self, request, *args, **kwargs):
        if not self.product.image:
            messages.info(request, f"“{self.product.name}” has no main image.")
            return self.back_to_images()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product"] = self.product
        context["picture"] = self.product.card_image
        context["what"] = "the main image"
        context["consequence"] = (
            f"The store will show the {self.product.category.name} placeholder "
            "instead. Extra images are not affected."
        )
        return context

    def post(self, request, *args, **kwargs):
        if images.remove_main_image(self.product):
            messages.success(
                request,
                f"Main image removed from “{self.product.name}” — "
                "it now shows the placeholder.",
            )
        return self.back_to_images()


class RemoveExtraImageView(ProductImagesMixin, TemplateView):
    """GET asks for confirmation; POST removes one extra image."""

    template_name = "products/manage_product_image_confirm_remove.html"

    @cached_property
    def extra(self):
        return get_object_or_404(self.product.extra_images, pk=self.kwargs["extra_pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product"] = self.product
        context["picture"] = self.extra.preview
        context["what"] = "this extra image"
        context["consequence"] = "The main image is not affected."
        return context

    def post(self, request, *args, **kwargs):
        images.remove_extra_image(self.extra)
        messages.success(request, f"Extra image removed from “{self.product.name}”.")
        return self.back_to_images()


class MoveExtraImageView(ProductImagesMixin, View):
    """POST-only: move an extra one place earlier (``up``) or later (``down``)."""

    def post(self, request, *args, **kwargs):
        extra = get_object_or_404(self.product.extra_images, pk=self.kwargs["extra_pk"])
        direction = request.POST.get("direction")
        if direction in ("up", "down"):
            images.move_extra(extra, direction)
        return self.back_to_images()


class ManageCatalogView(StaffRequiredMixin, TemplateView):
    """Categories and tags on one management page."""

    template_name = "products/manage_catalog.html"
    extra_context = {"section": "catalog"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.annotate(
            product_count=Count("products")
        )
        context["tags"] = Tag.objects.annotate(product_count=Count("products"))
        return context


class ManageCategoryCreateView(StaffRequiredMixin, SuccessMessageMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "products/manage_catalog_form.html"
    success_url = reverse_lazy("products:manage_catalog")
    success_message = "“%(name)s” created."
    extra_context = {"section": "catalog", "kind": "category"}


class ManageCategoryUpdateView(StaffRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "products/manage_catalog_form.html"
    success_url = reverse_lazy("products:manage_catalog")
    success_message = "“%(name)s” saved."
    extra_context = {"section": "catalog", "kind": "category"}


class ManageTagCreateView(StaffRequiredMixin, SuccessMessageMixin, CreateView):
    model = Tag
    form_class = TagForm
    template_name = "products/manage_catalog_form.html"
    success_url = reverse_lazy("products:manage_catalog")
    success_message = "“%(name)s” created."
    extra_context = {"section": "catalog", "kind": "tag"}


class ManageTagUpdateView(StaffRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Tag
    form_class = TagForm
    template_name = "products/manage_catalog_form.html"
    success_url = reverse_lazy("products:manage_catalog")
    success_message = "“%(name)s” saved."
    extra_context = {"section": "catalog", "kind": "tag"}
