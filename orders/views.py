"""Cart and checkout views — thin per the architecture convention.

The three HTMX interactions of the core live here: add-to-cart, quantity
change, and line removal. Each renders a partial (never ``base.html``);
the responses carry the navbar badge as an out-of-band swap via the
``oob_badge`` context flag. Checkout is conventional full-page work:
validate the form, hand everything to ``place_order``.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from accounts.mixins import StaffRequiredMixin
from products.models import Product

from .forms import ApplyDiscountForm, CheckoutForm, DiscountCodeForm, OrderStatusForm
from .models import Cart, CartItem, DiscountCode, Order
from .services import place_order


class CartView(LoginRequiredMixin, TemplateView):
    """The customer's cart page."""

    template_name = "orders/cart.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cart = Cart.for_user(self.request.user)
        context["cart"] = cart
        context["discount_form"] = ApplyDiscountForm(cart=cart)
        return context


class AddToCartView(LoginRequiredMixin, View):
    """HTMX: add a product; the button swaps and the badge updates OOB.

    Looks the product up through ``available()``, so adding an
    unavailable product 404s — the same not-for-sale semantics as the
    public catalog.
    """

    def post(self, request, pk):
        product = get_object_or_404(Product.objects.available(), pk=pk)
        item = Cart.for_user(request.user).add(product)
        return render(
            request,
            "orders/partials/_add_button.html",
            {"product": product, "in_cart": item.quantity, "oob_badge": True},
        )


class CartItemActionView(LoginRequiredMixin, View):
    """Base for HTMX line mutations: act, then re-render the cart contents.

    Items are always fetched through the owner's cart — never by bare pk.
    """

    def post(self, request, pk):
        item = get_object_or_404(CartItem, pk=pk, cart__user=request.user)
        self.act(item)
        return render(
            request,
            "orders/partials/_cart_contents.html",
            {
                "cart": item.cart,
                "discount_form": ApplyDiscountForm(cart=item.cart),
                "oob_badge": True,
            },
        )

    def act(self, item):
        raise NotImplementedError


class IncrementCartItemView(CartItemActionView):
    def act(self, item):
        item.increment()


class DecrementCartItemView(CartItemActionView):
    def act(self, item):
        item.decrement()


class RemoveCartItemView(CartItemActionView):
    def act(self, item):
        item.delete()


class ApplyDiscountView(LoginRequiredMixin, View):
    """HTMX: attach a typed code to the cart, or re-render with its reason.

    A rejected code leaves the cart untouched and comes back as a field
    error inside the same swapped partial — there is no redirect and no
    page to break. A successful apply clears the box.
    """

    def post(self, request):
        cart = Cart.for_user(request.user)
        form = ApplyDiscountForm(request.POST, cart=cart)
        if form.is_valid():
            cart.discount_code = form.cleaned_data["code"]
            cart.save(update_fields=["discount_code"])
            form = ApplyDiscountForm(cart=cart)
        return render(
            request,
            "orders/partials/_cart_contents.html",
            {"cart": cart, "discount_form": form},
        )


class RemoveDiscountView(LoginRequiredMixin, View):
    """HTMX: detach whatever code the cart is carrying."""

    def post(self, request):
        cart = Cart.for_user(request.user)
        cart.discount_code = None
        cart.save(update_fields=["discount_code"])
        return render(
            request,
            "orders/partials/_cart_contents.html",
            {"cart": cart, "discount_form": ApplyDiscountForm(cart=cart)},
        )


class CheckoutView(LoginRequiredMixin, FormView):
    """The single checkout page: validate the form, hand off to the service.

    A cart that can't check out (empty, holding a product that has since
    become unavailable, or carrying a code that has since expired) is
    sent back to the cart page to be fixed, before any card details are
    typed — ``place_order`` enforces the same rules transactionally as
    the backstop, and ``form_valid`` turns that backstop into a message
    rather than a server error.
    """

    template_name = "orders/checkout.html"
    form_class = CheckoutForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        cart = Cart.for_user(request.user)
        if not cart.items.exists():
            messages.info(request, "Your cart is empty — add something first.")
            return redirect("orders:cart")
        unavailable = [
            line.product.name for line in cart.lines() if not line.product.is_available
        ]
        if unavailable:
            messages.warning(
                request,
                f"No longer available: {', '.join(unavailable)}. "
                "Remove them from the cart to check out.",
            )
            return redirect("orders:cart")
        code = cart.discount_code
        if code is not None and not code.is_live():
            cart.discount_code = None
            cart.save(update_fields=["discount_code"])
            messages.warning(
                request,
                f"{code.code} is no longer valid, so it's been removed from your cart.",
            )
            return redirect("orders:cart")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cart"] = Cart.for_user(self.request.user)
        return context

    def form_valid(self, form):
        cart = Cart.for_user(self.request.user)
        try:
            order = place_order(cart, self.request.user, form.cleaned_data)
        except ValueError as problem:
            # The dispatch checks make this a race, not a routine path —
            # but a race at the till still deserves a sentence, not a 500.
            messages.warning(self.request, str(problem))
            return redirect("orders:cart")
        messages.success(self.request, f"Order {order.number} placed. Thank you!")
        return redirect(reverse("orders:confirmation", kwargs={"pk": order.pk}))


