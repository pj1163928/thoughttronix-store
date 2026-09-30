from django.contrib import admin

from products.admin import image_preview

from .models import Cart, CartItem, DiscountCode, Order, OrderItem


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "label",
        "status",
        "times_used",
        "per_user_limit",
        "total_limit",
        "starts_at",
        "ends_at",
    )
    list_filter = ("kind", "applies_to", "is_active")
    search_fields = ("code",)
    filter_horizontal = ("products",)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "item_count", "total")
    search_fields = ("user__username",)
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("snapshot",)

    @admin.display(description="Image at purchase")
    def snapshot(self, item):
        if item.pk is None:
            return "—"
        return image_preview(item.thumbnail)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "status", "total", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username", "shipping_name")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline]
