from django import template

from reviews.views import slot_context

register = template.Library()


@register.inclusion_tag("reviews/partials/_reviews_section.html", takes_context=True)
def reviews_section(context, product):
    """The product page's Reviews section, in the signed-in user's current state.

    A tag rather than view context so ``products`` never imports this
    app, as with ``{% wishlist_button %}``.
    """
    request = context["request"]
    return {
        **slot_context(request.user, product),
        "user": request.user,
        "request": request,
    }


@register.filter
def half_stars(rating):
    """The ten half-star positions of a stored rating, each lit or not.

    For a read-only star row: ``half`` is which half of its star a
    position draws (1 left, 2 right).
    """
    return [
        {"half": 1 if position % 2 else 2, "lit": position <= rating}
        for position in range(1, 11)
    ]
