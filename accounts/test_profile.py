"""The profile: a name, a 180 × 180 picture, and the navbar's profile menu."""

import io
from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.templatetags.static import static
from django.urls import reverse
from PIL import Image

from products import images

User = get_user_model()


@pytest.fixture
def casey(db):
    return User.objects.create_user(
        username="casey",
        password="casey-pass-123",
        email="casey@example.com",
        first_name="Casey",
        last_name="Monroe",
    )


@pytest.fixture
def signed_in(client, casey):
    client.force_login(casey)
    return client


def stored_size(name):
    with default_storage.open(name) as handle:
        return Image.open(io.BytesIO(handle.read())).size


def save_profile(client, **data):
    return client.post(
        reverse("accounts:edit_profile"),
        {"first_name": "Casey", "last_name": "Monroe", **data},
    )


# --- The picture itself ---------------------------------------------------------


def test_a_picture_is_cropped_and_scaled_to_180_square(make_image):
    avatar = images.validate_avatar(make_image(800, 400))

    assert Image.open(io.BytesIO(avatar)).size == (180, 180)
    assert Image.open(io.BytesIO(avatar)).format == "WEBP"


def test_a_180_pixel_picture_is_accepted(make_image):
    avatar = images.validate_avatar(make_image(180, 180))

    assert Image.open(io.BytesIO(avatar)).size == (180, 180)


def test_a_picture_smaller_than_180_is_refused(make_image):
    with pytest.raises(ValidationError) as refusal:
        images.validate_avatar(make_image(179, 400, name="tiny.png"))

    assert refusal.value.messages == [
        "“tiny.png” is 179 × 400 pixels. Images must be at least 180 pixels on "
        "each side, or they look blurry as a profile picture — use a larger "
        "version of the photo."
    ]


def test_a_file_that_is_not_an_image_is_refused():
    upload = io.BytesIO(b"not a picture")
    upload.name = "notes.png"

    with pytest.raises(ValidationError) as refusal:
        images.validate_avatar(upload)

    assert refusal.value.code == "wrong_type"


def test_replacing_a_picture_deletes_the_old_file(
    casey, make_image, django_capture_on_commit_callbacks
):
    images.set_avatar(casey, images.validate_avatar(make_image()))
    first = casey.avatar.name

    with django_capture_on_commit_callbacks(execute=True):
        images.set_avatar(casey, images.validate_avatar(make_image()))

    assert casey.avatar.name != first
    assert casey.avatar.name.startswith("avatars/")
    assert not default_storage.exists(first)
    assert default_storage.exists(casey.avatar.name)


def test_deleting_an_account_deletes_its_picture(
    casey, make_image, django_capture_on_commit_callbacks
):
    images.set_avatar(casey, images.validate_avatar(make_image()))
    name = casey.avatar.name

    with django_capture_on_commit_callbacks(execute=True):
        casey.delete()

    assert not default_storage.exists(name)


def test_no_picture_shows_the_silhouette(casey):
    picture = casey.avatar_picture

    assert picture.is_placeholder
    assert picture.url == static(images.AVATAR_PLACEHOLDER)
    assert (picture.width, picture.height) == (180, 180)


def test_a_missing_file_shows_the_silhouette_not_a_broken_image(casey, make_image):
    images.set_avatar(casey, images.validate_avatar(make_image()))
    default_storage.delete(casey.avatar.name)

    assert casey.avatar_picture.is_placeholder


# --- Name and greeting ---------------------------------------------------------------


def test_the_display_name_is_the_full_name_or_else_the_username(casey, db):
    nameless = User.objects.create_user(username="drew", password="x-pass-123")

    assert casey.display_name == "Casey Monroe"
    assert nameless.display_name == "drew"


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (5, "Good morning, Casey"),
        (11, "Good morning, Casey"),
        (12, "Good afternoon, Casey"),
        (17, "Good afternoon, Casey"),
        (18, "Good evening, Casey"),
        (2, "Good evening, Casey"),
    ],
)
def test_the_greeting_follows_the_time_of_day(casey, settings, hour, expected):
    settings.TIME_ZONE = "UTC"

    assert casey.greeting(datetime(2026, 10, 7, hour, 30, tzinfo=UTC)) == expected


def test_the_greeting_falls_back_to_the_username(db):
    nameless = User.objects.create_user(username="drew", password="x-pass-123")

    assert nameless.greeting().endswith(", drew")


# --- Sign-up ---------------------------------------------------------------------------


def sign_up(client, **extra):
    return client.post(
        reverse("accounts:signup"),
        {
            "username": "drew",
            "email": "drew@example.com",
            "password1": "a-long-passphrase-42",
            "password2": "a-long-passphrase-42",
            **extra,
        },
    )


