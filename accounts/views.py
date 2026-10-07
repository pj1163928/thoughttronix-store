from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import NON_FIELD_ERRORS
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    TemplateView,
    UpdateView,
)

from . import security
from .forms import AddressForm, SignInForm, SignupForm
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


class AccountView(LoginRequiredMixin, TemplateView):
    """The account at a glance: one card per thing that can be checked.

    Each card that can change something links to its own small page; this
    one only reads. The activity card shows the user's own events and
    nobody else's, newest first.
    """

    template_name = "accounts/account.html"
    activity_limit = 10

    def get_context_data(self, **kwargs):
        user = self.request.user
        return super().get_context_data(
            password_last_changed=user.password_last_changed,
            address_count=user.addresses.count(),
            events=user.security_events.all()[: self.activity_limit],
            **kwargs,
        )


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
