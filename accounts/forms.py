from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    SetPasswordForm,
    SetPasswordMixin,
    UserCreationForm,
    UsernameField,
)
from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.template.defaultfilters import pluralize

from products import images
from products.images import AVATAR_SIZE, MAX_FILE_MB, validate_avatar

from . import security
from .models import Address, User


class SignupForm(UserCreationForm):
    """Username, an optional name, email, and password with confirmation.

    The email is required here, though not on the model: it is how a
    forgotten password is recovered, but accounts from before sign-up
    asked for one have none. It must not belong to another account,
    compared case-insensitively, and is stored as typed. The username
    rules — no ``@``, no case-only twin — come from the model field and
    from ``UserCreationForm`` itself.

    The name is optional; it greets the person in the navbar's profile
    menu, which falls back to the username without one.

    The widgets carry DaisyUI classes because plain Django forms own
    their own styling here.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {
            "first_name": "First name (optional)",
            "last_name": "Last name (optional)",
        }
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


def _refusal(user, message, code):
    """Why a password or code was refused: paused, or simply wrong.

    Only for a signed-in user asking about their own account, who may be
    told it is paused; the sign-in page never says so.
    """
    standing = security.sign_in_standing(user)
    if standing.paused_until:
        minutes = standing.paused_minutes
        return forms.ValidationError(
            f"Too many failed attempts. Try again in {minutes} "
            f"minute{pluralize(minutes)}.",
            code="paused",
        )
    return forms.ValidationError(message, code=code)


class AuthenticatorCodeMixin:
    """Adds a code from the authenticator app, when the account asks for one.

    The form sets ``self.user`` and ``self.request``, a ``code_occasion``
    (see ``security.code_required``) and a ``purpose`` for the audit log,
    then calls ``add_code_field``. ``asks_for_code`` decides whether the
    field appears; a form that always wants one overrides it.

    The code is checked last, in ``clean``, and only when everything else
    is valid. A code works once, so spending it on a form that is about to
    come back with a typo in it would leave the user waiting for the next
    one. A wrong code counts toward the cooldown, through
    ``security.confirm_code``.
    """

    code_occasion = None
    purpose = ""

    def asks_for_code(self):
        return security.code_required(self.user, self.code_occasion)

    def add_code_field(self):
        if self.asks_for_code():
            self.fields["two_factor_code"] = forms.CharField(
                label="Authenticator code",
                max_length=10,
                help_text="The six-digit code your authenticator app shows now.",
                widget=forms.TextInput(
                    attrs={
                        "autocomplete": "one-time-code",
                        "inputmode": "numeric",
                        "class": "input w-full font-mono",
                    }
                ),
            )

    def clean(self):
        cleaned_data = super().clean()
        if "two_factor_code" in self.fields and not self.errors:
            if not security.confirm_code(
                self.user,
                cleaned_data["two_factor_code"],
                purpose=self.purpose,
                request=self.request,
            ):
                self.add_error(
                    "two_factor_code",
                    _refusal(self.user, "That code didn't work.", "wrong_code"),
                )
        return cleaned_data


class ReauthenticationForm(AuthenticatorCodeMixin, forms.Form):
    """The "prove it's you" field every sensitive change starts with.

    Subclasses add the change itself and set ``purpose``, a short label
    stored on the audit event when the password is wrong. The check is
    ``security.confirm_identity``: a wrong password counts toward the
    sign-in cooldown, and while the account is paused nothing is checked.
    The user is signed in and asking about their own account, so unlike
    the sign-in page this form may say that it is paused.

    A two-factor user who has asked for a code on security changes gets
    an "Authenticator code" field beside the password, and both must
    match (see ``AuthenticatorCodeMixin``). Any other two-factor user may
    answer with either: the field becomes "Current password or
    authenticator code", and ``accepts_code`` is set. An answer shaped
    like a code is checked last, in ``clean``, once the rest of the form
    is valid, for the same reason as the separate field: a right code
    works once.
    """

    code_occasion = "security_changes"

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
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "checkbox checkbox-primary"
            else:
                field.widget.attrs["class"] = "input w-full"
        self.add_code_field()
        self.accepts_code = (
            "two_factor_code" not in self.fields and self.user.two_factor_enabled
        )
        self.code_deferred = False
        if self.accepts_code:
            answer = self.fields["current_password"]
            answer.label = "Current password or authenticator code"
            answer.help_text = "Or the six-digit code your authenticator app shows now."
        # Proof first, then the change, whatever order the fields were
        # declared in; a ``field_order`` still goes ahead of both.
        self.order_fields(
            [*(self.field_order or []), "current_password", "two_factor_code"]
        )

    def clean_current_password(self):
        answer = self.cleaned_data["current_password"]
        if self.accepts_code and security.is_authenticator_code(answer):
            self.code_deferred = True
        else:
            self.confirm_identity(answer)
        return answer

    def clean(self):
        cleaned_data = super().clean()
        if self.code_deferred and not self.errors:
            try:
                self.confirm_identity(cleaned_data["current_password"])
            except forms.ValidationError as error:
                self.add_error("current_password", error)
        return cleaned_data

    def confirm_identity(self, answer):
        if not security.confirm_identity(
            self.user,
            answer,
            purpose=self.purpose,
            accept_code=self.accepts_code,
            request=self.request,
        ):
            message = (
                "That isn't your current password or a working code."
                if self.accepts_code
                else "That isn't your current password."
            )
            raise _refusal(self.user, message, "wrong_password")


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


class PasswordResetForm(DjangoPasswordResetForm):
    """The email address a forgotten password's reset link goes to.

    Django's own form finds the account, case-insensitively, and mails it
    a single-use link; an inactive (locked) account or one with no usable
    password is left alone. The address needn't be verified. Whatever was
    typed, the view answers the same way, so nothing here may say whether
    an account matched. ``save`` adds the audit event, for matched
    accounts only.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Email address"
        self.fields["email"].widget.attrs["class"] = "input w-full"

    def save(self, *, request=None, **kwargs):
        super().save(request=request, **kwargs)
        for user in self.get_users(self.cleaned_data["email"]):
            security.password_reset_requested(user, request=request)


