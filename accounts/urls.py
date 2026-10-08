from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.AccountView.as_view(), name="account"),
    path("profile/", views.EditProfileView.as_view(), name="edit_profile"),
    path("username/", views.ChangeUsernameView.as_view(), name="change_username"),
    path("email/", views.ChangeEmailView.as_view(), name="change_email"),
    # Sent to the new address; the token is the proof, so no sign-in.
    path(
        "email/confirm/<str:token>/",
        views.ConfirmEmailChangeView.as_view(),
        name="confirm_email_change",
    ),
    path(
        "email/verify/",
        views.SendVerificationView.as_view(),
        name="send_verification",
    ),
    # The token is the proof, so no sign-in; GET only shows a button.
    path(
        "email/verify/<str:token>/",
        views.VerifyEmailView.as_view(),
        name="verify_email",
    ),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    # A forgotten password: no sign-in on any of these.
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password/reset/complete/",
        views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("2fa/setup/", views.TwoFactorSetupView.as_view(), name="two_factor_setup"),
    path(
        "2fa/settings/",
        views.TwoFactorSettingsView.as_view(),
        name="two_factor_settings",
    ),
    path(
        "2fa/disable/", views.TwoFactorDisableView.as_view(), name="two_factor_disable"
    ),
    path(
        "2fa/recovery-codes/",
        views.RecoveryCodesView.as_view(),
        name="recovery_codes",
    ),
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
    # Only while a password has passed and a code is still owed.
    path("login/verify/", views.SignInCodeView.as_view(), name="login_verify"),
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
