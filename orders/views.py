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
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
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
from accounts.models import ADDRESS_FIELDS, Address
from products.models import Product

from .forms import ApplyDiscountForm, CheckoutForm, DiscountCodeForm, OrderStatusForm
from .models import Cart, CartItem, DiscountCode, Order
from .services import place_order


def address_initial(address, prefix):
    """A saved address as ``CheckoutForm`` initial data for one section.

    Checkout's field names are the address's own behind a ``shipping_``
    or ``billing_`` prefix, so the whole mapping is a prefix and a
    ``getattr`` — the reason ``Address.zip`` is spelled that way.
    """
    return {f"{prefix}{field}": getattr(address, field) for field in ADDRESS_FIELDS}


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
        problem = cart.discount_problem()
        if problem:
            cart.discount_code = None
            cart.save(update_fields=["discount_code"])
            messages.warning(request, f"{problem} It's been removed from your cart.")
            return redirect("orders:cart")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        """Pre-fill each section from the customer's default address.

        The invariant the address book maintains — a customer with any
        addresses has exactly one default per role — is what makes this
        a lookup rather than a guess. With an empty book there is
        nothing to fill, so the save-checkboxes are ticked instead: the
        customer is typing an address they have never saved, and the
        offer to keep it is the only moment asking is cheap.
        """
        initial = super().get_initial()
        addresses = list(self.request.user.addresses.all())
        if not addresses:
            initial["save_shipping_address"] = True
            initial["save_billing_address"] = True
            return initial

        for prefix, flag in (
            ("shipping_", "is_default_shipping"),
            ("billing_", "is_default_billing"),
        ):
            default = next((a for a in addresses if getattr(a, flag)), None)
            if default is not None:
                initial |= address_initial(default, prefix)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cart"] = Cart.for_user(self.request.user)
        context["addresses"] = self.request.user.addresses.all()
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

        # Deliberately after the order and outside its transaction:
        # remembering an address must never be able to undo a purchase.
        for prefix in ("shipping_", "billing_"):
            if form.cleaned_data.get(f"save_{prefix}address"):
                Address.objects.remember(self.request.user, form.cleaned_data, prefix)

        messages.success(self.request, f"Order {order.number} placed. Thank you!")
        return redirect(reverse("orders:confirmation", kwargs={"pk": order.pk}))


class CheckoutAddressFieldsView(LoginRequiredMixin, View):
    """HTMX: re-render one checkout address fieldset from a saved address.

    The picker is a typist and nothing more. It swaps values into the
    fields the customer would otherwise have typed, which is why
    ``CheckoutForm`` needs no saved-address field of its own and
    ``place_order`` needs no changes at all — what arrives at the till
    is the same POST either way. Editing a swapped-in value changes that
    order only; the saved address is never read back at submit time.

    The empty choice clears the fieldset, so "enter a new address" is
    the picker's own job rather than a separate control. Addresses are
    fetched through ``request.user``, never by bare pk.

    The picker's ``<select name="address">`` is what htmx sends here as
    the query string. It sits inside the checkout form, so a submitted
    checkout carries a stray ``address`` key — harmless, because
    ``CheckoutForm`` has no such field and ignores it.
    """

    def get(self, request, role):
        if role not in ("shipping", "billing"):
            raise Http404("No such address section.")

        chosen = request.GET.get("address", "")
        prefix = f"{role}_"
        initial = {}
        if chosen.isdigit():
            address = get_object_or_404(request.user.addresses, pk=chosen)
            initial = address_initial(address, prefix)

        form = CheckoutForm(initial=initial)
        fields = getattr(form, f"{role}_fields")()
        return render(
            request, "orders/partials/_address_fields.html", {"fields": fields}
        )


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
    """Codes grouped by whether they still have a future.

    Codes are retired, never deleted, so this page would otherwise
    accumulate every promotion the store has ever run. ``?show=`` picks
    a bucket the same way ``?status=`` does on the orders list; active
    is the default, so landing here shows only what is still in play.
    """

    template_name = "orders/manage_discounts.html"
    context_object_name = "codes"
    extra_context = {"section": "discounts"}
    buckets = ["active", "inactive", "all"]

    @property
    def show(self):
        requested = self.request.GET.get("show", "")
        return requested if requested in self.buckets else "active"

    def get_queryset(self):
        codes = DiscountCode.objects.with_usage().prefetch_related("products")
        if self.show == "all":
            return codes
        if self.show == "inactive":
            return codes.inactive()
        return codes.active()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show"] = self.show
        context["buckets"] = self.buckets
        # Tells the empty state whether this bucket is empty or the store
        # has simply never had a code — two very different pages.
        context["any_codes"] = DiscountCode.objects.exists()
        return context


