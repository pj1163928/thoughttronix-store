"""The order forms.

``CheckoutForm`` is the codebase's showcase of declarative validation.
Every rule is visible at its field declaration, in the style of data
annotations: field types validate (``EmailField``), field arguments
validate (``required``, ``max_length``, ``ChoiceField``), and the
``validators=[...]`` list carries the rest. No ``clean_*`` methods
and no ``clean()`` — none of its rules need imperative validation.

``ApplyDiscountForm`` is the deliberate exception, and the reason is
worth naming: whether a code exists, is live, and matches this cart are
questions only the database can answer, and each wrong answer needs its
own sentence for the customer. That is what ``clean_*`` is for.
"""

from django import forms
from django.core.validators import RegexValidator
from django.utils import timezone

from products.forms import StyledModelForm

from .models import DiscountCode, Order
from .validators import validate_card_number, validate_expiry

US_STATES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]

zip_validator = RegexValidator(
    r"^\d{5}(-\d{4})?$", "Enter a ZIP code like 79016 or 79016-1234."
)
cvv_validator = RegexValidator(r"^\d{3,4}$", "Enter the 3- or 4-digit CVV.")


class CheckoutForm(forms.Form):
    """One page, one POST: contact, shipping, billing, payment."""

    email = forms.EmailField(label="Email")

    shipping_name = forms.CharField(label="Full name", max_length=100)
    shipping_street = forms.CharField(label="Street address", max_length=200)
    shipping_line2 = forms.CharField(
        label="Apt, suite, etc. (optional)", max_length=200, required=False
    )
    shipping_city = forms.CharField(label="City", max_length=100)
    shipping_state = forms.ChoiceField(label="State", choices=US_STATES)
    shipping_zip = forms.CharField(
        label="ZIP code", max_length=10, validators=[zip_validator]
    )

    billing_name = forms.CharField(label="Full name", max_length=100)
    billing_street = forms.CharField(label="Street address", max_length=200)
    billing_line2 = forms.CharField(
        label="Apt, suite, etc. (optional)", max_length=200, required=False
    )
    billing_city = forms.CharField(label="City", max_length=100)
    billing_state = forms.ChoiceField(label="State", choices=US_STATES)
    billing_zip = forms.CharField(
        label="ZIP code", max_length=10, validators=[zip_validator]
    )

    card_number = forms.CharField(
        label="Card number", max_length=23, validators=[validate_card_number]
    )
    card_expiry = forms.CharField(
        label="Expiry (MM/YY)", max_length=5, validators=[validate_expiry]
    )
    card_cvv = forms.CharField(label="CVV", max_length=4, validators=[cvv_validator])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs["class"] = "select w-full"
            else:
                widget.attrs["class"] = "input w-full"

    # Field groups for the template — the form owns its own structure.

    def shipping_fields(self):
        return [self[name] for name in self.fields if name.startswith("shipping_")]

    def billing_fields(self):
        return [self[name] for name in self.fields if name.startswith("billing_")]

    def card_fields(self):
        return [self[name] for name in self.fields if name.startswith("card_")]


class ApplyDiscountForm(forms.Form):
    """The cart's discount box: one field, and a specific reason for every no.

    ``clean_code`` returns the ``DiscountCode`` itself rather than the
    string, so the view has nothing left to look up. Every rejection
    names the code and says what is actually wrong with it — an expired
    code never reaches the customer as a blank page or a bare "invalid".
    """

    code = forms.CharField(
        label="Discount code",
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "input join-item w-full", "placeholder": "Discount code"}
        ),
    )

    def __init__(self, *args, cart=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cart = cart

    def clean_code(self):
        code = DiscountCode.objects.find(self.cleaned_data["code"])
        if code is None:
            raise forms.ValidationError("We don't have a code by that name.")

        now = timezone.now()
        if not code.is_active:
            raise forms.ValidationError(f"{code.code} is no longer available.")
        if code.starts_at and now < code.starts_at:
            starts = timezone.localtime(code.starts_at).strftime("%B %-d")
            raise forms.ValidationError(f"{code.code} doesn't start until {starts}.")
        if code.ends_at and now >= code.ends_at:
            ended = timezone.localtime(code.ends_at).strftime("%B %-d")
            raise forms.ValidationError(f"{code.code} expired on {ended}.")

        if self.cart is not None and code.discount_for(self.cart) <= 0:
            if code.product:
                raise forms.ValidationError(
                    f"{code.code} applies to {code.product.name}, "
                    "which isn't in your cart."
                )
            raise forms.ValidationError(f"{code.code} has nothing to discount yet.")
        return code


class OrderStatusForm(forms.ModelForm):
    """The back-office status dropdown — any of the four states, anytime.

    Guarding the workflow (no un-cancelling, no re-shipping a delivered
    order) is deliberately left as a student exercise.
    """

    class Meta:
        model = Order
        fields = ["status"]
        widgets = {"status": forms.Select(attrs={"class": "select"})}


class DiscountCodeForm(StyledModelForm):
    """The back-office create/edit form for a code.

    ``is_active`` is deliberately absent: retiring is its own button on
    the list, so editing a promotion's terms can never switch it off by
    accident, and switching it off can never change its terms.
    """

    class Meta:
        model = DiscountCode
        fields = ["code", "kind", "value", "product", "starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].empty_label = "The whole order"

    def clean_code(self):
        """Normalise before validation, not just before saving.

        The model capitalises on save, but uniqueness is checked against
        ``cleaned_data`` — so without this, ``spring50`` would sail past
        the unique check next to an existing ``SPRING50`` and only fail
        at the database. It also keeps the success message honest.
        """
        return DiscountCode.normalize(self.cleaned_data["code"])