class OwnOrdersMixin(LoginRequiredMixin):
    """Orders are always fetched through the owner — never by bare pk."""

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)


class OrderConfirmationView(OwnOrdersMixin, DetailView):
    template_name = "orders/confirmation.html"
    context_object_name = "order"


class OrderHistoryView(OwnOrdersMixin, ListView):
    """The customer's orders, most recent first per the model ordering."""

    template_name = "orders/order_history.html"
    context_object_name = "orders"


class OrderDetailView(OwnOrdersMixin, DetailView):
    template_name = "orders/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("items")


# --- The back office --------------------------------------------------------
#
# Staff-only order oversight: every customer's orders, filterable by
# status, with the status dropdown on the detail page. The ``section``
# context entry drives the active tab in the staff shell.


class ManageOrderListView(StaffRequiredMixin, ListView):
    """All orders, most recent first, filterable via ``?status=``."""

    template_name = "orders/manage_orders.html"
    context_object_name = "orders"
    paginate_by = 20
    extra_context = {"section": "orders"}

    def get_queryset(self):
        orders = Order.objects.select_related("user")
        status = self.request.GET.get("status", "")
        if status in Order.Status.values:
            orders = orders.filter(status=status)
        return orders

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = Order.Status.choices
        context["active_status"] = self.request.GET.get("status", "")
        return context


class ManageOrderDetailView(StaffRequiredMixin, DetailView):
    """Any order's detail, with the status form alongside."""

    template_name = "orders/manage_order_detail.html"
    context_object_name = "order"
    queryset = Order.objects.select_related("user").prefetch_related("items")
    extra_context = {"section": "orders"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_form"] = OrderStatusForm(instance=self.object)
        return context


class UpdateOrderStatusView(StaffRequiredMixin, View):
    """POST-only: set an order's status from the back-office dropdown."""

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"{order.number} is now {order.get_status_display().lower()}.",
            )
        else:
            messages.error(request, "That isn't a status an order can have.")
        return redirect("orders:manage_order_detail", pk=order.pk)


class ManageDiscountListView(StaffRequiredMixin, ListView):
    """Every code ever created, live or not — codes are retired, not deleted."""

    template_name = "orders/manage_discounts.html"
    context_object_name = "codes"
    extra_context = {"section": "discounts"}

    def get_queryset(self):
        return DiscountCode.objects.select_related("product")


class ManageDiscountCreateView(StaffRequiredMixin, SuccessMessageMixin, CreateView):
    model = DiscountCode
    form_class = DiscountCodeForm
    template_name = "orders/manage_discount_form.html"
    success_url = reverse_lazy("orders:manage_discounts")
    success_message = "%(code)s created."
    extra_context = {"section": "discounts"}


class ManageDiscountUpdateView(StaffRequiredMixin, SuccessMessageMixin, UpdateView):
    model = DiscountCode
    form_class = DiscountCodeForm
    template_name = "orders/manage_discount_form.html"
    success_url = reverse_lazy("orders:manage_discounts")
    success_message = "%(code)s saved."
    extra_context = {"section": "discounts"}


class ToggleDiscountActiveView(StaffRequiredMixin, View):
    """POST-only: retire a code, or put a retired one back into service.

    Retiring is its own action rather than a checkbox on the edit form,
    so a promotion's terms and its availability can never be changed by
    the same slip of the hand. It touches nothing but ``is_active`` —
    orders that already used the code keep their own snapshot.
    """

    def post(self, request, pk):
        code = get_object_or_404(DiscountCode, pk=pk)
        code.is_active = not code.is_active
        code.save(update_fields=["is_active"])
        if code.is_active:
            messages.success(request, f"{code.code} is live again.")
        else:
            messages.success(
                request, f"{code.code} is retired. Past orders are unchanged."
            )
        return redirect("orders:manage_discounts")
