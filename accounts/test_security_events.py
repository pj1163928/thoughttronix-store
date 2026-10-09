"""The security audit log: what gets recorded, and who may read it."""

import inspect
from http import HTTPStatus

import pyotp
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse

from accounts import security
from accounts.models import SecurityEvent
from products.management.commands.seed import MANAGED_USERNAMES

Kind = SecurityEvent.Kind


@pytest.fixture
def superuser(db, enrol_two_factor):
    admin = get_user_model().objects.create_superuser(
        username="admin", password="admin123", email="admin@example.com"
    )
    enrol_two_factor(admin)
    return admin


def events(kind):
    return SecurityEvent.objects.filter(kind=kind)


# --- Recording ---------------------------------------------------------------


def test_signup_records_a_sign_up_event_with_the_ip(client, db):
    client.post(
        reverse("accounts:signup"),
        {
            "username": "fresh-thinker",
            "email": "fresh@example.com",
            "password1": "neural-implant-9000",
            "password2": "neural-implant-9000",
        },
        REMOTE_ADDR="203.0.113.7",
    )

    user = get_user_model().objects.get(username="fresh-thinker")
    event = events(Kind.SIGN_UP).get()
    assert event.user == user
    assert event.actor == user
    assert event.username == "fresh-thinker"
    assert event.ip_address == "203.0.113.7"


def test_a_refused_signup_records_nothing(client, db):
    client.post(
        reverse("accounts:signup"),
        {
            "username": "fresh-thinker",
            "email": "fresh@example.com",
            "password1": "neural-implant-9000",
            "password2": "neural-implant-9001",
        },
    )

    assert not SecurityEvent.objects.exists()


def test_successful_sign_in_records_its_event(client, customer):
    client.post(
        reverse("accounts:login"),
        {"username": "customer", "password": "customer123"},
        REMOTE_ADDR="198.51.100.4",
    )

    event = events(Kind.SIGN_IN_SUCCEEDED).get()
    assert event.user == customer
    assert event.actor == customer
    assert event.ip_address == "198.51.100.4"
    assert not events(Kind.SIGN_IN_FAILED).exists()


def test_wrong_password_records_a_failure_against_the_account(client, customer):
    client.post(
        reverse("accounts:login"),
        {"username": "customer", "password": "wrong"},
        REMOTE_ADDR="198.51.100.4",
    )

    event = events(Kind.SIGN_IN_FAILED).get()
    assert event.user == customer
    assert event.username == "customer"
    # Failing to sign in proves nothing about who was typing.
    assert event.actor is None
    assert event.ip_address == "198.51.100.4"
    assert not events(Kind.SIGN_IN_SUCCEEDED).exists()


def test_unknown_identifier_failure_stores_no_identifier(client, db):
    client.post(
        reverse("accounts:login"),
        {"username": "my-secret-password", "password": "whatever"},
        REMOTE_ADDR="198.51.100.4",
    )

    event = events(Kind.SIGN_IN_FAILED).get()
    assert event.user is None
    assert event.actor is None
    assert event.username == ""
    assert event.details == {}
    assert event.ip_address == "198.51.100.4"


def test_admin_sign_in_is_recorded_too(client, superuser):
    # The admin's own sign-in page redirects here, with ``next`` set, and
    # a superuser always has two-factor, so it takes both steps.
    client.post(
        reverse("accounts:login"),
        {"username": "admin", "password": "admin123", "next": reverse("admin:index")},
    )
    code = pyotp.TOTP(superuser.two_factor_device.secret).now()
    client.post(reverse("accounts:login_verify"), {"code": code})

    assert events(Kind.SIGN_IN_SUCCEEDED).get().user == superuser


def test_ip_comes_from_remote_addr_only():
    request = RequestFactory().get(
        "/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4"
    )

    assert security.client_ip(request) == "10.0.0.5"


@pytest.mark.parametrize("remote_addr", ["", "not-an-ip", "/run/gunicorn.sock"])
def test_unusable_remote_addr_is_recorded_as_unknown(remote_addr):
    request = RequestFactory().get("/", REMOTE_ADDR=remote_addr)

    assert security.client_ip(request) is None


def test_no_request_means_no_ip(customer):
    event = security.record_event(Kind.SIGN_UP, customer, actor=customer)

    assert event.ip_address is None


def test_deleting_a_user_keeps_their_events(customer, superuser):
    security.record_event(Kind.SIGN_UP, customer, actor=customer)
    security.record_event(Kind.ACCOUNT_LOCKED, customer, actor=superuser)

    customer.delete()

    assert SecurityEvent.objects.count() == 2
    for event in SecurityEvent.objects.all():
        assert event.user is None
        assert event.username == "customer"


