from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, RedirectURLMixin
from django.contrib.auth.views import PasswordChangeView as DjangoPasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import NON_FIELD_ERRORS
from django.http import HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from . import security
from .forms import (
    AddressForm,
    ChangeEmailForm,
    ChangeUsernameForm,
    PasswordChangeForm,
    PasswordResetForm,
    ProfileForm,
    RecoveryCodesForm,
    ResetPasswordForm,
    SignInCodeForm,
    SignInForm,
    SignOutDeviceForm,
    SignOutOthersForm,
    SignupForm,
    TwoFactorDisableForm,
    TwoFactorSettingsForm,
    TwoFactorSetupForm,
)
from .models import Address, SecurityEvent, TwoFactorDevice


class SignupView(SuccessMessageMixin, CreateView):
    """Create a customer account, then hand off to the login page.

    New users sign in themselves — auto-login after signup is left as a
    student exercise.
    """

    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("accounts:login")
    success_message = (
        "Account created — you can now sign in. We've emailed you a link "
        "to confirm your address."
    )

    def form_valid(self, form):
        response = super().form_valid(form)
        security.record_event(
            SecurityEvent.Kind.SIGN_UP,
            self.object,
            actor=self.object,
            request=self.request,
        )
        security.send_verification_email(self.object, self.request)
        return response


def _with_next(url, next_url):
    """``url``, carrying ``next_url`` along as ``?next=`` when there is one."""
    if not next_url:
        return url
    query = QueryDict(mutable=True)
    query[REDIRECT_FIELD_NAME] = next_url
    return f"{url}?{query.urlencode(safe='/')}"


class SignInView(LoginView):
    """Sign in, and say how many attempts are left after a refusal.

    The count shown is this browser's, kept by ``accounts.security``
    against whatever was typed. It is never the account's own, which
    would tell a stranger which usernames exist.

    For an account with two-factor on, a correct password is only step 1:
    nobody is signed in, and the browser goes on to ``SignInCodeView``
    with ``next`` carried along.
    """

    template_name = "accounts/login.html"
    authentication_form = SignInForm

    def form_valid(self, form):
        user = form.get_user()
        if user.two_factor_enabled:
            security.begin_two_factor_sign_in(
                self.request.session, user, form.cleaned_data["username"]
            )
            return HttpResponseRedirect(
                _with_next(reverse("accounts:login_verify"), self.get_redirect_url())
            )
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


@method_decorator(
    [sensitive_post_parameters("code"), csrf_protect, never_cache], name="dispatch"
)
class SignInCodeView(RedirectURLMixin, FormView):
    """Step 2 of signing in: a code, for an account that passed the password.

    Reachable only while ``accounts.security`` holds a half-finished
    sign-in for this browser; otherwise, or once it has timed out, the
    browser is sent back to the password. A working code signs in and
    follows ``next`` exactly as the password page would have.

    The person here has already given the right password, so after a
    wrong code they may be told how many tries are left before sign-in
    pauses, and that it has paused; the password page never says so.
    """

    form_class = SignInCodeForm
    template_name = "accounts/login_verify.html"
    next_page = settings.LOGIN_REDIRECT_URL

    def dispatch(self, request, *args, **kwargs):
        self.pending_user = security.pending_sign_in_user(request.session)
        if self.pending_user is None:
            messages.info(request, "That sign-in timed out. Enter your password again.")
            return self.back_to_password()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "request": self.request}

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            next=self.get_redirect_url(), password_url=self.password_url(), **kwargs
        )

    def form_valid(self, form):
        login(self.request, form.user)
        security.forget_sign_in_attempts(self.request.session)
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        standing = security.sign_in_standing(self.pending_user)
        if security.pending_sign_in_user(self.request.session) is None:
            if standing.paused_until:
                minutes = standing.paused_minutes
                messages.error(
                    self.request,
                    f"Too many failed attempts. Sign-in is paused — try again in "
                    f"{minutes} minute{pluralize(minutes)}.",
                )
            else:
                messages.error(
                    self.request, "Too many wrong codes. Enter your password again."
                )
            return self.back_to_password()
        return self.render_to_response(
            self.get_context_data(form=form, standing=standing)
        )

    def password_url(self):
        return _with_next(reverse("accounts:login"), self.get_redirect_url())

    def back_to_password(self):
        return HttpResponseRedirect(self.password_url())


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
            two_factor_device=TwoFactorDevice.objects.confirmed()
            .filter(user=user)
            .first(),
            two_factor_required=security.two_factor_required(user),
            recovery_codes_left=user.recovery_codes.unused().count(),
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


