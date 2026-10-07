from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Address, SecurityEvent, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = (
        *DjangoUserAdmin.fieldsets,
        ("ThoughtTronix", {"fields": ("job_title",)}),
    )
    list_display = ("username", "email", "job_title", "is_staff")


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
