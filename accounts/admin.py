from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Case, DateTimeField, Exists, OuterRef, Q, Value, When
from django.utils import timezone

from . import security
from .models import Address, SecurityEvent, TwoFactorDevice, User


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
    model permission can hand them to other staff. Each one skips the
    acting admin's own account and every superuser (see
    ``security.overridable``), and the security work is
    ``accounts.security``'s.

    Superusers also see each account's security state as list columns
    and filters: email verified, two-factor on, and whether sign-in is
    locked or paused. Other staff see Django's list unchanged.
    """

    fieldsets = (
        *DjangoUserAdmin.fieldsets,
        ("ThoughtTronix", {"fields": ("job_title", "email_verified_at")}),
    )
    readonly_fields = ("email_verified_at",)
    list_display = ("username", "email", "job_title", "is_staff")
    actions = ["mark_email_verified"]

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
        allowed, skipped = security.overridable(request.user, queryset)
        verified = [
            user
            for user in allowed
            if security.mark_email_verified(user, actor=request.user, request=request)
        ]
        self._report(request, "Marked verified", verified)
        unchanged = [user for user in allowed if user not in verified]
        self._report(
            request,
            "Already verified or no email, so left alone",
            unchanged,
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
