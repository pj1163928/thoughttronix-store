from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    SetPasswordMixin,
    UserCreationForm,
)
from django.template.defaultfilters import pluralize

from . import security
from .models import Address, User


class SignupForm(UserCreationForm):
    """Username, email, and password with confirmation.

    The email is required here, though not on the model: it is how a
    forgotten password is recovered, but accounts from before sign-up
    asked for one have none. It must not belong to another account,
    compared case-insensitively, and is stored as typed. The username
    rules — no ``@``, no case-only twin — come from the model field and
    from ``UserCreationForm`` itself.

    The widgets carry DaisyUI classes because plain Django forms own
    their own styling here.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        help_texts = {"email": "For password resets and account alerts."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        for field in self.fields.values():
            field.widget.attrs["class"] = "input w-full"

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.with_email(email).exists():
            raise forms.ValidationError(
                "An account with that email address already exists."
            )
        return email


class SignInForm(AuthenticationForm):
    """The stock authentication form, dressed in DaisyUI.

    The ``username`` field takes a username or an email; the backend
    decides which. Its length is widened from the username's limit to an
    email's.

    Every refusal reads the same: a wrong password, an account that
    doesn't exist, a locked account and a cooldown all come back from the
    backend as "no user", and all show one message. The attempts-left line
    beneath it comes from ``SignInView``, out of this browser's own
    history, so it doesn't say whether the account exists either.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Those details didn't work.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        identifier = self.fields["username"]
        identifier.label = "Username or email"
        identifier.max_length = User._meta.get_field("email").max_length
        identifier.widget.attrs["maxlength"] = identifier.max_length
        for field in self.fields.values():
            field.widget.attrs["class"] = "input w-full"


class ReauthenticationForm(forms.Form):
    """The "prove it's you" field every sensitive change starts with.

    Subclasses add the change itself and set ``purpose``, a short label
    stored on the audit event when the password is wrong. The check is
    ``security.confirm_identity``: a wrong password counts toward the
    sign-in cooldown, and while the account is paused nothing is checked.
    The user is signed in and asking about their own account, so unlike
    the sign-in page this form may say that it is paused.
    """

    purpose = ""

    current_password = forms.CharField(
        label="Current password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, request=None, **kwargs):
        self.user = user
        self.request = request
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input w-full"

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if security.confirm_identity(
            self.user, password, purpose=self.purpose, request=self.request
        ):
            return password
        standing = security.sign_in_standing(self.user)
        if standing.paused_until:
            minutes = standing.paused_minutes
            raise forms.ValidationError(
                f"Too many failed attempts. Try again in {minutes} "
                f"minute{pluralize(minutes)}.",
                code="paused",
            )
        raise forms.ValidationError(
            "That isn't your current password.", code="wrong_password"
        )


class PasswordChangeForm(SetPasswordMixin, ReauthenticationForm):
    """The current password, then the new one twice.

    Django's own ``PasswordChangeForm`` checks the old password itself;
    this one checks it through ``ReauthenticationForm`` so a wrong answer
    counts toward the cooldown like any other.
    """

    purpose = "password_change"

    new_password1, new_password2 = SetPasswordMixin.create_password_fields(
        label1="New password", label2="New password again"
    )

    def clean(self):
        self.validate_passwords("new_password1", "new_password2")
        self.validate_password_for_user(self.user, "new_password2")
        return super().clean()

    def save(self, commit=True):
        return self.set_password_and_save(self.user, "new_password1", commit=commit)


class SignOutOthersForm(ReauthenticationForm):
    """Only the current password: the button's whole job is to act."""

    purpose = "sign_out_others"


class SignOutDeviceForm(ReauthenticationForm):
    """Only the current password; the device comes from the URL."""

    purpose = "sign_out_device"


class AddressForm(forms.ModelForm):
    """Create or edit one saved address, defaults included.

    The default checkboxes are *requests*, not fields to be written. They
    never reach the database directly: ``save`` clears them on the
    instance and routes the request through ``Address.make_default``,
    which is the only thing allowed to move a default. Writing the raw
    flag would put two rows in one role for as long as the transaction
    lasted, which the unique constraints forbid outright.

    A box is rendered disabled when this address already holds that role,
    so the gesture that would leave a customer with no default simply
    isn't offered. Disabled fields fall back to their initial value, so
    the role survives the save untouched.

    Styling is done here rather than inherited from
    ``products.StyledModelForm``: ``products`` imports
    ``accounts.mixins``, and inheriting the other way would make the two
    apps import each other.
    """

    class Meta:
        model = Address
        fields = [
            "label",
            "name",
            "street",
            "line2",
            "city",
            "state",
            "zip",
            "is_default_shipping",
            "is_default_billing",
        ]
        labels = {
            "label": "Name this address (optional)",
            "name": "Full name",
            "street": "Street address",
            "line2": "Apt, suite, etc. (optional)",
            "city": "City",
            "state": "State",
            "zip": "ZIP code",
            "is_default_shipping": "Use as my default shipping address",
            "is_default_billing": "Use as my default billing address",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "checkbox checkbox-primary"
                if getattr(self.instance, name, False):
                    field.disabled = True
                    field.help_text = "Tick a different address to change this."
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "select w-full"
            else:
                widget.attrs["class"] = "input w-full"

    def address_fields(self):
        """The address itself — the template's grammar, the form's structure."""
        return [self[name] for name in self.fields if not name.startswith("is_default")]

    def default_fields(self):
        return [self[name] for name in self.fields if name.startswith("is_default")]

    def save(self, commit=True):
        roles = {
            "shipping": self.cleaned_data.get("is_default_shipping", False),
            "billing": self.cleaned_data.get("is_default_billing", False),
        }
        address = super().save(commit=False)
        address.is_default_shipping = False
        address.is_default_billing = False
        if not commit:
            return address

        address.save()
        others = Address.objects.filter(user=address.user).exclude(pk=address.pk)
        if not others.exists():
            # A customer's first address is their default for both roles,
            # whatever they ticked — checkout must always have something
            # to pre-select.
            roles = {"shipping": True, "billing": True}
        if any(roles.values()):
            address.make_default(**roles)
        return address
