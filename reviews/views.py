"""Review views — thin, and each HTMX endpoint returns a partial.

The "Your review" slot is always rebuilt from the database by
``slot_context``, the one place its state is decided, shared with the
product page's ``reviews_section`` tag.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, render
from django.views import View

from products.models import Product

from .forms import ReviewForm
from .models import Review

SLOT_UPDATE_TEMPLATE = "reviews/partials/_slot_update.html"


def slot_context(user, product, form=None):
    """What the "Your review" slot shows ``user`` for ``product``, from the database.

    Their own review if they have one; otherwise whether they may write
    one, with ``form`` (a rejected submission) or a blank form.
    """
    review = Review.objects.by(user).filter(product=product).first()
    return {
        "product": product,
        "review": review,
        "eligible": review is None and Review.can_write(user, product),
        "form": form or ReviewForm(),
    }


def section_context(user, product, form=None):
    """The whole Reviews section for ``user``: the slot, the summary and the list.

    ``others`` is lazy, so a response that only re-renders the slot and
    the summaries never queries it.
    """
    reviews = Review.objects.filter(product=product)
    return {
        **slot_context(user, product, form),
        "summary": reviews.rating_summary(),
        "others": reviews.listed_for(user),
    }


class CreateReviewView(LoginRequiredMixin, View):
    """HTMX: write the signed-in user's review of a product, then re-render the slot.

    Every outcome answers with the slot as the database now has it, plus
    the section summary and the details-card average out of band. A
    user who already has a review — a double click, a stale second tab —
    gets that review back and nothing is written; so does the loser of
    two submits racing past that check, caught by the unique constraint.
    An ineligible user gets the not-bought note.
    """

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = None
        already = Review.objects.by(request.user).filter(product=product).exists()
        if not already and Review.can_write(request.user, product):
            form = ReviewForm(
                request.POST, instance=Review(user=request.user, product=product)
            )
            if form.is_valid():
                try:
                    with transaction.atomic():
                        form.save()
                except IntegrityError:
                    pass  # A concurrent submit won; the slot shows its review.
                form = None
        return render(
            request,
            SLOT_UPDATE_TEMPLATE,
            section_context(request.user, product, form),
        )
