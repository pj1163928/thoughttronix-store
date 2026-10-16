"""The review forms: the author's, and the staff member's moderation form.

The comment's length rule lives on ``Review.clean`` — it applies to live
reviews only — and reaches this form through ``full_clean``, so each
problem is reported once. The rating is drawn by the template as a
DaisyUI half-star picker from ``rating_options``, not by its widget.
"""

from django import forms

from products.forms import StyledModelForm

from .models import Review


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
