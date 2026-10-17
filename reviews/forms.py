"""The review forms: the author's, the staff member's moderation form, and the
back office's Reviews tab filters.

The comment's length rule lives on ``Review.clean`` — it applies to live
reviews only — and reaches this form through ``full_clean``, so each
problem is reported once. The rating is drawn by the template as a
DaisyUI half-star picker from ``rating_options``, not by its widget.
"""

from django import forms

from products.forms import StyledModelForm
from products.models import Product

from .models import DEFAULT_MANAGE_SORT, MANAGE_SORTS, Review


class ReviewForm(StyledModelForm):
    """Rating, optional headline and comment — what an author writes."""

    class Meta:
        model = Review
        fields = ["rating", "headline", "comment"]
        labels = {"headline": "Headline (optional)", "comment": "Your review"}
        widgets = {"comment": forms.Textarea(attrs={"rows": 5})}
        error_messages = {
            "rating": {
                "required": "Choose a rating.",
                "invalid_choice": "Choose a rating.",
            }
        }

    def rating_options(self):
        """The picker's radios, lowest first: 1 star, 1½ stars … 5 stars.

        There is no half-star option: 1.0 is the lowest rating, so the
        first star is one whole radio and every later star is two
        halves. ``checked`` keeps a rejected submission's choice.
        """
        chosen = str(self["rating"].value() or "")
        return [
            {
                "value": value,
                "label": label,
                "whole": value == Review.Rating.ONE,
                "half": 1 if value % 2 else 2,
                "checked": str(value) == chosen,
            }
            for value, label in Review.Rating.choices
        ]

    def rating_chosen(self):
        """Whether any rating is checked; if not, the hidden "no rating" radio is."""
        return any(option["checked"] for option in self.rating_options())


class ModerationForm(StyledModelForm):
    """Headline and comment only — what staff may correct in someone else's review.

    No rating field: staff remove abuse without changing what the customer
    thought of the product, so a POSTed rating never reaches the model.
    """

    class Meta:
        model = Review
        fields = ["headline", "comment"]
        labels = {"headline": "Headline (optional)", "comment": "Review"}
        widgets = {"comment": forms.Textarea(attrs={"rows": 5})}


class ReviewFilterForm(forms.Form):
    """The Reviews tab's search, sort and filters, read from the querystring.

    Every field is optional. A value the form doesn't recognise, from a
    hand-edited querystring or a product since deleted, drops out of
    ``cleaned_data`` on its own, so that filter is ignored and the others
    still apply. The product menu offers only products with a review, of
    any status: the rest would only ever show an empty list.
    """

    AUTHORS = [("customer", "Customers"), ("staff", "Staff")]
    STATUSES = [("live", "Live"), ("removed", "Removed")]
    FILTERS = ["q", "product", "rating", "author", "status"]

    q = forms.CharField(
        label="Search",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "type": "search",
                "placeholder": "Search reviewer, product or text",
                "class": "input input-sm w-full sm:w-64",
            }
        ),
    )
    sort = forms.ChoiceField(
        label="Sort by",
        choices=[(value, sort["label"]) for value, sort in MANAGE_SORTS.items()],
        required=False,
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(reviews__isnull=False)
        .distinct()
        .order_by("name"),
        required=False,
        empty_label="All products",
    )
    rating = forms.TypedChoiceField(
        choices=[("", "All ratings"), *Review.Rating.choices],
        coerce=int,
        empty_value=None,
        required=False,
    )
    author = forms.ChoiceField(choices=[("", "All authors"), *AUTHORS], required=False)
    status = forms.ChoiceField(
        choices=[("", "All statuses"), *STATUSES], required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "q":
                field.widget.attrs["class"] = "select select-sm w-full sm:w-auto"

    def filters(self):
        """The valid search and filters, ready for ``Review.objects.filtered``."""
        self.is_valid()
        return {
            name: self.cleaned_data[name]
            for name in self.FILTERS
            if name in self.cleaned_data
        }

    def chosen_sort(self):
        """The chosen sort, a key of ``MANAGE_SORTS``; Reviewer A–Z by default."""
        self.is_valid()
        return self.cleaned_data.get("sort") or DEFAULT_MANAGE_SORT

    def is_active(self):
        """Whether a search or filter narrows the list, for "Clear filters".

        The sort narrows nothing, so it doesn't count.
        """
        return any(value not in (None, "") for value in self.filters().values())