def test_sign_up_takes_an_optional_name(client, db):
    sign_up(client, first_name="Drew", last_name="Park")

    assert User.objects.get(username="drew").display_name == "Drew Park"


def test_sign_up_works_without_a_name(client, db):
    response = sign_up(client)

    assert response.status_code == HTTPStatus.FOUND
    assert User.objects.get(username="drew").display_name == "drew"


# --- The Edit profile page --------------------------------------------------------------


def test_edit_profile_requires_sign_in(client, db):
    response = client.get(reverse("accounts:edit_profile"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("accounts:login"))


def test_edit_profile_changes_the_name(signed_in, casey):
    response = save_profile(signed_in, first_name="Case", last_name="Rivera")

    assert response.url == reverse("accounts:account")
    casey.refresh_from_db()
    assert casey.display_name == "Case Rivera"


def test_uploading_a_picture_stores_a_180_square(signed_in, casey, make_image):
    save_profile(signed_in, photo=make_image(1000, 600))

    casey.refresh_from_db()
    assert casey.avatar.name.startswith("avatars/")
    assert stored_size(casey.avatar.name) == (180, 180)


def test_a_bad_picture_is_explained_and_nothing_is_saved(signed_in, casey, make_image):
    response = save_profile(
        signed_in, first_name="Changed", photo=make_image(100, 100, name="tiny.png")
    )

    assert response.status_code == HTTPStatus.OK
    assert "“tiny.png” is 100 × 100 pixels" in response.content.decode()
    casey.refresh_from_db()
    assert casey.first_name == "Casey"
    assert not casey.avatar


def test_remove_is_offered_only_with_a_picture(signed_in, casey, make_image):
    before = signed_in.get(reverse("accounts:edit_profile")).content.decode()
    images.set_avatar(casey, images.validate_avatar(make_image()))
    after = signed_in.get(reverse("accounts:edit_profile")).content.decode()

    assert "Remove my profile picture" not in before
    assert "Remove my profile picture" in after


def test_removing_the_picture_brings_back_the_silhouette(
    signed_in, casey, make_image, django_capture_on_commit_callbacks
):
    images.set_avatar(casey, images.validate_avatar(make_image()))
    name = casey.avatar.name

    with django_capture_on_commit_callbacks(execute=True):
        save_profile(signed_in, remove_photo="on")

    casey.refresh_from_db()
    assert not casey.avatar
    assert casey.avatar_picture.is_placeholder
    assert not default_storage.exists(name)


def test_a_new_picture_wins_over_remove(signed_in, casey, make_image):
    images.set_avatar(casey, images.validate_avatar(make_image()))
    first = casey.avatar.name

    save_profile(signed_in, remove_photo="on", photo=make_image())

    casey.refresh_from_db()
    assert casey.avatar
    assert casey.avatar.name != first


# --- The navbar's profile menu --------------------------------------------------------------


def test_the_profile_menu_greets_by_name_and_links_to_the_account(signed_in, casey):
    page = signed_in.get(reverse("products:catalog")).content.decode()

    assert casey.greeting() in page
    assert "Casey Monroe" in page
    assert f'href="{reverse("accounts:account")}"' in page
    assert f'href="{reverse("accounts:edit_profile")}"' in page
    assert static(images.AVATAR_PLACEHOLDER) in page


def test_the_profile_menu_shows_an_uploaded_picture(signed_in, casey, make_image):
    images.set_avatar(casey, images.validate_avatar(make_image()))

    page = signed_in.get(reverse("products:catalog")).content.decode()

    assert casey.avatar.url in page
    assert static(images.AVATAR_PLACEHOLDER) not in page


def test_visitors_get_no_profile_menu(client, db):
    page = client.get(reverse("products:catalog")).content.decode()

    assert "Your profile menu" not in page


def test_the_navbar_icons_sit_left_of_the_profile_menu(signed_in):
    page = signed_in.get(reverse("products:catalog")).content.decode()

    positions = [
        page.index(f'href="{reverse("orders:history")}"'),
        page.index(f'href="{reverse("wishlist:list")}"'),
        page.index('id="cart-badge"'),
        page.index('aria-label="Your profile menu"'),
    ]
    assert positions == sorted(positions)
    for label in ("Orders", "Wishlist", "Cart"):
        assert f'aria-label="{label}"' in page


def test_sign_out_lives_in_the_profile_menu(signed_in):
    page = signed_in.get(reverse("products:catalog")).content.decode()

    menu = page[page.index('aria-label="Your profile menu"') :]
    assert 'form="sign-out-form"' in menu
    assert (
        f'id="sign-out-form" method="post" action="{reverse("accounts:logout")}"'
        in menu
    )
