"""Review views — thin, and each HTMX endpoint returns a partial.

The "Your review" slot is always rebuilt from the database by
``slot_context``, the one place its state is decided, shared with the
product page's ``reviews_section`` tag.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import InvalidPage, Paginator
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from products.models import Product

from .forms import ModerationForm, ReviewForm
from .models import DEFAULT_SORT, SORTS, Review

SLOT_UPDATE_TEMPLATE = "reviews/partials/_slot_update.html"
REVIEW_TEMPLATE = "reviews/partials/_review.html"
FORM_TEMPLATE = "reviews/partials/_review_form.html"
MODERATE_FORM_TEMPLATE = "reviews/partials/_review_moderate_form.html"
CONFIRM_DELETE_TEMPLATE = "reviews/partials/_review_delete_confirm.html"
PAGE_TEMPLATE = "reviews/partials/_review_page.html"
REVIEWS_PER_PAGE = 10


def slot_context(user, product, form=None):
    """What the "Your review" slot shows ``user`` for ``product``, from the database.

    Their own review if they have one; otherwise whether they may write
    one, with ``form`` (a rejected submission) or a blank form. A
    rejected ``form`` alongside an existing review is a rejected edit,
    so the slot shows the edit form again with its errors.
    """
    review = Review.objects.by(user).filter(product=product).first()
    return {
        "product": product,
        "review": review,
        "eligible": review is None and Review.can_write(user, product),
        "editing": review is not None and form is not None,
        "form": form or ReviewForm(),
    }


def section_context(user, product, form=None):
    """The slot and the summary: everything a change to ``user``'s review re-renders.

    The list below them comes from ``list_context``, which only the page
    load and ``reviews:list`` need.
    """
    return {
        **slot_context(user, product, form),
        "summary": Review.objects.filter(product=product).rating_summary(),
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


def list_context(user, product, sort=DEFAULT_SORT, page=1):
    """One page of everyone else's reviews of ``product``, as ``user`` sees them.

    ``REVIEWS_PER_PAGE`` at a time in ``sort`` (unknown sorts are Newest),
    never ``user``'s own review or a removed one. A page number past the
    end, or not a number, is a 404, as for Django's ``ListView``: Show more
    must never hand back a page it has already shown.
    """
    if sort not in SORTS:
        sort = DEFAULT_SORT
    reviews = Review.objects.filter(product=product).listed_for(user).sorted_by(sort)
    try:
        page = Paginator(reviews, REVIEWS_PER_PAGE).page(page)
    except InvalidPage as error:
        raise Http404("No such page of reviews.") from error
    return {"product": product, "page": page, "sort": sort, "sorts": SORTS}


class ReviewListView(View):
    """HTMX: a page of everyone else's reviews of a product, in the chosen sort.

    Open to visitors, as the product page is. The sort menu asks for page
    one and replaces the list; Show more asks for the next page in the
    same sort and replaces its own button. Both get the same partial: the
    page's reviews, then a fresh button if any remain.
    """

    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        context = list_context(
            request.user,
            product,
            request.GET.get("sort", DEFAULT_SORT),
            request.GET.get("page", 1),
        )
        return render(request, PAGE_TEMPLATE, context)


class ReviewActionMixin(LoginRequiredMixin):
    """Finds the review in the URL for a user allowed to act on it.

    The author or staff (``Review.objects.changeable_by``); anyone else
    gets a 404, as for another customer's wishlist line. ``author_only``
    views narrow that to the author: a staff member's change to someone
    else's review goes through the staff endpoints, which can't touch
    the rating. ``staff_only`` views narrow it the other way, to staff
    acting on someone else's review: an author, staff or not, changes
    their own review as its author.
    """

    author_only = False
    staff_only = False

    def get_review(self):
        reviews = Review.objects.changeable_by(self.request.user).live()
        review = get_object_or_404(
            reviews.select_related("product", "user"), pk=self.kwargs["pk"]
        )
        if self.author_only and review.user_id != self.request.user.pk:
            raise Http404("Only the author edits their review here.")
        if self.staff_only and (
            not self.request.user.is_staff or review.user_id == self.request.user.pk
        ):
            raise Http404("Staff moderate other people's reviews here.")
        return review


class ReviewDetailView(ReviewActionMixin, View):
    """HTMX: one review, as it is now — what Cancel swaps back over a form."""

    def get(self, request, pk):
        return render(request, REVIEW_TEMPLATE, {"review": self.get_review()})


class EditReviewView(ReviewActionMixin, View):
    """HTMX: the author's edit of their own review — rating, headline and comment.

    The GET swaps the filled-in form over the review and changes nothing.
    A valid POST saves, marks the review "Edited" if anything changed,
    and answers with the slot plus both averages out of band; an invalid
    one answers with the slot holding the form and its errors.
    """

    author_only = True

    def get(self, request, pk):
        review = self.get_review()
        return render(
            request,
            FORM_TEMPLATE,
            {
                "review": review,
                "product": review.product,
                "form": ReviewForm(instance=review),
            },
        )

    def post(self, request, pk):
        review = self.get_review()
        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            if form.has_changed():
                form.instance.edited_at = timezone.now()
            form.save()
            form = None
        return render(
            request,
            SLOT_UPDATE_TEMPLATE,
            section_context(request.user, review.product, form),
        )


class DeleteReviewView(ReviewActionMixin, View):
    """HTMX: the author's delete of their own review — a real deletion.

    The GET swaps the inline "Delete your review?" confirmation over the
    review and changes nothing; its "Keep it" fetches the review back
    through ``reviews:detail``. The POST deletes the row and answers with
    the slot as the database now has it — the form again for an author
    who is still eligible, the not-bought note for one who isn't — plus
    both averages out of band.
    """

    author_only = True

    def get(self, request, pk):
        return render(request, CONFIRM_DELETE_TEMPLATE, {"review": self.get_review()})

    def post(self, request, pk):
        review = self.get_review()
        product = review.product
        review.delete()
        return render(
            request, SLOT_UPDATE_TEMPLATE, section_context(request.user, product)
        )


class ModerateReviewView(ReviewActionMixin, View):
    """HTMX: a staff member's edit of someone else's review — headline and comment.

    The GET swaps the staff form over the review in the list and changes
    nothing; its Cancel fetches the review back through ``reviews:detail``.
    A valid POST saves, marks the review "Edited by ThoughtTronix staff"
    if anything changed, and answers with the review; an invalid one
    answers with the form and its errors. The rating can't change, so
    neither can any average, and nothing is swapped out of band.
    """

    staff_only = True

    def get(self, request, pk):
        review = self.get_review()
        return render(
            request,
            MODERATE_FORM_TEMPLATE,
            {"review": review, "form": ModerationForm(instance=review)},
        )

    def post(self, request, pk):
        review = self.get_review()
        form = ModerationForm(request.POST, instance=review)
        if not form.is_valid():
            return render(
                request, MODERATE_FORM_TEMPLATE, {"review": review, "form": form}
            )
        if form.has_changed():
            form.instance.moderated_at = timezone.now()
            form.instance.moderated_by = request.user
        form.save()
        return render(request, REVIEW_TEMPLATE, {"review": review})
