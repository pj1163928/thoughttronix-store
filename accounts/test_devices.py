"""The Account page's device list: what's signed in, and signing one out.

Each test client is one browser. Two clients signed in as the same user
are two devices; two windows of one real browser share cookies, and so
are one.
"""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import security
from accounts.models import SecurityEvent, UserSession

Kind = SecurityEvent.Kind
User = get_user_model()

PASSWORD = "casey-pass-123"
FIREFOX_ON_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"
)
SAFARI_ON_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey", password=PASSWORD, email="casey@example.com"
    )


def sign_in(client, user_agent="", ip="127.0.0.1"):
    client.post(
        reverse("accounts:login"),
        {"username": "casey", "password": PASSWORD},
        HTTP_USER_AGENT=user_agent,
        REMOTE_ADDR=ip,
    )
    return client


@pytest.fixture
def laptop(casey):
    return sign_in(Client(), FIREFOX_ON_WINDOWS, "198.51.100.4")


@pytest.fixture
def phone(casey):
    return sign_in(Client(), SAFARI_ON_IPHONE, "203.0.113.7")


def session_of(client):
    return UserSession.objects.get(pk=client.session[security.USER_SESSION_KEY])


def is_signed_in(client):
    return client.get(reverse("accounts:account")).status_code == HTTPStatus.OK


def sign_out_device(client, user_session, password=PASSWORD):
    return client.post(
        reverse("accounts:sign_out_device", args=[user_session.pk]),
        {"current_password": password},
    )


# --- Recording devices -----------------------------------------------------------


def test_signing_in_registers_the_device(laptop, casey):
    user_session = session_of(laptop)

    assert user_session.user == casey
    assert user_session.ip_address == "198.51.100.4"
    assert user_session.user_agent == FIREFOX_ON_WINDOWS
    assert user_session.label == "Firefox on Windows"


def test_two_browsers_are_two_devices(laptop, phone, casey):
    assert casey.user_sessions.count() == 2
    assert session_of(laptop) != session_of(phone)


def test_signing_in_again_in_the_same_browser_replaces_its_device(laptop, casey):
    first = session_of(laptop)

    sign_in(laptop, FIREFOX_ON_WINDOWS)

    assert casey.user_sessions.get() != first


def test_signing_out_removes_the_device(laptop, casey):
    laptop.post(reverse("accounts:logout"))

    assert not casey.user_sessions.exists()


def test_a_session_from_before_devices_were_tracked_gets_one(laptop, casey):
    session = laptop.session
    del session[security.USER_SESSION_KEY]
    session.save()
    casey.user_sessions.all().delete()

    assert is_signed_in(laptop)
    assert casey.user_sessions.count() == 1


def test_last_active_is_refreshed_at_most_once_a_minute(laptop):
    user_session = session_of(laptop)
    recently = timezone.now() - timedelta(seconds=10)
    UserSession.objects.filter(pk=user_session.pk).update(last_seen_at=recently)

    laptop.get(reverse("products:catalog"), REMOTE_ADDR="192.0.2.50")

    user_session.refresh_from_db()
    assert user_session.last_seen_at == recently
    assert user_session.ip_address == "198.51.100.4"


def test_last_active_and_ip_follow_the_device_once_a_minute_has_passed(laptop):
    user_session = session_of(laptop)
    earlier = timezone.now() - timedelta(minutes=5)
    UserSession.objects.filter(pk=user_session.pk).update(last_seen_at=earlier)

    laptop.get(reverse("products:catalog"), REMOTE_ADDR="192.0.2.50")

    user_session.refresh_from_db()
    assert user_session.last_seen_at > earlier
    assert user_session.ip_address == "192.0.2.50"


def test_a_device_idle_past_the_session_lifetime_is_not_listed(
    settings, laptop, phone, casey
):
    idle = timezone.now() - timedelta(seconds=settings.SESSION_COOKIE_AGE + 60)
    UserSession.objects.filter(pk=session_of(phone).pk).update(last_seen_at=idle)

    listed = list(laptop.get(reverse("accounts:account")).context["user_sessions"])

    assert listed == [session_of(laptop)]


def test_expired_devices_are_cleared_at_the_next_sign_in(settings, laptop, casey):
    idle = timezone.now() - timedelta(seconds=settings.SESSION_COOKIE_AGE + 60)
    UserSession.objects.filter(pk=session_of(laptop).pk).update(last_seen_at=idle)

    phone = sign_in(Client(), SAFARI_ON_IPHONE)

    assert list(casey.user_sessions.all()) == [session_of(phone)]


@pytest.mark.parametrize(
    ("user_agent", "label"),
    [
        (FIREFOX_ON_WINDOWS, "Firefox on Windows"),
        (SAFARI_ON_IPHONE, "Safari on iPhone"),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
            "like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Edge on Windows",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Chrome on macOS",
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, "
            "like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
            "Chrome on Android",
        ),
        ("curl/8.9.1", "Unknown browser"),
        ("", "Unknown browser"),
    ],
)
def test_the_device_label_names_browser_and_system(user_agent, label):
    assert UserSession(user_agent=user_agent).label == label


