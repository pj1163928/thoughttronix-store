from django import template

from reviews.models import RatingSummary, Review
from reviews.views import revealing_list_context, section_context

register = template.Library()


@register.inclusion_tag("reviews/partials/_reviews_section.html", takes_context=True)
def reviews_section(context, product):
    """The product page's Reviews section, in the signed-in user's current state.

    A tag rather than view context so ``products`` never imports this
    app, as with ``{% wishlist_button %}``. A ``?review=<pk>`` from the
    back office's "View on product page" link lists reviews down to that
    one, so its ``#review-<pk>`` anchor is on the page to jump to.
    """
    request = context["request"]
    return {
        **section_context(request.user, product),
        **revealing_list_context(request.user, product, request.GET.get("review", "")),
        "user": request.user,
        "request": request,
    }


@register.inclusion_tag("reviews/partials/_details_rating.html")
def review_rating(product):
    """The details card's small customer average and count, linking to the section."""
    return {"summary": Review.objects.filter(product=product).rating_summary()}


@register.inclusion_tag("reviews/partials/_card_rating.html")
def card_rating(product):
    """A catalog card's customer average and count, read from ``with_ratings()``.

    The product must come from ``ProductQuerySet.with_ratings()``: the tag
    reads its annotations, so a grid of cards adds no query per card.
    """
    return {
        "summary": RatingSummary(
            count=product.rating_count, average=product.rating_average
        )
    }


@register.filter
def half_stars(rating):
    """The ten half-star positions of a rating in half stars, drawn as five stars.

    For a read-only star row: ``half`` is which half of its star a
    position draws (1 left, 2 right), and ``current`` marks the last lit
    half. DaisyUI's ``rating`` lights that position and every one before
    it, and leaves the rest faint.
    """
    return [
        {"half": 1 if position % 2 else 2, "current": position == rating}
        for position in range(1, 11)
    ]