class EditProfileView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Your name and profile picture: what the navbar's profile menu shows.

    Always the signed-in user's own profile; there is no pk to tamper with.
    """

    form_class = ProfileForm
    template_name = "accounts/edit_profile.html"
    success_url = reverse_lazy("accounts:account")
    success_message = "Profile saved."

    def get_object(self, queryset=None):
        return self.request.user


class ChangeUsernameView(LoginRequiredMixin, FormView):
    """Rename the account, after the current password.

    The username plays no part in the session auth hash, so this session
    and every other one stay signed in. Recording and the alert are
    ``accounts.security``'s.
    """

    form_class = ChangeUsernameForm
    template_name = "accounts/change_username.html"
    success_url = reverse_lazy("accounts:account")

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def form_valid(self, form):
        old_username = self.request.user.get_username()
        user = form.save()
        security.username_changed(user, old_username, request=self.request)
        messages.success(
            self.request, f"Username changed. You're now {user.get_username()}."
        )
        return super().form_valid(form)


class ChangeEmailView(LoginRequiredMixin, FormView):
    """Ask for a new email address, after the current password.

    Nothing changes here: a confirmation link goes to the new address, and
    the old one stays in effect until it is followed. Sending and
    recording are ``accounts.security``'s.
    """

    form_class = ChangeEmailForm
    template_name = "accounts/change_email.html"
    success_url = reverse_lazy("accounts:account")

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def form_valid(self, form):
        new_email = form.cleaned_data["email"]
        security.request_email_change(
            self.request.user, new_email, request=self.request
        )
        current = self.request.user.email
        messages.success(
            self.request,
            f"We've sent a confirmation link to {new_email}. "
            + (
                f"Your email stays {current} until you follow it."
                if current
                else "Your email is added once you follow it."
            ),
        )
        return super().form_valid(form)


class ConfirmEmailChangeView(TemplateView):
    """Switch to a new email address from the link that was mailed to it.

    No sign-in is needed: the token is the proof. As with verification,
    GET only shows the change behind a button, so a mail scanner fetching
    the link changes nothing; the POST from that button makes the change.
    """

    template_name = "accounts/confirm_email_change.html"

    def dispatch(self, request, *args, **kwargs):
        self.change = security.email_change_for_token(kwargs["token"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            change=self.change,
            available=self.change is not None and self.change.is_available(),
            **kwargs,
        )

    def post(self, request, *args, **kwargs):
        if self.change is None or not security.change_email(
            self.change.user, self.change.new_email, request=request
        ):
            return self.get(request, *args, **kwargs)
        messages.success(request, f"Your email address is now {self.change.new_email}.")
        if request.user.is_authenticated:
            return redirect("accounts:account")
        return redirect("accounts:login")


class SendVerificationView(LoginRequiredMixin, View):
    """Email the signed-in user a fresh link to confirm their address.

    POST only; the Account page's "resend link" button is a form.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        user = request.user
        if user.email_verified:
            messages.info(request, "Your email address is already confirmed.")
        elif security.send_verification_email(user, request):
            messages.success(
                request, f"We've sent a confirmation link to {user.email}."
            )
        else:
            messages.warning(request, "Your account has no email address to confirm.")
        return redirect("accounts:account")


