from django.urls import path

from . import views

app_name = "wishlist"

# No URL names a wishlist or its owner: every view serves request.user's own.
urlpatterns = [
    path("wishlist/", views.WishlistView.as_view(), name="list"),
    path("wishlist/add/<int:pk>/", views.AddToWishlistView.as_view(), name="add"),
    path(
        "wishlist/remove/<int:pk>/",
        views.RemoveFromWishlistView.as_view(),
        name="remove",
    ),
    path(
        "wishlist/items/<int:pk>/remove/",
        views.RemoveWishlistItemView.as_view(),
        name="remove_item",
    ),
]
