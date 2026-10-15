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
]
