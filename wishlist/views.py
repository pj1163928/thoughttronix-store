"""Wishlist views — thin, and always reached through the owner.

The product page's add and remove buttons are HTMX: each re-renders
``_wishlist_button.html`` from what the database holds after the change.
Both are idempotent rather than a toggle, so a double click or a stale
second tab lands on the state its button promised instead of flipping
it back. The wishlist page's own Remove buttons re-render the whole list,
the way the cart's line buttons do.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import TemplateView

from products.models import Product

from .models import Wishlist, WishlistItem


class WishlistView(LoginRequiredMixin, TemplateView):
    """The customer's own wishlist page, newest first."""

    template_name = "wishlist/wishlist.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["items"] = WishlistItem.objects.of(self.request.user).with_products()
        return context


class WishlistButtonView(LoginRequiredMixin, View):
    """Base for the product page's HTMX buttons: act, then re-render the button.

    Any product can be saved, so the lookup is the whole catalog — not
    ``available()`` as add-to-cart uses.
    """

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        self.act(Wishlist.for_user(request.user), product)
        return render(
            request,
            "wishlist/partials/_wishlist_button.html",
            {
                "product": product,
                "in_wishlist": WishlistItem.objects.of(request.user).holds(product),
            },
        )

    def act(self, wishlist, product):
        raise NotImplementedError


class AddToWishlistView(WishlistButtonView):
    def act(self, wishlist, product):
        wishlist.add(product)


class RemoveFromWishlistView(WishlistButtonView):
    def act(self, wishlist, product):
        wishlist.remove(product)


class RemoveWishlistItemView(LoginRequiredMixin, View):
    """HTMX: remove one line on the wishlist page, then re-render the list.

    Lines are fetched through the owner — another customer's line 404s,
    the same answer as a line that doesn't exist.
    """

    def post(self, request, pk):
        mine = WishlistItem.objects.of(request.user)
        get_object_or_404(mine, pk=pk).delete()
        return render(
            request,
            "wishlist/partials/_wishlist_contents.html",
            {"items": mine.with_products()},
        )