@pytest.mark.parametrize(
    ("user_agent", "is_phone"),
    [
        (FIREFOX_ON_WINDOWS, False),
        (SAFARI_ON_IPHONE, True),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/129.0.0.0", True),
        ("", False),
    ],
)
def test_phones_are_told_apart_from_computers(user_agent, is_phone):
    assert UserSession(user_agent=user_agent).is_phone is is_phone


# --- The list on the Account page ------------------------------------------------


def test_the_hub_lists_every_device_and_marks_this_one(laptop, phone):
    response = laptop.get(reverse("accounts:account"))
    page = response.content.decode()

    assert "Firefox on Windows" in page
    assert "Safari on iPhone" in page
    assert "203.0.113.7" in page
    assert page.count("This device") == 1
    assert "Signed in" in page
    assert "Last active" in page
    # Only the other device can be signed out from here.
    assert reverse("accounts:sign_out_device", args=[session_of(phone).pk]) in page
    assert reverse("accounts:sign_out_device", args=[session_of(laptop).pk]) not in page


def test_the_hub_lists_only_the_users_own_devices(laptop, db):
    User.objects.create_user(username="someone-else", password="someone123")
    other = Client()
    other.post(
        reverse("accounts:login"),
        {"username": "someone-else", "password": "someone123"},
        HTTP_USER_AGENT=SAFARI_ON_IPHONE,
    )

    page = laptop.get(reverse("accounts:account")).content.decode()

    assert "Safari on iPhone" not in page


# --- Signing one device out ------------------------------------------------------


def test_the_confirm_page_names_the_device(laptop, phone):
    response = laptop.get(
        reverse("accounts:sign_out_device", args=[session_of(phone).pk])
    )

    assert response.status_code == HTTPStatus.OK
    assert "Sign out Safari on iPhone?" in response.content.decode()
    assert list(response.context["form"].fields) == ["current_password"]


def test_viewing_the_confirm_page_signs_nothing_out(laptop, phone):
    laptop.get(reverse("accounts:sign_out_device", args=[session_of(phone).pk]))

    assert is_signed_in(phone)


def test_signing_a_device_out_ends_only_that_device(laptop, phone, casey):
    third = sign_in(Client(), "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0")

    response = sign_out_device(laptop, session_of(phone))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("accounts:account")
    assert not is_signed_in(phone)
    assert is_signed_in(laptop)
    assert is_signed_in(third)
    casey.refresh_from_db()
    assert casey.check_password(PASSWORD)


def test_the_signed_out_device_is_told_why(laptop, phone):
    sign_out_device(laptop, session_of(phone))

    response = phone.get(reverse("products:catalog"))

    assert not response.context["user"].is_authenticated
    assert "This device was signed out from another device." in (
        response.content.decode()
    )


def test_signing_a_device_out_is_recorded(laptop, phone, casey):
    target = session_of(phone)

    sign_out_device(laptop, target)

    event = SecurityEvent.objects.get(kind=Kind.SESSION_ENDED)
    assert event.user == casey
    assert event.actor == casey
    assert event.details == {"device": "Safari on iPhone"}
    assert not UserSession.objects.filter(pk=target.pk).exists()


def test_a_wrong_password_signs_nothing_out_and_counts_toward_the_cooldown(
    laptop, phone, casey
):
    response = sign_out_device(laptop, session_of(phone), password="nope")

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors["current_password"] == [
        "That isn't your current password."
    ]
    assert is_signed_in(phone)
    failure = SecurityEvent.objects.get(kind=Kind.SIGN_IN_FAILED)
    assert failure.details == {"reauthentication": "sign_out_device"}


def test_this_device_cant_be_signed_out_from_the_list(laptop):
    response = sign_out_device(laptop, session_of(laptop))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert is_signed_in(laptop)


def test_another_accounts_device_cant_be_signed_out(laptop, db):
    User.objects.create_user(username="someone-else", password="someone123")
    other = Client()
    other.post(
        reverse("accounts:login"),
        {"username": "someone-else", "password": "someone123"},
    )

    response = sign_out_device(laptop, session_of(other))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert is_signed_in(other)


def test_signing_a_device_out_requires_sign_in(client, laptop):
    response = sign_out_device(client, session_of(laptop))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


# --- The other ways out clear the list too ---------------------------------------


def test_sign_out_of_all_others_clears_the_other_devices(laptop, phone, casey):
    laptop.post(reverse("accounts:sign_out_others"), {"current_password": PASSWORD})

    assert list(casey.user_sessions.all()) == [session_of(laptop)]
    assert not is_signed_in(phone)


def test_a_password_change_clears_the_other_devices(laptop, phone, casey):
    laptop.post(
        reverse("accounts:password_change"),
        {
            "current_password": PASSWORD,
            "new_password1": "synaptic-velvet-42",
            "new_password2": "synaptic-velvet-42",
        },
    )

    assert list(casey.user_sessions.all()) == [session_of(laptop)]
    assert not is_signed_in(phone)
