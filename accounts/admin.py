from django import forms
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.core.exceptions import PermissionDenied
from django.db.models import Case, DateTimeField, Exists, OuterRef, Q, Value, When
from django.utils import timezone

from . import security
from .models import Address, SecurityEvent, TwoFactorDevice, User

# On a superuser's change page these can't be edited, by anyone: no admin
# can quietly take over another, and superusers change their own account
# from the Account page. The password is shown as ``password_locked``.
SUPERUSER_LOCKED_FIELDS = ("username", "email", "is_active")


class UserChangeForm(DjangoUserChangeForm):
    """Django's user change form, which can change an email but not remove it."""

    def clean_email(self):
        email = self.cleaned_data["email"]
        if not email and self.initial.get("email"):
            raise forms.ValidationError(
                "An email address can be changed here but not removed: it is "
                "how the owner gets back into their account."
            )
        return email


class YesNoFilter(admin.SimpleListFilter):
    """A Yes/No filter on one condition, given as ``matches``."""

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(self.matches)
        if self.value() == "no":
            return queryset.exclude(self.matches)
        return queryset


class EmailVerifiedFilter(YesNoFilter):
    title = "email verified"
    parameter_name = "email_verified"
    # ``User.email_verified`` as a query: an account with no email isn't.
    matches = Q(email_verified_at__isnull=False) & ~Q(email="")


class TwoFactorFilter(YesNoFilter):
    title = "two-factor"
    parameter_name = "two_factor"
    matches = Q(two_factor_on=True)


