from django.urls import path

from . import views

app_name = "reviews"

# Public actions use the product pk or the review pk; no URL names a reviewer.
urlpatterns = [
    path(
        "reviews/product/<int:pk>/create/",
        views.CreateReviewView.as_view(),
        name="create",
    ),
    path("reviews/product/<int:pk>/", views.ReviewListView.as_view(), name="list"),
    path("reviews/<int:pk>/", views.ReviewDetailView.as_view(), name="detail"),
    path("reviews/<int:pk>/edit/", views.EditReviewView.as_view(), name="edit"),
    path("reviews/<int:pk>/delete/", views.DeleteReviewView.as_view(), name="delete"),
    path(
        "reviews/<int:pk>/moderate/",
        views.ModerateReviewView.as_view(),
        name="moderate",
    ),
    path("reviews/<int:pk>/remove/", views.RemoveReviewView.as_view(), name="remove"),
    path(
        "backoffice/reviews/",
        views.ManageReviewListView.as_view(),
        name="manage",
    ),
]
