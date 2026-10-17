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
from django.views.generic import ListView

from accounts.mixins import StaffRequiredMixin
from products.models import Product

from .forms import ModerationForm, ReviewFilterForm, ReviewForm
from .models import DEFAULT_SORT, SORTS, Review

SLOT_UPDATE_TEMPLATE = "reviews/partials/_slot_update.html"
REVIEW_TEMPLATE = "reviews/partials/_review.html"
REMOVED_NOTICE_TEMPLATE = "reviews/partials/_review_removed_notice.html"
FORM_TEMPLATE = "reviews/partials/_review_form.html"
MODERATE_FORM_TEMPLATE = "reviews/partials/_review_moderate_form.html"
CONFIRM_DELETE_TEMPLATE = "reviews/partials/_review_delete_confirm.html"
CONFIRM_REMOVE_TEMPLATE = "reviews/partials/_review_remove_confirm.html"
REMOVED_TEMPLATE = "reviews/partials/_review_removed.html"
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
    return {
        "product": product,
        "page": page,
        "reviews": page.object_list,
        "sort": sort,
        "sorts": SORTS,
    }


def revealing_list_context(user, product, review_pk):
    """The product page's first list, shown down to the review ``review_pk``.

    The Reviews tab's "View on product page" link asks for this, so the
    review it jumps to is on the page however far down the Newest list it
    sits: every page up to and including its own, with Show more carrying
    on from there. A pk that isn't one of ``product``'s listed reviews, or
    isn't a number, gets the ordinary first page; so does the viewer's own
    review, which is in the "Your review" slot instead.
    """
    listed = Review.objects.filter(product=product).listed_for(user)
    review = listed.filter(pk=review_pk).first() if str(review_pk).isdigit() else None
    if review is None:
        return list_context(user, product)
    last_page = listed.newer_than(review).count() // REVIEWS_PER_PAGE + 1
    context = list_context(user, product, DEFAULT_SORT, last_page)
    context["reviews"] = listed.sorted_by(DEFAULT_SORT)[: last_page * REVIEWS_PER_PAGE]
    return context


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

    A removed review is a 404 unless the view ``allow_removed``, and even
    then only for its author, who may see the removal notice and delete
    the text.
    """

    author_only = False
    staff_only = False
    allow_removed = False

    def get_review(self):
        reviews = Review.objects.changeable_by(self.request.user)
        if not self.allow_removed:
            reviews = reviews.live()
        review = get_object_or_404(
            reviews.select_related("product", "user"), pk=self.kwargs["pk"]
        )
        if review.removed_at and review.user_id != self.request.user.pk:
            raise Http404("Only its author may reach a removed review.")
        if self.author_only and review.user_id != self.request.user.pk:
            raise Http404("Only the author edits their review here.")
        if self.staff_only and (
            not self.request.user.is_staff or review.user_id == self.request.user.pk
        ):
            raise Http404("Staff moderate other people's reviews here.")
        return review


class ReviewDetailView(ReviewActionMixin, View):
    """HTMX: one review, as it is now — what Cancel swaps back over a form.

    A removed review comes back to its author as the removal notice, never
    its text: that is what "Keep it" swaps back over the delete
    confirmation.
    """

    allow_removed = True

    def get(self, request, pk):
        review = self.get_review()
        template = REMOVED_NOTICE_TEMPLATE if review.removed_at else REVIEW_TEMPLATE
        return render(request, template, {"review": review})


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
    """HTMX: the author's delete of their own review.

    The GET swaps the inline "Delete your review?" confirmation over the
    review and changes nothing; its "Keep it" fetches the review back
    through ``reviews:detail``. The POST answers with the slot as the
    database now has it, plus both averages out of band.

    A live review is really deleted: the slot shows the form again for an
    author who is still eligible, the not-bought note for one who isn't.
    A removed review only loses its text: the row stays, so its author
    still can't post it again, and the slot keeps the removal notice.
    """

    author_only = True
    allow_removed = True

    def get(self, request, pk):
        return render(request, CONFIRM_DELETE_TEMPLATE, {"review": self.get_review()})

    def post(self, request, pk):
        review = self.get_review()
        product = review.product
        if review.removed_at:
            review.delete_text()
        else:
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


class RemoveReviewView(ReviewActionMixin, View):
    """HTMX: a staff member's removal of someone else's review.

    The GET swaps the inline "Remove this review?" confirmation over the
    review in the list and changes nothing; its Cancel fetches the review
    back through ``reviews:detail``. The POST removes it and answers with
    nothing for its place in the list, which takes it off the page, plus
    both averages out of band: a removed review leaves every number.
    """

    staff_only = True

    def get(self, request, pk):
        return render(request, CONFIRM_REMOVE_TEMPLATE, {"review": self.get_review()})

    def post(self, request, pk):
        review = self.get_review()
        review.remove(request.user)
        return render(
            request,
            REMOVED_TEMPLATE,
            {"summary": Review.objects.filter(product=review.product).rating_summary()},
        )


# --- The back office ----------------------------------------------------------
#
# The Reviews tab: the one place reviews are moderated, since they are kept
# out of the Django admin. The ``section`` context entry drives the active
# tab in the staff shell.


class ManageReviewListView(StaffRequiredMixin, ListView):
    """Every review, removed and staff ones included, 20 a page.

    Sorted by ``?sort=`` (Reviewer A–Z by default, Product A–Z or
    Newest), searched by ``?q=`` and filtered by ``?product=``,
    ``?rating=``, ``?author=`` and ``?status=``, all through
    ``ReviewFilterForm``; they compose, and the pagination links keep
    them. This is the back office, so rows name the author by username
    and full name, with their profile picture, and the staff member who
    edited or removed the review.
    """

    template_name = "reviews/manage_reviews.html"
    context_object_name = "reviews"
    paginate_by = 20
    extra_context = {"section": "reviews"}

    def get_queryset(self):
        self.filter_form = ReviewFilterForm(self.request.GET)
        return (
            Review.objects.filtered(**self.filter_form.filters())
            .sorted_for_staff(self.filter_form.chosen_sort())
            .select_related("product", "user", "moderated_by", "removed_by")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        # Tells the empty state whether the filters emptied the list or the
        # store simply has no reviews yet.
        context["any_reviews"] = Review.objects.exists()
        return context