class ResetPasswordForm(SetPasswordForm):
    """The new password twice, from a reset link; no current password.

    The link is the proof. Django's ``SetPasswordForm`` validates and
    saves; this only relabels and styles it to match the change-password
    page.
    """

    new_password1, new_password2 = SetPasswordMixin.create_password_fields(
        label1="New password", label2="New password again"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input w-full"


class ChangeUsernameForm(ReauthenticationForm):
    """The current password, then the new username.

    The new name is held to sign-up's rules: the model field's own
    validators (so no ``@``), and no other account's username in any
    capitalisation. Recapitalising your own username is allowed; the
    name you already have is refused, since it would change nothing.

    The form never touches ``user`` until ``save``, so an invalid name
    can't leak into the rest of the page through ``request.user``.
    """

    purpose = "change_username"

    username = UsernameField(
        label="New username",
        max_length=User._meta.get_field("username").max_length,
        help_text=User._meta.get_field("username").help_text,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"]
        User._meta.get_field("username").run_validators(username)
        if username == self.user.username:
            raise forms.ValidationError(
                "That's already your username.", code="unchanged"
            )
        taken = User.objects.filter(username__iexact=username).exclude(pk=self.user.pk)
        if taken.exists():
            raise forms.ValidationError(
                "A user with that username already exists.", code="unique"
            )
        return username

    def save(self):
        self.user.username = self.cleaned_data["username"]
        self.user.save(update_fields=["username"])
        return self.user


class ChangeEmailForm(ReauthenticationForm):
    """The current password, then the new email address.

    Submitting it changes nothing yet: the view mails a confirmation link
    to the new address, and the old one stays in effect until it is
    followed. The address is held to sign-up's rule, unique among other
    accounts in any capitalisation; recapitalising your own is allowed,
    and the address you already have is refused, since it would change
    nothing. Uniqueness is checked again when the link is followed.
    """

    purpose = "change_email"

    email = forms.EmailField(
        label="New email address",
        max_length=User._meta.get_field("email").max_length,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email == self.user.email:
            raise forms.ValidationError(
                "That's already your email address.", code="unchanged"
            )
        if security.email_taken(email, by_other_than=self.user):
            raise forms.ValidationError(
                "An account with that email address already exists.", code="unique"
            )
        return email


class SignOutOthersForm(ReauthenticationForm):
    """Only the current password: the button's whole job is to act."""

    purpose = "sign_out_others"


class SignOutDeviceForm(ReauthenticationForm):
    """Only the current password; the device comes from the URL."""

    purpose = "sign_out_device"


class RecoveryCodesForm(ReauthenticationForm):
    """Only the current password: the page's whole job is to make new codes."""

    purpose = "recovery_codes"


class TwoFactorDisableForm(ReauthenticationForm):
    """The current password and a code, both, whatever the account has chosen.

    Turning two-factor off removes the protection the phone provides, so
    the phone alone mustn't be enough, and neither must the password.
    """

    purpose = "two_factor_disable"

    def asks_for_code(self):
        return True


class TwoFactorSetupForm(forms.Form):
    """A code from the authenticator app, proving setup worked.

    No current password: a working code proves the person has the phone,
    and a superuser sent here straight after signing in shouldn't be asked
    for it again. A wrong code here isn't counted toward the cooldown
    either, since the secret is on the page beside it and there is nothing
    to guess.
    """

    code = forms.CharField(
        label="Code from your app",
        max_length=10,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "placeholder": "123456",
            }
        ),
    )

    def __init__(self, device, *args, **kwargs):
        self.device = device
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs["class"] = "input w-full font-mono"

    def clean_code(self):
        code = self.cleaned_data["code"]
        if not security.verify_code(self.device, code):
            raise forms.ValidationError(
                "That code didn't work. Enter the newest six-digit code your "
                "app shows, and check your phone's clock is set automatically.",
                code="wrong_code",
            )
        return code


class SignInCodeForm(forms.Form):
    """Step 2 of signing in: a code from the authenticator app, or a recovery code.

    The check is ``security.check_sign_in_code``, which also counts a
    wrong code toward the cooldown and, after too many, drops the
    half-finished sign-in. On success ``user`` is the account to sign in.
    """

    code = forms.CharField(
        label="Authenticator or recovery code",
        max_length=20,
        help_text=(
            "The six-digit code your authenticator app shows now, or one of "
            "your recovery codes."
        ),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "autocapitalize": "off",
                "spellcheck": "false",
                "autofocus": True,
            }
        ),
    )

    def __init__(self, request, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs["class"] = "input w-full font-mono"

    def clean_code(self):
        code = self.cleaned_data["code"]
        self.user = security.check_sign_in_code(self.request, code)
        if self.user is None:
            raise forms.ValidationError("That code didn't work.", code="wrong_code")
        return code


class TwoFactorSettingsForm(ReauthenticationForm):
    """When to be asked for a code, besides signing in.

    A security setting like any other, and one that can switch a
    protection off, so it always takes both the current password and a
    code, whatever the account has chosen.
    """

    purpose = "two_factor_settings"
    field_order = ["ask_at_checkout", "ask_for_security_changes"]

    ask_at_checkout = forms.BooleanField(
        label="When I place an order",
        required=False,
        help_text="The checkout page asks for a code before the order goes through.",
    )
    ask_for_security_changes = forms.BooleanField(
        label="With my password, for security changes",
        required=False,
        help_text=(
            "Changing your password, username or email, signing out other "
            "devices and replacing your recovery codes take your password "
            "and a code."
        ),
    )

    def asks_for_code(self):
        return True


class ProfileForm(forms.ModelForm):
    """The name the store greets you by, and your profile picture.

    Nothing here is a security setting, so no current password is asked
    for. The picture is a plain ``FileField`` for the same reason the
    product image form uses one: ``clean_photo`` hands it to
    ``validate_avatar``, whose refusals say what was actually wrong, and a
    valid upload arrives already cropped and scaled, ready for
    ``images.set_avatar``. Choosing a new picture wins over "remove".
    """

    photo = forms.FileField(
        label="New profile picture",
        required=False,
        help_text=(
            f"JPEG, PNG or WebP · at least {AVATAR_SIZE} pixels on each side · "
            f"up to {MAX_FILE_MB} MB. It's cropped to a square from the middle."
        ),
    )
    remove_photo = forms.BooleanField(label="Remove my profile picture", required=False)

    class Meta:
        model = User
        fields = ("first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.avatar:
            del self.fields["remove_photo"]
        for field in self.fields.values():
            field.widget.attrs["class"] = "input w-full"
        self.fields["photo"].widget.attrs.update(
            {"class": "file-input w-full", "accept": "image/jpeg,image/png,image/webp"}
        )
        if "remove_photo" in self.fields:
            self.fields["remove_photo"].widget.attrs["class"] = "checkbox"

    def clean_photo(self):
        upload = self.cleaned_data["photo"]
        return validate_avatar(upload) if upload else None

    def save(self):
        user = super().save()
        if self.cleaned_data["photo"]:
            images.set_avatar(user, self.cleaned_data["photo"])
        elif self.cleaned_data.get("remove_photo"):
            images.remove_avatar(user)
        return user


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
