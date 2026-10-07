from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.views import PasswordChangeView as DjangoPasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import NON_FIELD_ERRORS
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    UpdateView,
)

from . import security
from .forms import (
    AddressForm,
    PasswordChangeForm,
    SignInForm,
    SignOutDeviceForm,
    SignOutOthersForm,
    SignupForm,
)
from .models import Address, SecurityEvent


class SignupView(SuccessMessageMixin, CreateView):
    """Create a customer account, then hand off to the login page.

    New users sign in themselves — auto-login after signup is left as a
    student exercise.
    """

    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("accounts:login")
    success_message = "Account created — you can now sign in."

    def form_valid(self, form):
        response = super().form_valid(form)
        security.record_event(
            SecurityEvent.Kind.SIGN_UP,
            self.object,
            actor=self.object,
            request=self.request,
        )
        return response


class SignInView(LoginView):
    """Sign in, and say how many attempts are left after a refusal.

    The count shown is this browser's, kept by ``accounts.security``
    against whatever was typed. It is never the account's own, which
    would tell a stranger which usernames exist.
    """

    template_name = "accounts/login.html"
    authentication_form = SignInForm

    def form_valid(self, form):
        security.forget_sign_in_attempts(self.request.session)
        return super().form_valid(form)

    def form_invalid(self, form):
        standing = None
        if form.has_error(NON_FIELD_ERRORS, "invalid_login"):
            standing = security.note_refused_sign_in(
                self.request.session, form.cleaned_data["username"]
            )
        return self.render_to_response(
            self.get_context_data(form=form, standing=standing)
        )


class SignOutView(LogoutView):
    def post(self, request, *args, **kwargs):
        # Flash after super() has flushed the session, or the message
        # would be wiped along with it.
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You have signed out.")
        return response


# --- The Account page -------------------------------------------------------


class AccountView(LoginRequiredMixin, FormView):
    """The account at a glance: one card per thing that can be checked.

    Each card that can change something links to its own small page. The
    one form shown here, "Sign out of all other devices", posts to
    ``SignOutOthersView``, which renders this same page when the password
    is wrong. The activity card shows the user's own events and nobody
    else's, newest first.
    """

    template_name = "accounts/account.html"
    form_class = SignOutOthersForm
    success_url = reverse_lazy("accounts:account")
    activity_limit = 10
    http_method_names = ["get", "head", "options"]

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def get_context_data(self, **kwargs):
        user = self.request.user
        return super().get_context_data(
            password_last_changed=user.password_last_changed,
            address_count=user.addresses.count(),
            user_sessions=user.user_sessions.active(),
            current_session_id=security.current_session_id(self.request),
            events=user.security_events.all()[: self.activity_limit],
            **kwargs,
        )


class SignOutOthersView(AccountView):
    """End every session but this one, after the current password."""

    http_method_names = ["post"]

    def form_valid(self, form):
        security.sign_out_other_sessions(self.request.user, self.request)
        messages.success(self.request, "You've been signed out on every other device.")
        return super().form_valid(form)


class SignOutDeviceView(LoginRequiredMixin, FormView):
    """Sign one other device out, after the current password.

    Only the owner's own devices are found, and never this one — signing
    out here is what the navbar's "Sign out" is for.
    """

    form_class = SignOutDeviceForm
    template_name = "accounts/device_sign_out.html"
    success_url = reverse_lazy("accounts:account")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.user_session = get_object_or_404(
                request.user.user_sessions.active().exclude(
                    pk=security.current_session_id(request)
                ),
                pk=kwargs["pk"],
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def get_context_data(self, **kwargs):
        return super().get_context_data(user_session=self.user_session, **kwargs)

    def form_valid(self, form):
        security.sign_out_session(
            self.request.user, self.user_session, request=self.request
        )
        messages.success(self.request, f"Signed out {self.user_session.label}.")
        return super().form_valid(form)


class PasswordChangeView(DjangoPasswordChangeView):
    """Change the password, staying signed in here and nowhere else.

    Django's view saves the password and keeps this session; the new
    password has already ended every other one. Recording and the alert
    are ``accounts.security``'s.
    """

    form_class = PasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:account")

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "request": self.request}

    def form_valid(self, form):
        response = super().form_valid(form)
        security.password_changed(form.user, request=self.request)
        messages.success(
            self.request,
            "Password changed. Every other device has been signed out.",
        )
        return response


# --- The address book -------------------------------------------------------
#
# A customer's saved addresses, reusable at checkout. Thin views over
# ``Address`` and ``AddressForm``; every default and every promotion is
# decided on the model.


class OwnAddressesMixin(LoginRequiredMixin):
    """Addresses are always fetched through the owner — never by bare pk."""

    model = Address
    success_url = reverse_lazy("accounts:addresses")

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)


class AddressListView(OwnAddressesMixin, ListView):
    template_name = "accounts/address_list.html"
    context_object_name = "addresses"

    def get_queryset(self):
        return super().get_queryset().order_by("label")


class AddressCreateView(OwnAddressesMixin, SuccessMessageMixin, CreateView):
    form_class = AddressForm
    template_name = "accounts/address_form.html"
    success_message = "Address saved."

    def form_valid(self, form):
        # Set before the form saves: ``AddressForm.save`` needs an owner
        # to decide whether this is the customer's first address.
        form.instance.user = self.request.user
        return super().form_valid(form)


class AddressUpdateView(OwnAddressesMixin, SuccessMessageMixin, UpdateView):
    form_class = AddressForm
    template_name = "accounts/address_form.html"
    success_message = "Address updated."


class AddressDeleteView(OwnAddressesMixin, SuccessMessageMixin, DeleteView):
    template_name = "accounts/address_confirm_delete.html"
    context_object_name = "address"
    success_message = "Address deleted."