class SignInFilter(admin.SimpleListFilter):
    """Whether each account is locked, paused, or free to sign in."""

    title = "sign-in"
    parameter_name = "sign_in"

    def lookups(self, request, model_admin):
        return (("locked", "Locked"), ("paused", "Paused"), ("allowed", "Allowed"))

    def queryset(self, request, queryset):
        match self.value():
            case "locked":
                return queryset.filter(is_active=False)
            case "paused":
                return queryset.filter(sign_in_paused_until__isnull=False)
            case "allowed":
                return queryset.filter(
                    is_active=True, sign_in_paused_until__isnull=True
                )
        return queryset


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Django's user admin, plus the superuser overrides.

    Overrides are admin actions gated on ``is_superuser`` alone, so no
    model permission can hand them to other staff: mark email verified,
    reset two-factor, clear sign-in cooldown, lock, unlock and send a
    password reset link. Each one skips the acting admin's own account
    and every superuser (see ``security.overridable``), and the security
    work, the audit event and the owner's email are
    ``accounts.security``'s.

    Superusers also see each account's security state as list columns
    and filters: email verified, two-factor on, and whether sign-in is
    locked or paused. Other staff see Django's list unchanged.

    The change page edits an account directly, and the security fields
    go through ``accounts.security`` with the editor as actor, exactly as
    the owner's own changes do: a new username or email takes effect at
    once (the email counted as verified, the old address told), ticking
    "Active" off or on locks or unlocks, and Django's set-password form is
    recorded and alerted. On a superuser's change page, the acting
    admin's own included, none of those can be edited at all.
    """

    form = UserChangeForm
    fieldsets = (
        *DjangoUserAdmin.fieldsets,
        ("ThoughtTronix", {"fields": ("job_title", "email_verified_at")}),
    )
    readonly_fields = ("email_verified_at",)
    list_display = ("username", "email", "job_title", "is_staff")
    actions = [
        "mark_email_verified",
        "reset_two_factor",
        "clear_cooldown",
        "lock_account",
        "unlock_account",
        "send_password_reset",
    ]

    def has_override_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def get_queryset(self, request):
        """For superusers, annotate each account's two-factor state and pause.

        Pauses come from ``security.paused_accounts``, worked out once per
        list rather than once per row.
        """
        queryset = super().get_queryset(request)
        if not self.has_override_permission(request):
            return queryset
        paused = security.paused_accounts()
        return queryset.annotate(
            two_factor_on=Exists(
                TwoFactorDevice.objects.confirmed().filter(user=OuterRef("pk"))
            ),
            sign_in_paused_until=Case(
                *(When(pk=pk, then=Value(until)) for pk, until in paused.items()),
                default=Value(None),
                output_field=DateTimeField(),
            ),
        )

    def get_list_display(self, request):
        if not self.has_override_permission(request):
            return self.list_display
        return (
            "username",
            "email",
            "email_verified",
            "two_factor",
            "sign_in",
            "job_title",
            "is_staff",
        )

    def get_list_filter(self, request):
        if not self.has_override_permission(request):
            return self.list_filter
        # The sign-in filter's "Locked" stands in for Django's "Active".
        return (
            "is_staff",
            "is_superuser",
            EmailVerifiedFilter,
            TwoFactorFilter,
            SignInFilter,
            "groups",
        )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and obj.is_superuser:
            return (*fields, *SUPERUSER_LOCKED_FIELDS, "password_locked")
        return fields

    def get_fieldsets(self, request, obj=None):
        """On a superuser's page, the password row loses its set-password button.

        A read-only ``password`` would print the raw hash, so the row shows
        ``password_locked`` in its place.
        """
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None or not obj.is_superuser:
            return fieldsets
        return [
            (
                name,
                {
                    **options,
                    "fields": [
                        "password_locked" if field == "password" else field
                        for field in options["fields"]
                    ],
                },
            )
            for name, options in fieldsets
        ]

    @admin.display(description="Password")
    def password_locked(self, obj):
        return "Superusers change their own password, from their Account page."

    def save_model(self, request, obj, form, change):
        """Save an edit, with username, email and "Active" applied by ``security``.

        The form has already checked the identity rules (no ``@``, unique
        in any case). The email and "Active" are put back before saving,
        because ``security.change_email``, ``lock_account`` and
        ``unlock_account`` apply them themselves; each records its event
        with the editor as actor and emails the owner.
        """
        if not change:
            super().save_model(request, obj, form, change)
            return
        changed = set(form.changed_data)
        new_email, active = obj.email, obj.is_active
        for field in changed & {"email", "is_active"}:
            setattr(obj, field, form.initial[field])
        super().save_model(request, obj, form, change)
        actor = request.user
        if "username" in changed:
            security.username_changed(
                obj, form.initial["username"], actor=actor, request=request
            )
        if "email" in changed and not security.change_email(
            obj, new_email, actor=actor, request=request
        ):
            self.message_user(
                request,
                f"{new_email} was taken by another account meanwhile, so the "
                f"email is unchanged.",
                messages.ERROR,
            )
        if "is_active" in changed:
            apply = security.unlock_account if active else security.lock_account
            apply(obj, actor=actor, request=request)

    def user_change_password(self, request, id, form_url=""):
        """Django's set-password page, refused for superusers and recorded.

        A superuser's password, the acting admin's own included, is
        changed only from their own Account page. For anyone else a new
        password is recorded and the owner alerted; it is told apart from
        a form that didn't save by the stored hash having changed.
        """
        user = self.get_object(request, unquote(id))
        if user is not None and user.is_superuser:
            raise PermissionDenied
        before = user.password if user is not None else None
        response = super().user_change_password(request, id, form_url)
        if user is not None and request.method == "POST":
            user.refresh_from_db(fields=["password"])
            if user.password != before:
                security.password_set_by_support(
                    user, actor=request.user, request=request
                )
        return response

    @admin.display(
        boolean=True, description="Email verified", ordering="email_verified_at"
    )
    def email_verified(self, obj):
        return obj.email_verified

    @admin.display(boolean=True, description="Two-factor", ordering="two_factor_on")
    def two_factor(self, obj):
        return obj.two_factor_on

    @admin.display(description="Sign-in")
    def sign_in(self, obj):
        """ "Locked", "Paused until 14:32", or blank when sign-in is allowed."""
        if not obj.is_active:
            return "Locked"
        if obj.sign_in_paused_until is not None:
            return f"Paused until {timezone.localtime(obj.sign_in_paused_until):%H:%M}"
        return None

    @admin.action(description="Mark email verified", permissions=["override"])
    def mark_email_verified(self, request, queryset):
        self._override(
            request,
            queryset,
            security.mark_email_verified,
            done="Marked verified",
            unchanged="Already verified or no email, so left alone",
        )

    @admin.action(description="Reset two-factor", permissions=["override"])
    def reset_two_factor(self, request, queryset):
        self._override(
            request,
            queryset,
            security.reset_two_factor,
            done="Two-factor reset",
            unchanged="Two-factor wasn't on, so left alone",
        )

    @admin.action(description="Clear sign-in cooldown", permissions=["override"])
    def clear_cooldown(self, request, queryset):
        self._override(
            request,
            queryset,
            security.clear_cooldown,
            done="Cooldown cleared",
            unchanged="No failed sign-ins to clear, so left alone",
        )

    @admin.action(description="Lock account", permissions=["override"])
    def lock_account(self, request, queryset):
        self._override(
            request,
            queryset,
            security.lock_account,
            done="Locked",
            unchanged="Already locked, so left alone",
        )

    @admin.action(description="Unlock account", permissions=["override"])
    def unlock_account(self, request, queryset):
        self._override(
            request,
            queryset,
            security.unlock_account,
            done="Unlocked",
            unchanged="Not locked, so left alone",
        )

    @admin.action(description="Send password reset link", permissions=["override"])
    def send_password_reset(self, request, queryset):
        self._override(
            request,
            queryset,
            security.send_password_reset,
            done="Reset link sent",
            unchanged="No email or locked, so no link sent",
        )

    def _override(self, request, queryset, apply, *, done, unchanged):
        """Apply one override to every selected account it may touch, and report.

        ``apply`` is the ``accounts.security`` function, called with the
        admin as actor; it returns whether it changed anything. The
        message names who was changed, who was left alone, and who was
        skipped by the guardrail.
        """
        allowed, skipped = security.overridable(request.user, queryset)
        changed = [
            user for user in allowed if apply(user, actor=request.user, request=request)
        ]
        self._report(request, done, changed)
        self._report(
            request,
            unchanged,
            [user for user in allowed if user not in changed],
            messages.INFO,
        )
        self._report(
            request,
            "Skipped — overrides never apply to your own account or a superuser's",
            skipped,
            messages.WARNING,
        )

    def _report(self, request, what, users, level=messages.SUCCESS):
        if users:
            names = ", ".join(user.get_username() for user in users)
            self.message_user(request, f"{what}: {names}.", level)


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "city", "state", "default_for")
    list_filter = ("state", "is_default_shipping", "is_default_billing")
    search_fields = ("user__username", "label", "name", "street", "city")


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """The audit log: superusers may read it, and nobody may rewrite it.

    No add, change or delete for anyone, superusers included — a history
    an admin could edit would only record what that admin allowed it to.
    Viewing is decided by ``is_superuser`` alone, not by model
    permissions, so granting a staff member ``view_securityevent`` still
    shows them nothing.
    """

    list_display = ("created_at", "kind", "username", "actor", "ip_address")
    list_filter = (
        "kind",
        "created_at",
        ("actor", admin.RelatedOnlyFieldListFilter),
        ("user", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("username",)
    date_hierarchy = "created_at"
    list_select_related = ("actor",)
    fields = (
        "created_at",
        "kind",
        "user",
        "username",
        "actor",
        "ip_address",
        "details",
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