def test_deleting_an_actor_keeps_the_events_they_performed(customer, superuser):
    security.record_event(Kind.ACCOUNT_LOCKED, customer, actor=superuser)

    superuser.delete()

    event = SecurityEvent.objects.get()
    assert event.actor is None
    assert event.user == customer


def test_every_public_function_has_a_docstring_and_type_hints():
    public = [
        obj
        for name, obj in inspect.getmembers(security, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == security.__name__
    ]

    assert public
    for function in public:
        assert inspect.getdoc(function), function.__name__
        annotations = function.__annotations__
        assert "return" in annotations, function.__name__
        params = inspect.signature(function).parameters
        assert set(params) <= set(annotations), function.__name__


# --- The admin ---------------------------------------------------------------


@pytest.fixture
def event(customer):
    return security.record_event(Kind.SIGN_UP, customer, actor=customer)


@pytest.fixture
def event_admin():
    return admin.site._registry[SecurityEvent]


def request_as(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


def test_superuser_can_read_the_log(client, superuser, event):
    client.force_login(superuser)

    changelist = client.get(reverse("admin:accounts_securityevent_changelist"))
    detail = client.get(reverse("admin:accounts_securityevent_change", args=[event.pk]))

    assert changelist.status_code == HTTPStatus.OK
    assert "customer" in changelist.content.decode()
    assert detail.status_code == HTTPStatus.OK


def test_nobody_can_add_change_or_delete_events(superuser, event, event_admin):
    request = request_as(superuser)

    assert not event_admin.has_add_permission(request)
    assert not event_admin.has_change_permission(request, event)
    assert not event_admin.has_delete_permission(request, event)
    assert "delete_selected" not in event_admin.get_actions(request)


def test_superuser_add_and_delete_pages_are_refused(client, superuser, event):
    client.force_login(superuser)

    add = client.get(reverse("admin:accounts_securityevent_add"))
    delete = client.post(
        reverse("admin:accounts_securityevent_delete", args=[event.pk]),
        {"post": "yes"},
    )

    assert add.status_code == HTTPStatus.FORBIDDEN
    assert delete.status_code == HTTPStatus.FORBIDDEN
    assert SecurityEvent.objects.filter(pk=event.pk).exists()


def test_superuser_cannot_edit_an_event(client, superuser, event):
    client.force_login(superuser)

    response = client.post(
        reverse("admin:accounts_securityevent_change", args=[event.pk]),
        {"kind": Kind.PASSWORD_CHANGED, "username": "someone-else"},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    event.refresh_from_db()
    assert event.kind == Kind.SIGN_UP
    assert event.username == "customer"


def test_staff_cannot_see_the_log(client, staff_user, event):
    client.force_login(staff_user)

    changelist = client.get(reverse("admin:accounts_securityevent_changelist"))
    index = client.get(reverse("admin:index"))

    assert changelist.status_code == HTTPStatus.FORBIDDEN
    assert (
        reverse("admin:accounts_securityevent_changelist") not in index.content.decode()
    )


def test_staff_granted_the_view_permission_still_cannot_see_it(
    client, staff_user, event
):
    staff_user.user_permissions.add(
        Permission.objects.get(codename="view_securityevent")
    )
    client.force_login(staff_user)

    response = client.get(reverse("admin:accounts_securityevent_changelist"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_log_filters_by_kind_and_searches_by_username(client, superuser, customer):
    security.record_event(Kind.SIGN_UP, customer, actor=customer)
    security.record_event(Kind.SIGN_UP, superuser, actor=superuser)
    security.record_event(Kind.SIGN_IN_FAILED, customer)
    client.force_login(superuser)
    url = reverse("admin:accounts_securityevent_changelist")

    by_kind = client.get(url, {"kind__exact": Kind.SIGN_IN_FAILED})
    by_name = client.get(url, {"q": "customer"})

    assert by_kind.context["cl"].result_count == 1
    # The superuser's own sign-in by force_login is in the log too, so
    # the search is checked by name rather than by a total.
    assert {e.username for e in by_name.context["cl"].result_list} == {"customer"}
    assert by_name.context["cl"].result_count == 2


# --- The seed ----------------------------------------------------------------


def test_seed_twice_gives_every_seeded_user_one_sign_up_event(db):
    call_command("seed")
    call_command("seed")

    User = get_user_model()
    for username in MANAGED_USERNAMES:
        user = User.objects.get(username=username)
        assert user.security_events.filter(kind=Kind.SIGN_UP).count() == 1
    # No orphans from the first run's deleted accounts.
    assert not SecurityEvent.objects.filter(user=None).exists()
