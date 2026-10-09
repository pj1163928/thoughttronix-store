"""Signing in with a username or an email, in any capitalisation."""

import pytest
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from accounts.models import SecurityEvent

User = get_user_model()


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password="casey-pass-123", email="Casey@Example.com"
    )


def sign_in(client, identifier, password):
    return client.post(
        reverse("accounts:login"), {"username": identifier, "password": password}
    )


def signed_in_user(client):
    return User.objects.get(pk=client.session["_auth_user_id"])


# --- Which identifiers work ---------------------------------------------------


@pytest.mark.parametrize(
    "identifier",
    [
        "casey",
        "CASEY",
        "Casey",
        "Casey@Example.com",
        "casey@example.com",
        "CASEY@EXAMPLE.COM",
    ],
)
def test_signs_in_with_username_or_email_in_any_case(client, casey, identifier):
    response = sign_in(client, identifier, "casey-pass-123")

    assert response.status_code == 302
    assert signed_in_user(client) == casey


@pytest.mark.parametrize("identifier", ["casey", "casey@example.com"])
def test_wrong_password_is_refused_either_way(client, casey, identifier):
    response = sign_in(client, identifier, "wrong")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_an_unknown_identifier_is_refused(client, casey):
    response = sign_in(client, "nobody@example.com", "casey-pass-123")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_a_blank_email_never_matches_an_account_without_one(db):
    # Older accounts have "" as their email. A blank identifier must not
    # pick one of them.
    User.objects.create_user(username="legacy", password="legacy-pass-123")

    assert authenticate(None, username="", password="legacy-pass-123") is None


def test_one_users_email_does_not_open_another_users_account(client, casey):
    User.objects.create_user(
        username="dana", password="dana-pass-123", email="dana@example.com"
    )

    sign_in(client, "dana@example.com", "casey-pass-123")

    assert "_auth_user_id" not in client.session


def test_a_failure_by_email_is_recorded_against_the_account(client, casey):
    # The cooldown counts failures per account, so a wrong password typed
    # against the email must land on the same account as one typed
    # against the username.
    sign_in(client, "CASEY@example.com", "wrong")

    event = SecurityEvent.objects.get(kind=SecurityEvent.Kind.SIGN_IN_FAILED)
    assert event.user == casey


# --- Locked accounts ----------------------------------------------------------


def test_an_inactive_user_gets_the_wrong_password_message(client, casey):
    wrong = sign_in(client, "casey", "wrong").context["form"].non_field_errors()

    casey.is_active = False
    casey.save()
    locked = sign_in(client, "casey", "casey-pass-123")

    assert "_auth_user_id" not in client.session
    assert locked.context["form"].non_field_errors() == wrong


def test_an_inactive_user_is_refused_by_email_too(client, casey):
    casey.is_active = False
    casey.save()

    sign_in(client, "casey@example.com", "casey-pass-123")

    assert "_auth_user_id" not in client.session


# --- Permissions behave as before ---------------------------------------------


def test_the_custom_backend_replaces_model_backend():
    assert settings.AUTHENTICATION_BACKENDS == [
        "accounts.backends.UsernameOrEmailBackend"
    ]


def test_a_superuser_has_every_permission(db):
    admin = User.objects.create_superuser(username="admin", password="admin-pass-123")

    assert admin.has_perm("products.delete_product")
    assert admin.has_module_perms("orders")


def test_a_granted_permission_is_honoured_and_others_are_not(staff_user):
    staff_user.user_permissions.add(Permission.objects.get(codename="change_product"))
    staff_user = User.objects.get(pk=staff_user.pk)  # drop the perm cache

    assert staff_user.has_perm("products.change_product")
    assert not staff_user.has_perm("products.delete_product")


def test_an_inactive_superuser_has_no_permissions(db):
    admin = User.objects.create_superuser(
        username="admin", password="admin-pass-123", is_active=False
    )

    assert not admin.has_perm("products.delete_product")


def test_staff_can_sign_in_to_the_admin_by_email(client, db):
    # Staff rather than a superuser, who would owe two-factor setup first.
    User.objects.create_user(
        username="admin",
        password="admin-pass-123",
        email="admin@example.com",
        is_staff=True,
    )

    response = client.post(
        reverse("accounts:login"),
        {
            "username": "ADMIN@example.com",
            "password": "admin-pass-123",
            "next": reverse("admin:index"),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("admin:index")
    assert client.get(reverse("admin:index")).status_code == 200


def test_the_admin_sign_in_page_sends_you_to_the_stores(client, db):
    # The admin's own page signs in on a password alone, which would skip
    # the two-factor code step.
    response = client.get(reverse("admin:index"), follow=True)

    assert response.request["PATH_INFO"] == reverse("accounts:login")
    assert response.context["next"] == reverse("admin:index")
    assert "accounts/login.html" in [t.name for t in response.templates]


def test_posting_to_the_admin_sign_in_page_signs_nobody_in(client, db):
    User.objects.create_superuser(username="admin", password="admin-pass-123")

    client.post(
        reverse("admin:login"), {"username": "admin", "password": "admin-pass-123"}
    )

    assert "_auth_user_id" not in client.session
    assert not SecurityEvent.objects.exists()


def test_a_signed_in_session_survives_the_next_request(client, casey):
    # The session stores the backend's dotted path; get_user must find it.
    sign_in(client, "casey@example.com", "casey-pass-123")

    response = client.get(reverse("accounts:addresses"))

    assert response.status_code == 200
    assert response.context["user"] == casey


# --- The page -----------------------------------------------------------------


def test_the_field_is_labelled_username_or_email(client, db):
    form = client.get(reverse("accounts:login")).context["form"]

    assert form.fields["username"].label == "Username or email"
    assert "Username or email" in client.get(reverse("accounts:login")).content.decode()


def test_the_field_is_long_enough_for_any_email(client, db):
    # Usernames stop at 150 characters, emails at 254.
    form = client.get(reverse("accounts:login")).context["form"]

    assert form.fields["username"].widget.attrs["maxlength"] == 254
