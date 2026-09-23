from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/add/<int:pk>/", views.AddToCartView.as_view(), name="add"),
    path(
        "cart/items/<int:pk>/increment/",
        views.IncrementCartItemView.as_view(),
        name="increment",
    ),
    path(
        "cart/items/<int:pk>/decrement/",
        views.DecrementCartItemView.as_view(),
        name="decrement",
    ),
    path(
        "cart/items/<int:pk>/remove/",
        views.RemoveCartItemView.as_view(),
        name="remove",
    ),
    path("cart/discount/", views.ApplyDiscountView.as_view(), name="apply_discount"),
    path(
        "cart/discount/remove/",
        views.RemoveDiscountView.as_view(),
        name="remove_discount",
    ),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("orders/", views.OrderHistoryView.as_view(), name="history"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="detail"),
    path(
        "orders/<int:pk>/confirmation/",
        views.OrderConfirmationView.as_view(),
        name="confirmation",
    ),
    # Back office — staff-only, pk URLs per the URL conventions.
    path(
        "backoffice/orders/",
        views.ManageOrderListView.as_view(),
        name="manage_orders",
    ),
    path(
        "backoffice/orders/<int:pk>/",
        views.ManageOrderDetailView.as_view(),
        name="manage_order_detail",
    ),
    path(
        "backoffice/orders/<int:pk>/status/",
        views.UpdateOrderStatusView.as_view(),
        name="manage_order_status",
    ),
    path(
        "backoffice/discounts/",
        views.ManageDiscountListView.as_view(),
        name="manage_discounts",
    ),
    path(
        "backoffice/discounts/add/",
        views.ManageDiscountCreateView.as_view(),
        name="manage_discount_create",
    ),
    path(
        "backoffice/discounts/<int:pk>/edit/",
        views.ManageDiscountUpdateView.as_view(),
        name="manage_discount_update",
    ),
    path(
        "backoffice/discounts/<int:pk>/toggle/",
        views.ToggleDiscountActiveView.as_view(),
        name="manage_discount_toggle",
    ),
    path(
        "backoffice/discounts/<int:pk>/reinstate/",
        views.ReinstateDiscountView.as_view(),
        name="manage_discount_reinstate",
    ),
]
