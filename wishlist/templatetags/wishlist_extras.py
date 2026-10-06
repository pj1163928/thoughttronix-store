from django import template

from wishlist.models import WishlistItem

register = template.Library()


@register.inclusion_tag("wishlist/partials/_wishlist_button.html", takes_context=True)
def wishlist_button(context, product):
    """The wishlist button for ``product``, in the signed-in user's current state.

    A tag rather than view context so ``products`` never imports this
    app, and so only pages that show the button pay for its one query.
    """
    request = context["request"]
    return {
        "product": product,
        "in_wishlist": WishlistItem.objects.of(request.user).holds(product),
        "user": request.user,
        "request": request,
    }