class VerifyEmailView(TemplateView):
    """Confirm an email address from the link that was mailed to it.

    No sign-in is needed: the token is the proof. GET only shows what
    would be confirmed, behind a button, because mail scanners fetch links
    to look at them; only the POST from that button verifies.
    """

    template_name = "accounts/verify_email.html"

    def dispatch(self, request, *args, **kwargs):
        self.target = security.user_for_verification_token(kwargs["token"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(target=self.target, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.target is None:
            return self.get(request, *args, **kwargs)
        security.mark_email_verified(self.target, request=request)
        messages.success(request, f"Thanks — {self.target.email} is confirmed.")
        if request.user.is_authenticated:
            return redirect("accounts:account")
        return redirect("accounts:login")


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


# --- Two-factor authentication ----------------------------------------------


@method_decorator(never_cache, name="dispatch")
class TwoFactorSetupView(LoginRequiredMixin, FormView):
    """Turn two-factor on: scan the QR code, then enter a working code.

    Opening the page gives the account a pending device, and two-factor
    is on only once a code from it checks out. The QR code and setup key
    are shown only while setup is pending; once it's on, this page sends
    the user back to their Account page. No current password is asked
    for (see ``TwoFactorSetupForm``).

    Success doesn't redirect: the recovery codes are rendered into the
    response itself, are never stored in plain text, and so can't be
    shown again. Nothing here may be cached, by the browser or anyone.
    """

    form_class = TwoFactorSetupForm
    template_name = "accounts/two_factor_setup.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.device = security.pending_two_factor_device(request.user)
            if self.device is None:
                messages.info(request, "Two-factor authentication is already on.")
                return redirect("accounts:account")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "device": self.device}

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            # segno's own SVG, built from the secret: no user input reaches it.
            qr_svg=mark_safe(security.provisioning_qr_svg(self.device)),
            setup_key=security.setup_key(self.device),
            required=security.two_factor_required(self.request.user),
            **kwargs,
        )

    def form_valid(self, form):
        codes = security.enable_two_factor(self.device, request=self.request)
        messages.success(self.request, "Two-factor authentication is on.")
        return render(
            self.request, "accounts/recovery_codes_issued.html", {"codes": codes}
        )


class TwoFactorOnMixin(LoginRequiredMixin):
    """For pages that manage two-factor: only for accounts with it on.

    Anyone else is sent to their Account page with ``two_factor_off_message``.
    The account's confirmed device is ``self.device``.
    """

    two_factor_off_message = "Turn on two-factor authentication first."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.device = (
                TwoFactorDevice.objects.confirmed().filter(user=request.user).first()
            )
            if self.device is None:
                messages.info(request, self.two_factor_off_message)
                return redirect("accounts:account")
        return super().dispatch(request, *args, **kwargs)


class TwoFactorSettingsView(TwoFactorOnMixin, FormView):
    """Choose when to be asked for a code, besides signing in.

    Saving takes the current password and a code (see
    ``TwoFactorSettingsForm``). Recording and the alert are
    ``accounts.security``'s.
    """

    form_class = TwoFactorSettingsForm
    template_name = "accounts/two_factor_settings.html"
    success_url = reverse_lazy("accounts:account")

    def get_initial(self):
        return {
            "ask_at_checkout": self.device.ask_at_checkout,
            "ask_for_security_changes": self.device.ask_for_security_changes,
        }

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def form_valid(self, form):
        changed = security.update_two_factor_settings(
            self.request.user,
            ask_at_checkout=form.cleaned_data["ask_at_checkout"],
            ask_for_security_changes=form.cleaned_data["ask_for_security_changes"],
            request=self.request,
        )
        if changed:
            messages.success(self.request, "Two-factor settings saved.")
        else:
            messages.info(self.request, "Nothing changed.")
        return super().form_valid(form)


@method_decorator(never_cache, name="dispatch")
class RecoveryCodesView(TwoFactorOnMixin, FormView):
    """Replace the recovery codes with a new set, after the current password.

    As with setup, success doesn't redirect: the new codes are rendered
    into the response itself and can't be shown again, so nothing here
    may be cached. Recording and the alert are ``accounts.security``'s.
    """

    form_class = RecoveryCodesForm
    template_name = "accounts/recovery_codes.html"

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            codes_left=self.request.user.recovery_codes.unused().count(), **kwargs
        )

    def form_valid(self, form):
        codes = security.regenerate_recovery_codes(
            self.request.user, request=self.request
        )
        messages.success(self.request, "New recovery codes made.")
        return render(
            self.request,
            "accounts/recovery_codes_issued.html",
            {"codes": codes, "replaced": True},
        )


class TwoFactorDisableView(TwoFactorOnMixin, FormView):
    """Turn two-factor off, after the current password and a code.

    Superusers are refused, the page and its POST alike: two-factor is
    mandatory for them. Removing the device and codes, recording and the
    alert are ``accounts.security``'s.
    """

    form_class = TwoFactorDisableForm
    template_name = "accounts/two_factor_disable.html"
    success_url = reverse_lazy("accounts:account")
    two_factor_off_message = "Two-factor authentication is already off."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and security.two_factor_required(request.user):
            messages.error(
                request,
                "Two-factor authentication is required for administrator "
                "accounts, so it can't be turned off.",
            )
            return redirect("accounts:account")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "request": self.request,
        }

    def form_valid(self, form):
        security.disable_two_factor(self.request.user, request=self.request)
        messages.success(self.request, "Two-factor authentication is off.")
        return super().form_valid(form)


# --- Resetting a forgotten password -----------------------------------------
#
# Django's own reset views, restyled. Each one names its namespaced next
# page and email template: Django's defaults point at un-namespaced URL
# names that this project doesn't have. The token generator is Django's
# too, so a link works once, dies when the password changes, and lasts
# ``PASSWORD_RESET_TIMEOUT``. None of these pages needs a sign-in.


class PasswordResetView(auth_views.PasswordResetView):
    """Ask for a reset link by email.

    Every address gets the same redirect to the same "check your inbox"
    page, whether or not an account uses it, so the form can't be used to
    find out who shops here.
    """

    form_class = PasswordResetForm
    template_name = "accounts/password_reset.html"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    email_template_name = "accounts/email/password_reset.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    @property
    def extra_email_context(self):
        return {"hours": settings.PASSWORD_RESET_TIMEOUT // 3600}


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Choose a new password from a reset link, then sign in afresh.

    Django's view moves the token out of the URL into the session before
    showing the form, so GET changes nothing. Saving the password ends
    every session; the user is deliberately not signed in afterwards.
    Recording and the alert are ``accounts.security``'s.
    """

    form_class = ResetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        security.password_reset_completed(form.user, request=self.request)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


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