class ManageDiscountCreateView(StaffRequiredMixin, SuccessMessageMixin, CreateView):
    """Create a code — or, if that name is taken, offer the one in the way.

    The form is told to record a name clash rather than reject it, so a
    duplicate arrives here as a valid form carrying ``duplicate_of``.
    Everything the admin typed is handed to the confirmation screen as
    hidden fields, which keeps the whole exchange stateless: no session
    to expire, nothing to clean up, and two browser tabs cannot confuse
    each other.
    """

    model = DiscountCode
    form_class = DiscountCodeForm
    template_name = "orders/manage_discount_form.html"
    success_url = reverse_lazy("orders:manage_discounts")
    success_message = "%(code)s created."
    extra_context = {"section": "discounts"}

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"detect_duplicates": True}

    def form_valid(self, form):
        if form.duplicate_of is not None:
            return self.render_duplicate(form)
        return super().form_valid(form)

    def render_duplicate(self, form):
        """Answer a name clash with the existing code and what can be done about it."""
        return render(
            self.request,
            "orders/manage_discount_reinstate.html",
            {
                "section": "discounts",
                "existing": form.duplicate_of,
                "form": form,
                "typed_label": self.typed_label(form),
                "submitted": self.submitted_fields(),
            },
        )

    @staticmethod
    def typed_label(form):
        """The typed terms in the same words as ``DiscountCode.label``.

        Built from ``cleaned_data`` rather than the unsaved instance:
        ``target_label`` reads the products relation, which an object
        with no primary key cannot answer for.
        """
        code = form.instance
        if form.cleaned_data.get("applies_to") == DiscountCode.Scope.ALL:
            return f"{code.amount_label} off your order"
        names = [product.name for product in form.cleaned_data.get("products", [])]
        return f"{code.amount_label} off {', '.join(names)}"

    def submitted_fields(self):
        """The POST as name/value pairs, ready to re-emit as hidden inputs.

        ``getlist`` rather than plain lookup because the product
        checkboxes send one value per tick, and a set of products that
        silently collapsed to its first member would be a nasty way to
        lose a promotion's terms.
        """
        return [
            (name, value)
            for name in self.request.POST
            if name != "csrfmiddlewaretoken"
            for value in self.request.POST.getlist(name)
        ]


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


class ReinstateDiscountView(StaffRequiredMixin, View):
    """POST-only: bring an existing code back, with or without new terms.

    Reached only from the duplicate screen, where an admin tried to
    create a code whose name is already taken. Two buttons post here.
    ``apply_terms`` carries everything they typed and saves it over the
    existing code; without it, the code comes back exactly as it was and
    only ``is_active`` moves — the separation ``ToggleDiscountActiveView``
    insists on, preserved by making the admin choose which they meant.

    Reinstating never rewrites an order. ``reset_usage`` moves
    ``counting_since`` instead, which changes what counts towards the
    limits from here on and leaves every past order's frozen discount
    exactly where it is.
    """

    def post(self, request, pk):
        code = get_object_or_404(DiscountCode, pk=pk)
        apply_terms = "apply_terms" in request.POST

        if not apply_terms and code.is_active:
            # Nothing to switch back on. Saying so beats reporting a
            # success that changed nothing.
            messages.info(request, f"{code.code} is already {code.status}.")
            return redirect("orders:manage_discount_update", pk=code.pk)

        if apply_terms:
            form = DiscountCodeForm(request.POST, instance=code)
            if not form.is_valid():
                messages.error(
                    request,
                    f"{code.code} wasn't changed — those terms didn't validate.",
                )
                return redirect("orders:manage_discount_update", pk=code.pk)
            code = form.save()

        code.is_active = True
        if "reset_usage" in request.POST:
            code.counting_since = timezone.now()
        code.save(update_fields=["is_active", "counting_since"])

        terms = " with your new terms" if apply_terms else ""
        counting = (
            " Its usage count starts over." if "reset_usage" in request.POST else ""
        )
        if code.status in {"live", "scheduled"}:
            messages.success(request, f"{code.code} is back{terms}.{counting}")
        else:
            # Chiefly the expired case: switching is_active on cannot
            # outrun a date that has already passed.
            messages.warning(
                request,
                f"{code.code} was saved{terms}, but it's still {code.status} — "
                "check its dates.",
            )
        return redirect("orders:manage_discounts")
