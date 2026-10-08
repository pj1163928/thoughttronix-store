from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from . import security
from .models import Address, SecurityEvent, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Django's user admin, plus the superuser overrides.

    Overrides are admin actions gated on ``is_superuser`` alone, so no
    model permission can hand them to other staff. Each one skips the
    acting admin's own account and every superuser (see
    ``security.overridable``), and the security work is
    ``accounts.security``'s.
    """

    fieldsets = (
        *DjangoUserAdmin.fieldsets,
        ("ThoughtTronix", {"fields": ("job_title", "email_verified_at")}),
    )
    readonly_fields = ("email_verified_at",)
    list_display = ("username", "email", "email_verified", "job_title", "is_staff")
    actions = ["mark_email_verified"]

    def has_override_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    @admin.display(boolean=True, description="Email verified")
    def email_verified(self, obj):
        return obj.email_verified

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
