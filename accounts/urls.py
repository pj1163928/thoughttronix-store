from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.AccountView.as_view(), name="account"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path(
        "sessions/sign-out-others/",
        views.SignOutOthersView.as_view(),
        name="sign_out_others",
    ),
    # One of the owner's own devices — fetched through the owner, by pk.
    path(
        "sessions/<int:pk>/sign-out/",
        views.SignOutDeviceView.as_view(),
        name="sign_out_device",
    ),
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    # The address book — a customer's own pages, so pks rather than slugs.
    path("addresses/", views.AddressListView.as_view(), name="addresses"),
    path("addresses/add/", views.AddressCreateView.as_view(), name="address_create"),
    path(
        "addresses/<int:pk>/edit/",
        views.AddressUpdateView.as_view(),
        name="address_update",
    ),
    path(
        "addresses/<int:pk>/delete/",
        views.AddressDeleteView.as_view(),
        name="address_delete",
    ),
]
