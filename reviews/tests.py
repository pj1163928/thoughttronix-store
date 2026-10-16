"""Reviews: eligibility, the model's rules, the "Your review" slot and create."""

import html
import io
import re
from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem
from products import images
from products.models import Category, Product, Tag
from products.views import stars_phrase

from .forms import ReviewForm
from .models import Review
from .templatetags.reviews_extras import half_stars

pytestmark = pytest.mark.django_db

NOT_BOUGHT = "Only customers who've bought Seraphine Home Hub can review it."
SIGN_IN = "Bought this? Sign in to leave a review."


def buy(user, product, *, status=Order.Status.PLACED):
    """One order by ``user`` holding one ``product``, in ``status``."""
    order = Order.objects.create(
        user=user,
        status=status,
        total=product.price,
        email="casey@example.com",
        shipping_name="Casey Monroe",
        shipping_street="214 Synapse Street",
        shipping_city="Canyon",
        shipping_state="TX",
        shipping_zip="79015",
        billing_name="Casey Monroe",
        billing_street="214 Synapse Street",
        billing_city="Canyon",
        billing_state="TX",
        billing_zip="79015",
        card_last4="4242",
    )
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        unit_price=Decimal(product.price),
        quantity=1,
    )
    return order


# --- Eligibility --------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "eligible"),
    [
        (Order.Status.PLACED, True),
        (Order.Status.SHIPPED, True),
        (Order.Status.DELIVERED, True),
        (Order.Status.CANCELLED, False),
    ],
)
def test_can_write_needs_a_non_cancelled_order_for_the_product(
    customer, product, featured_product, status, eligible
):
    # A live order for a different product never qualifies anyone.
    buy(customer, featured_product)
    buy(customer, product, status=status)

    assert Review.can_write(customer, product) is eligible


def test_anonymous_visitors_cannot_write(product):
    assert not Review.can_write(AnonymousUser(), product)


def test_staff_qualify_on_the_same_terms(staff_user, product):
    assert not Review.can_write(staff_user, product)

    buy(staff_user, product)

    assert Review.can_write(staff_user, product)


def test_an_unavailable_product_can_be_reviewed_by_its_buyers(
    customer, unavailable_product
):
    buy(customer, unavailable_product)

    assert Review.can_write(customer, unavailable_product)


# --- The model ----------------------------------------------------------------


def make_review(user, product, *, rating=8, comment="Does what it promises."):
    return Review.objects.create(
        user=user, product=product, rating=rating, comment=comment
    )


@pytest.mark.parametrize("half_stars", [2, 10])
def test_the_database_accepts_one_and_five_stars(customer, product, half_stars):
    assert make_review(customer, product, rating=half_stars).rating == half_stars


def test_stars_halves_the_stored_rating(customer, product):
    review = make_review(customer, product, rating=7)

    assert review.stars == 3.5
    assert review.get_rating_display() == "3½ stars"


def test_one_review_per_user_and_product(customer, product):
    make_review(customer, product)

    with pytest.raises(IntegrityError):
        make_review(customer, product)


def test_by_staff_is_taken_from_the_author_when_first_written(
    customer, staff_user, product
):
    assert not make_review(customer, product).by_staff
    assert make_review(staff_user, product).by_staff


def test_by_is_scoped_to_the_author(customer, staff_user, product):
    mine = make_review(customer, product)
    make_review(staff_user, product)

    assert list(Review.objects.by(customer)) == [mine]
    assert not Review.objects.by(AnonymousUser()).exists()


@pytest.mark.parametrize(
    ("comment", "message"),
    [
        ("   too short   ", "Write at least 10 characters."),
        ("x" * 2001, "Keep it to 2,000 characters (this has 2,001)."),
    ],
)
def test_clean_holds_a_live_comment_to_ten_to_two_thousand_characters(
    customer, product, comment, message
):
    review = Review(user=customer, product=product, rating=8, comment=comment)

    with pytest.raises(ValidationError) as caught:
        review.full_clean()

    assert caught.value.message_dict["comment"] == [message]


def test_clean_trims_and_accepts_exactly_ten_characters(customer, product):
    review = Review(user=customer, product=product, rating=8, comment="  0123456789  ")

    review.full_clean()

    assert review.comment == "0123456789"


def test_clean_lets_a_removed_review_hold_a_blank_comment(customer, product):
    review = Review(
        user=customer, product=product, rating=8, comment="", removed_at=timezone.now()
    )

    review.full_clean()


def test_reviews_are_not_in_the_admin():
    """The back office's Reviews tab is the one place reviews are moderated."""
    assert Review not in admin.site._registry


@pytest.mark.parametrize("half_stars", [0, 1, 11])
def test_the_database_refuses_ratings_outside_one_to_five_stars(
    customer, product, half_stars
):
    """Not just the form: a rating written past validation still can't land."""
    with pytest.raises(IntegrityError):
        Review.objects.create(
            user=customer,
            product=product,
            rating=half_stars,
            comment="Out of range, whatever the form said.",
        )


# --- Create (HTMX) -------------------------------------------------------------


def create_url(product):
    return reverse("reviews:create", kwargs={"pk": product.pk})


VALID = {
    "rating": "9",
    "headline": "Finally, a hub that gets me",
    "comment": "It finished my sentences before I did. Mostly correctly.",
}


def test_a_second_create_returns_the_existing_review(client, customer, product):
    """A double click or a stale second tab shows the review, never an error."""
    buy(customer, product)
    client.force_login(customer)
    client.raise_request_exception = False
    client.post(create_url(product), VALID)

    response = client.post(
        create_url(product),
        {"rating": "2", "comment": "The stale tab's different opinion."},
    )

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert 'id="your-review"' in page
    assert "Finally, a hub that gets me" in page
    assert "stale tab" not in page
    assert Review.objects.count() == 1
    assert Review.objects.get().rating == 9


def test_a_valid_create_writes_the_review_and_returns_the_slot(
    client, customer, product
):
    buy(customer, product)
    client.force_login(customer)

    response = client.post(create_url(product), VALID)

    assert response.status_code == HTTPStatus.OK
    review = Review.objects.get()
    assert (review.user, review.product, review.rating) == (customer, product, 9)
    assert review.headline == "Finally, a hub that gets me"
    assert not review.by_staff
    page = response.content.decode()
    assert "<html" not in page
    assert 'id="your-review"' in page
    assert f'id="review-{review.pk}"' in page
    assert "It finished my sentences" in page
    assert 'aria-label="4½ stars"' in page
    assert "Post review" not in page


def test_a_create_response_updates_both_averages_out_of_band(client, customer, product):
    """The slot, plus the section summary and the details-card average, all current."""
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=6)
    buy(customer, product)
    client.force_login(customer)

    response = client.post(create_url(product), {**VALID, "rating": "10"})

    page = response.content.decode()
    assert 'id="your-review"' in page
    assert 'id="reviews-summary"' in page
    assert page.count('hx-swap-oob="true"') == 2
    assert 'id="details-rating"' in page
    assert "4.0 from 2 customer reviews" in page
    assert "4.0 · 2 customer reviews" in page


def test_a_staff_members_review_is_marked_by_staff(client, staff_user, product):
    buy(staff_user, product)
    client.force_login(staff_user)

    client.post(create_url(product), VALID)

    assert Review.objects.get().by_staff


def test_the_headline_is_optional(client, customer, product):
    buy(customer, product)
    client.force_login(customer)

    client.post(create_url(product), {**VALID, "headline": ""})

    assert Review.objects.get().headline == ""


def test_an_unavailable_product_can_be_reviewed(client, customer, unavailable_product):
    buy(customer, unavailable_product)
    client.force_login(customer)

    client.post(create_url(unavailable_product), VALID)

    assert Review.objects.get().product == unavailable_product


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"headline": "h" * 101}, "Ensure this value has at most 100 characters"),
        ({"comment": "   too short   "}, "Write at least 10 characters."),
        ({"comment": ""}, "Write at least 10 characters."),
        ({"comment": "x" * 2001}, "Keep it to 2,000 characters (this has 2,001)."),
        ({"rating": ""}, "Choose a rating."),
        ({"rating": "1"}, "Choose a rating."),
        ({"rating": "11"}, "Choose a rating."),
    ],
)
def test_invalid_input_re_renders_the_form_with_errors(
    client, customer, product, changes, message
):
    buy(customer, product)
    client.force_login(customer)

    response = client.post(create_url(product), {**VALID, **changes})

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert 'id="your-review"' in page
    assert "Post review" in page
    assert message in page
    assert page.count(message) == 1
    assert not Review.objects.exists()


def test_a_rejected_rating_choice_is_kept(client, customer, product):
    buy(customer, product)
    client.force_login(customer)

    response = client.post(create_url(product), {**VALID, "comment": "short"})

    page = response.content.decode()
    assert 'value="9" aria-label="4½ stars"' in page
    assert page.count("checked") == 1


def test_an_ineligible_create_writes_nothing(client, customer, product):
    buy(customer, product, status=Order.Status.CANCELLED)
    client.force_login(customer)

    response = client.post(create_url(product), VALID)

    assert response.status_code == HTTPStatus.OK
    assert NOT_BOUGHT in response.content.decode()
    assert not Review.objects.exists()


def test_anonymous_create_redirects_to_sign_in(client, product):
    response = client.post(create_url(product), VALID)

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url
    assert not Review.objects.exists()


def test_create_is_post_only(client, customer, product):
    buy(customer, product)
    client.force_login(customer)

    response = client.get(create_url(product))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_create_for_a_missing_product_404s(client, customer):
    client.force_login(customer)

    response = client.post(reverse("reviews:create", kwargs={"pk": 999}), VALID)

    assert response.status_code == HTTPStatus.NOT_FOUND


# --- The product page's "Your review" slot ------------------------------------


def test_a_visitor_is_asked_to_sign_in_and_brought_back(client, product):
    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert 'id="reviews"' in page
    assert SIGN_IN in page
    assert f"{reverse('accounts:login')}?next=/products/seraphine-home-hub/" in page
    assert create_url(product) not in page


def test_a_customer_who_hasnt_bought_it_sees_the_note(client, customer, product):
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert NOT_BOUGHT in page
    assert create_url(product) not in page


def test_a_customer_with_only_a_cancelled_order_sees_the_note(
    client, customer, product
):
    buy(customer, product, status=Order.Status.CANCELLED)
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    assert NOT_BOUGHT in response.content.decode()


@pytest.mark.parametrize(
    "status", [Order.Status.PLACED, Order.Status.SHIPPED, Order.Status.DELIVERED]
)
def test_a_buyer_sees_the_form(client, customer, product, status):
    buy(customer, product, status=status)
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert create_url(product) in page
    assert "Post review" in page
    assert NOT_BOUGHT not in page


def test_staff_who_bought_it_see_the_form(client, staff_user, product):
    buy(staff_user, product)
    client.force_login(staff_user)

    response = client.get(product.get_absolute_url())

    assert create_url(product) in response.content.decode()


def test_an_unavailable_products_buyer_sees_the_form(
    client, customer, unavailable_product
):
    buy(customer, unavailable_product)
    client.force_login(customer)

    response = client.get(unavailable_product.get_absolute_url())

    assert create_url(unavailable_product) in response.content.decode()


def test_the_author_sees_their_review_instead_of_the_form(client, customer, product):
    buy(customer, product)
    review = make_review(customer, product, comment="Mine, and nobody else's.")
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert f'id="review-{review.pk}"' in page
    assert "Mine, and nobody else" in page
    assert create_url(product) not in page


def test_an_author_whose_order_was_cancelled_still_sees_their_review(
    client, customer, product
):
    order = buy(customer, product)
    make_review(customer, product, comment="Written while it still counted.")
    order.status = Order.Status.CANCELLED
    order.save()
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert "Written while it still counted." in page
    assert NOT_BOUGHT not in page


# --- The Reviews section: summary and list --------------------------------------


def shopper(username, first_name="", last_name=""):
    """Another signed-up customer, for reviews that aren't the viewer's."""
    return get_user_model().objects.create_user(
        username=username, first_name=first_name, last_name=last_name
    )


def test_the_summary_counts_customer_reviews_only(
    client, customer, staff_user, product, featured_product
):
    """Staff and removed reviews never move a number; staff ones are still listed."""
    make_review(customer, product, rating=8)
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=10)
    make_review(staff_user, product, rating=2)
    removed = make_review(shopper("gfinch", "Gordon", "Finch"), product, rating=2)
    removed.removed_at = timezone.now()
    removed.save()
    make_review(staff_user, featured_product, rating=10, comment="Staff pick, sorry.")

    page = client.get(product.get_absolute_url()).content.decode()
    staff_only = client.get(featured_product.get_absolute_url()).content.decode()

    assert "4.5 from 2 customer reviews" in page
    assert "No customer reviews yet" in staff_only
    assert "Staff pick, sorry." in staff_only
    assert "ThoughtTronix staff" in staff_only


def test_reviewers_are_named_by_first_name_and_last_initial_only(client, product):
    """Never the username (a sign-in identifier) and never the full name."""
    make_review(shopper("dcole", "Dana", "Cole"), product)
    make_review(shopper("ghost_x9"), product)

    page = client.get(product.get_absolute_url()).content.decode()

    assert "Dana C." in page
    assert "A ThoughtTronix customer" in page
    for private in ["dcole", "Cole", "ghost_x9"]:
        assert private not in page


def test_each_review_shows_its_authors_picture_or_the_silhouette(
    client, product, make_image
):
    dana = shopper("dcole", "Dana", "Cole")
    images.set_avatar(dana, images.validate_avatar(make_image()))
    make_review(dana, product)
    make_review(shopper("gfinch", "Gordon", "Finch"), product)

    page = client.get(product.get_absolute_url()).content.decode()

    assert dana.avatar.url in page
    assert "placeholders/avatar.svg" in page


def test_the_authors_picture_is_labelled_without_the_full_name(customer, product):
    customer.first_name, customer.last_name = "Casey", "Monroe"
    customer.save()

    review = make_review(customer, product)

    assert review.author_picture.alt == "Profile picture of Casey M."


def test_a_star_row_is_five_stars_lit_up_to_the_rating():
    positions = half_stars(7)

    assert [position["half"] for position in positions] == [1, 2] * 5
    assert [position["current"] for position in positions].index(True) == 6
    assert sum(position["current"] for position in positions) == 1


def test_each_review_shows_its_rating_as_a_number(client, product):
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=9)

    page = client.get(product.get_absolute_url()).content.decode()

    assert 'aria-label="4½ stars"' in page
    assert '<span class="text-sm font-semibold" aria-hidden="true">4.5</span>' in page


def test_star_classes_are_written_out_for_tailwind():
    """Tailwind only finds whole class names; a built one never reaches the CSS."""
    templates = Path(settings.BASE_DIR) / "templates" / "reviews"
    for template in templates.rglob("*.html"):
        assert "mask-half-{{" not in template.read_text(encoding="utf-8"), template


def test_a_first_name_alone_is_used_as_is(customer, product):
    review = make_review(shopper("cher", "Cher"), product)

    assert review.author_name == "Cher"


def test_a_visitor_reads_the_summary_and_the_list(client, product):
    make_review(shopper("dcole", "Dana", "Cole"), product, comment="Hears everything.")

    page = client.get(product.get_absolute_url()).content.decode()

    assert "4.0 from 1 customer review" in page
    assert "Hears everything." in page
    assert "Verified purchase" in page


def test_a_product_without_reviews_says_so_twice(client, product):
    """In the details card and in the section summary."""
    page = client.get(product.get_absolute_url()).content.decode()

    assert page.count("No customer reviews yet") == 2


def test_the_details_card_links_its_average_to_the_section(client, product):
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=7)

    page = client.get(product.get_absolute_url()).content.decode()

    assert '<a href="#reviews" id="details-rating"' in page
    assert "3.5 · 1 customer review" in page


def test_the_viewers_own_review_is_in_the_slot_not_the_list(client, customer, product):
    mine = make_review(customer, product, comment="Mine, shown once.")
    theirs = make_review(shopper("dcole", "Dana", "Cole"), product)
    client.force_login(customer)

    response = client.get(product.get_absolute_url())

    page = response.content.decode()
    assert page.count(f'id="review-{mine.pk}"') == 1
    assert page.count("Mine, shown once.") == 1
    assert page.index('id="your-review"') < page.index(f'id="review-{mine.pk}"')
    assert page.index(f'id="review-{mine.pk}"') < page.index('id="review-list"')
    assert page.index('id="review-list"') < page.index(f'id="review-{theirs.pk}"')


def test_removed_reviews_are_not_listed(client, product):
    removed = make_review(shopper("dcole", "Dana", "Cole"), product)
    removed.removed_at = timezone.now()
    removed.save()

    page = client.get(product.get_absolute_url()).content.decode()

    assert f'id="review-{removed.pk}"' not in page


def test_staff_and_removed_reviews_are_left_out_of_the_counted_set(
    customer, staff_user, product
):
    counted = make_review(customer, product)
    make_review(staff_user, product)
    removed = make_review(shopper("dcole", "Dana", "Cole"), product)
    removed.removed_at = timezone.now()
    removed.save()

    assert list(Review.objects.counted()) == [counted]
    assert Review.objects.rating_summary().count == 1


def test_an_empty_summary_has_no_average():
    summary = Review.objects.none().rating_summary()

    assert (summary.count, summary.average, summary.half_stars) == (0, None, 0)


@pytest.mark.parametrize(
    ("ratings", "display", "half_stars"),
    [([8], "4.0", 8), ([7, 8], "3.8", 8), ([8, 9, 9], "4.3", 9), ([2, 3], "1.3", 3)],
)
def test_the_average_rounds_half_up(product, ratings, display, half_stars):
    for number, rating in enumerate(ratings):
        make_review(shopper(f"shopper{number}"), product, rating=rating)

    summary = Review.objects.rating_summary()

    assert (summary.average_display, summary.half_stars) == (display, half_stars)


def test_by_staff_survives_the_author_changing_roles(customer, staff_user, product):
    """A snapshot of who wrote it, never recomputed."""
    customers_review = make_review(customer, product, comment="Written as a customer.")
    staff_review = make_review(staff_user, product, comment="Written as staff.")

    customer.is_staff = True
    customer.save()
    staff_user.is_staff = False
    staff_user.save()
    for review in (customers_review, staff_review):
        review.refresh_from_db()
        review.comment += " Edited later."
        review.save()

    customers_review.refresh_from_db()
    staff_review.refresh_from_db()
    assert not customers_review.by_staff
    assert staff_review.by_staff
    assert list(Review.objects.counted()) == [customers_review]


# --- Author edit (HTMX) -----------------------------------------------------------


def edit_url(review):
    return reverse("reviews:edit", kwargs={"pk": review.pk})


def test_another_customer_cannot_edit_a_review(client, customer, product):
    """Nobody but the author and staff: anyone else gets a 404, GET and POST alike."""
    review = make_review(customer, product, rating=8, comment="My words, not yours.")
    client.force_login(shopper("dcole", "Dana", "Cole"))

    shown = client.get(edit_url(review))
    saved = client.post(edit_url(review), {**VALID, "rating": "2"})

    assert shown.status_code == HTTPStatus.NOT_FOUND
    assert saved.status_code == HTTPStatus.NOT_FOUND
    review.refresh_from_db()
    assert (review.rating, review.comment) == (8, "My words, not yours.")
    assert review.edited_at is None


def test_an_author_whose_order_was_cancelled_can_still_edit(client, customer, product):
    """Eligibility guards creation only; a later refund doesn't take the review away."""
    order = buy(customer, product)
    review = make_review(customer, product, rating=8, comment="Before the refund.")
    order.status = Order.Status.CANCELLED
    order.save()
    client.force_login(customer)

    shown = client.get(edit_url(review))
    client.post(edit_url(review), {**VALID, "comment": "After the refund, still mine."})

    assert shown.status_code == HTTPStatus.OK
    assert "Save changes" in shown.content.decode()
    review.refresh_from_db()
    assert review.comment == "After the refund, still mine."
    assert review.edited_at is not None


def test_a_staff_member_editing_their_own_review_is_an_author_edit(
    client, staff_user, product
):
    """Rating included, labelled just "Edited": their own review isn't moderation."""
    buy(staff_user, product)
    review = make_review(staff_user, product, rating=8)
    client.force_login(staff_user)

    response = client.post(edit_url(review), {**VALID, "rating": "3"})

    review.refresh_from_db()
    assert review.rating == 3
    assert review.edited_at is not None
    assert (review.moderated_at, review.moderated_by) == (None, None)
    assert review.by_staff
    page = response.content.decode()
    assert "· Edited" in page
    assert "Edited by ThoughtTronix staff" not in page


def detail_url(review):
    return reverse("reviews:detail", kwargs={"pk": review.pk})


def test_the_edit_form_is_filled_in_and_changes_nothing(client, customer, product):
    review = make_review(customer, product, rating=7, comment="As first written.")
    client.force_login(customer)

    response = client.get(edit_url(review))

    page = response.content.decode()
    assert "<html" not in page
    assert f'<form id="review-{review.pk}"' in page
    assert f'hx-post="{edit_url(review)}"' in page
    assert f'hx-get="{detail_url(review)}"' in page
    assert 'value="7" aria-label="3½ stars"\n               class' in page
    assert page.count("checked") == 1
    assert "As first written." in page
    assert "Save changes" in page
    review.refresh_from_db()
    assert (review.rating, review.comment, review.edited_at) == (
        7,
        "As first written.",
        None,
    )


def test_cancel_returns_the_review_as_it_was(client, customer, product):
    review = make_review(customer, product, comment="Untouched by Cancel.")
    client.force_login(customer)
    client.get(edit_url(review))

    response = client.get(detail_url(review))

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "<html" not in page
    assert page.strip().startswith(f'<article id="review-{review.pk}"')
    assert "Untouched by Cancel." in page
    assert "Edited" not in page
    assert f'hx-get="{edit_url(review)}"' in page


def test_saving_an_edit_changes_the_review_and_marks_it_edited(
    client, customer, product
):
    review = make_review(customer, product, rating=8, comment="First thoughts here.")
    client.force_login(customer)

    response = client.post(
        edit_url(review),
        {"rating": "5", "headline": "Second thoughts", "comment": "It got worse."},
    )

    review.refresh_from_db()
    assert (review.rating, review.headline, review.comment) == (
        5,
        "Second thoughts",
        "It got worse.",
    )
    assert review.edited_at is not None
    page = response.content.decode()
    assert 'id="your-review"' in page
    assert f'id="review-{review.pk}"' in page
    assert "· Edited" in page
    assert "Save changes" not in page


def test_an_edit_response_updates_both_averages_out_of_band(client, customer, product):
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=6)
    review = make_review(customer, product, rating=6)
    client.force_login(customer)

    response = client.post(edit_url(review), {**VALID, "rating": "10"})

    page = response.content.decode()
    assert page.count('hx-swap-oob="true"') == 2
    assert 'id="reviews-summary"' in page
    assert 'id="details-rating"' in page
    assert "4.0 from 2 customer reviews" in page
    assert "4.0 · 2 customer reviews" in page


def test_saving_without_a_change_isnt_an_edit(client, customer, product):
    review = make_review(customer, product, rating=8, comment="Exactly the same.")
    client.force_login(customer)

    client.post(
        edit_url(review),
        {"rating": "8", "headline": "", "comment": "Exactly the same."},
    )

    review.refresh_from_db()
    assert review.edited_at is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"headline": "h" * 101}, "Ensure this value has at most 100 characters"),
        ({"comment": "   too short   "}, "Write at least 10 characters."),
        ({"comment": "x" * 2001}, "Keep it to 2,000 characters (this has 2,001)."),
        ({"rating": ""}, "Choose a rating."),
        ({"rating": "11"}, "Choose a rating."),
    ],
)
def test_an_invalid_edit_re_renders_the_form_and_saves_nothing(
    client, customer, product, changes, message
):
    review = make_review(customer, product, rating=8, comment="Still the original.")
    client.force_login(customer)

    response = client.post(edit_url(review), {**VALID, **changes})

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert 'id="your-review"' in page
    assert f'<form id="review-{review.pk}"' in page
    assert "Save changes" in page
    assert page.count(message) == 1
    review.refresh_from_db()
    assert (review.rating, review.comment, review.edited_at) == (
        8,
        "Still the original.",
        None,
    )


def test_staff_cannot_author_edit_someone_elses_review(
    client, customer, staff_user, product
):
    """Staff edits of other people's reviews go through moderation, which keeps the rating."""
    review = make_review(customer, product, rating=8)
    client.force_login(staff_user)

    shown = client.get(edit_url(review))
    saved = client.post(edit_url(review), {**VALID, "rating": "2"})

    assert (shown.status_code, saved.status_code) == (
        HTTPStatus.NOT_FOUND,
        HTTPStatus.NOT_FOUND,
    )
    review.refresh_from_db()
    assert review.rating == 8


def test_another_customer_cannot_fetch_a_review_partial(client, customer, product):
    review = make_review(customer, product)
    client.force_login(shopper("dcole", "Dana", "Cole"))

    assert client.get(detail_url(review)).status_code == HTTPStatus.NOT_FOUND


def test_a_removed_review_cant_be_edited_and_comes_back_as_the_notice(
    client, customer, product
):
    """Its text is never shown back to anyone, its author included.

    Fetching it, as "Keep it" does over the delete confirmation, gives
    its author the removal notice instead.
    """
    review = make_review(customer, product, comment="Words staff took down.")
    review.removed_at = timezone.now()
    review.save()
    client.force_login(customer)

    assert client.get(edit_url(review)).status_code == HTTPStatus.NOT_FOUND
    fetched = client.get(detail_url(review)).content.decode()
    assert fetched.strip().startswith(f'<div id="review-{review.pk}"')
    assert "Your review was removed by ThoughtTronix staff." in fetched
    assert "Words staff took down." not in fetched


def test_visitors_are_sent_to_sign_in_from_edit(client, customer, product):
    review = make_review(customer, product)

    response = client.post(edit_url(review), VALID)

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url


def test_only_the_author_sees_edit_on_the_product_page(client, customer, product):
    mine = make_review(customer, product)
    theirs = make_review(shopper("dcole", "Dana", "Cole"), product)
    client.force_login(customer)

    page = client.get(product.get_absolute_url()).content.decode()

    assert edit_url(mine) in page
    assert edit_url(theirs) not in page


def test_an_edited_review_says_so_in_the_list(client, product):
    review = make_review(shopper("dcole", "Dana", "Cole"), product)
    review.edited_at = timezone.now()
    review.save()

    page = client.get(product.get_absolute_url()).content.decode()

    assert "· Edited" in page
    assert edit_url(review) not in page


# --- Author delete (HTMX) ---------------------------------------------------------

CONFIRM = "Delete your review? This can't be undone."


def delete_url(review):
    return reverse("reviews:delete", kwargs={"pk": review.pk})


def test_the_delete_confirmation_changes_nothing(client, customer, product):
    review = make_review(customer, product, comment="Still here after asking.")
    client.force_login(customer)

    response = client.get(delete_url(review))

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "<html" not in page
    assert page.strip().startswith(f'<div id="review-{review.pk}"')
    assert CONFIRM in page
    assert f'hx-post="{delete_url(review)}"' in page
    assert 'hx-target="#your-review"' in page
    assert f'hx-get="{detail_url(review)}"' in page
    assert "Keep it" in page
    assert "hx-confirm" not in page
    review.refresh_from_db()
    assert review.comment == "Still here after asking."


def test_keep_it_returns_the_review_unchanged(client, customer, product):
    review = make_review(customer, product, rating=7, comment="Kept, as it was.")
    client.force_login(customer)
    client.get(delete_url(review))

    response = client.get(detail_url(review))

    page = response.content.decode()
    assert page.strip().startswith(f'<article id="review-{review.pk}"')
    assert "Kept, as it was." in page
    assert f'hx-get="{delete_url(review)}"' in page
    assert Review.objects.get().rating == 7


def test_deleting_removes_the_row_and_updates_both_averages(client, customer, product):
    make_review(shopper("dcole", "Dana", "Cole"), product, rating=6)
    buy(customer, product)
    review = make_review(customer, product, rating=10)
    client.force_login(customer)

    response = client.post(delete_url(review))

    assert response.status_code == HTTPStatus.OK
    assert not Review.objects.filter(pk=review.pk).exists()
    page = response.content.decode()
    assert "<html" not in page
    assert 'id="your-review"' in page
    assert f'id="review-{review.pk}"' not in page
    assert page.count('hx-swap-oob="true"') == 2
    assert 'id="reviews-summary"' in page
    assert 'id="details-rating"' in page
    assert "3.0 from 1 customer review" in page
    assert "3.0 · 1 customer review" in page


def test_a_still_eligible_author_can_write_again_after_deleting(
    client, customer, product
):
    buy(customer, product)
    review = make_review(customer, product, comment="The first attempt.")
    client.force_login(customer)

    response = client.post(delete_url(review))

    page = response.content.decode()
    assert "Post review" in page
    assert create_url(product) in page
    client.post(create_url(product), VALID)
    assert Review.objects.get().comment == VALID["comment"]


def test_an_author_whose_order_was_cancelled_can_still_delete(
    client, customer, product
):
    """Then the slot has nothing to offer them: the not-bought note."""
    order = buy(customer, product)
    review = make_review(customer, product, comment="Before the refund.")
    order.status = Order.Status.CANCELLED
    order.save()
    client.force_login(customer)

    shown = client.get(delete_url(review))
    response = client.post(delete_url(review))

    assert shown.status_code == HTTPStatus.OK
    assert not Review.objects.exists()
    page = response.content.decode()
    assert NOT_BOUGHT in page
    assert "Post review" not in page


def test_another_customer_cannot_delete_a_review(client, customer, product):
    review = make_review(customer, product, comment="Not yours to delete.")
    client.force_login(shopper("dcole", "Dana", "Cole"))

    shown = client.get(delete_url(review))
    deleted = client.post(delete_url(review))

    assert (shown.status_code, deleted.status_code) == (
        HTTPStatus.NOT_FOUND,
        HTTPStatus.NOT_FOUND,
    )
    assert Review.objects.filter(pk=review.pk).exists()


def test_staff_cannot_delete_someone_elses_review(
    client, customer, staff_user, product
):
    """Staff take a review down with Remove, which keeps the row; delete is the author's."""
    review = make_review(customer, product)
    client.force_login(staff_user)

    assert client.get(delete_url(review)).status_code == HTTPStatus.NOT_FOUND
    assert client.post(delete_url(review)).status_code == HTTPStatus.NOT_FOUND
    assert Review.objects.filter(pk=review.pk).exists()


def test_a_staff_member_can_delete_their_own_review(client, staff_user, product):
    review = make_review(staff_user, product)
    client.force_login(staff_user)

    response = client.post(delete_url(review))

    assert response.status_code == HTTPStatus.OK
    assert not Review.objects.exists()


def test_visitors_are_sent_to_sign_in_from_delete(client, customer, product):
    review = make_review(customer, product)

    response = client.post(delete_url(review))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url
    assert Review.objects.exists()


def test_only_the_author_sees_delete_on_the_product_page(client, customer, product):
    mine = make_review(customer, product)
    theirs = make_review(shopper("dcole", "Dana", "Cole"), product)
    client.force_login(customer)

    page = client.get(product.get_absolute_url()).content.decode()

    assert delete_url(mine) in page
    assert delete_url(theirs) not in page


# --- Show more and sort ---------------------------------------------------------


def dated_review(username, product, *, rating, days_ago):
    """Another shopper's review of ``product``, written ``days_ago`` days ago."""
    review = make_review(shopper(username), product, rating=rating)
    review.created_at = timezone.now() - timedelta(days=days_ago)
    review.save()
    return review


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("newest", ["dee", "cal", "bea", "ada"]),
        ("highest", ["bea", "cal", "ada", "dee"]),
        ("lowest", ["dee", "cal", "ada", "bea"]),
        ("nonsense", ["dee", "cal", "bea", "ada"]),
    ],
)
def test_each_sort_orders_equal_ratings_newest_first(product, sort, expected):
    """Cal is written before Ada but dated after her, so the tie-break is the date."""
    dated_review("cal", product, rating=8, days_ago=2)
    dated_review("ada", product, rating=8, days_ago=4)
    dated_review("bea", product, rating=10, days_ago=3)
    dated_review("dee", product, rating=4, days_ago=1)

    reviews = Review.objects.filter(product=product).sorted_by(sort)

    assert [review.user.username for review in reviews] == expected


def list_url(product, **params):
    return f"{reverse('reviews:list', args=[product.pk])}?{urlencode(params)}"


REVIEW_ID = re.compile(r'<article id="review-(\d+)"')
SHOW_MORE = re.compile(r'id="show-more-reviews".*?hx-get="([^"]+)"', re.DOTALL)


def test_show_more_serves_ten_at_a_time_in_the_current_sort(client, product):
    """Following each page's own button walks the whole list once, in order."""
    for number in range(23):
        dated_review(
            f"shopper{number}", product, rating=2 + number % 9, days_ago=number
        )
    expected = list(Review.objects.sorted_by("highest").values_list("pk", flat=True))

    shown, page_sizes = [], []
    url = list_url(product, sort="highest")
    while url and len(page_sizes) < 5:
        page = client.get(url).content.decode()
        ids = [int(pk) for pk in REVIEW_ID.findall(page)]
        page_sizes.append(len(ids))
        shown += ids
        more = SHOW_MORE.search(page)
        url = html.unescape(more.group(1)) if more else None

    assert page_sizes == [10, 10, 3]
    assert shown == expected


@pytest.mark.parametrize("sort", ["newest", "highest", "lowest"])
def test_the_list_never_includes_the_viewers_own_or_a_removed_review(
    client, customer, product, sort
):
    """Their own review is in the slot; a removed one is hidden from everyone."""
    make_review(customer, product, rating=10)
    removed = dated_review("gfinch", product, rating=2, days_ago=0)
    removed.removed_at = timezone.now()
    removed.save()
    theirs = dated_review("dcole", product, rating=6, days_ago=3)
    client.force_login(customer)

    page = client.get(list_url(product, sort=sort)).content.decode()

    assert [int(pk) for pk in REVIEW_ID.findall(page)] == [theirs.pk]


@pytest.mark.parametrize(("count", "shown", "more"), [(10, 10, False), (11, 10, True)])
def test_the_product_page_shows_ten_reviews_then_show_more(
    client, product, count, shown, more
):
    for number in range(count):
        dated_review(f"shopper{number}", product, rating=8, days_ago=number)

    page = client.get(product.get_absolute_url()).content.decode()

    assert len(REVIEW_ID.findall(page)) == shown
    assert ("Show more reviews" in page) is more
    if more:
        assert html.escape(list_url(product, sort="newest", page=2)) in page


def test_the_sort_menu_offers_three_sorts_once_there_are_two_reviews(client, product):
    dated_review("dcole", product, rating=8, days_ago=1)
    alone = client.get(product.get_absolute_url()).content.decode()
    dated_review("gfinch", product, rating=8, days_ago=2)

    page = client.get(product.get_absolute_url()).content.decode()

    assert 'id="review-sort"' not in alone
    assert 'id="review-sort"' in page
    assert f'hx-get="{reverse("reviews:list", args=[product.pk])}"' in page
    for value, label in [
        ("newest", "Newest"),
        ("highest", "Highest rated"),
        ("lowest", "Lowest rated"),
    ]:
        assert f'value="{value}"' in page
        assert label in page
    assert '<option value="newest" selected>' in page


@pytest.mark.parametrize("page", ["3", "0", "abc"])
def test_a_page_that_isnt_there_is_a_404(client, product, page):
    for number in range(11):
        dated_review(f"shopper{number}", product, rating=8, days_ago=number)

    response = client.get(list_url(product, page=page))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_the_list_of_a_missing_product_is_a_404(client):
    response = client.get(reverse("reviews:list", args=[999]))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_a_sort_change_answers_with_page_one_only(client, product):
    """The partial alone, never the page: it replaces the list's contents."""
    for number in range(12):
        dated_review(
            f"shopper{number}", product, rating=2 + number % 9, days_ago=number
        )

    page = client.get(list_url(product, sort="lowest")).content.decode()

    assert len(REVIEW_ID.findall(page)) == 10
    assert "<html" not in page
    assert 'id="review-list"' not in page
    assert "sort=lowest&amp;page=2" in page


# --- The seed -------------------------------------------------------------------


def test_the_seeded_reviews_obey_the_features_own_rules(db):
    """Run twice: every author bought what they reviewed, and the demo states exist."""
    call_command("seed", stdout=io.StringIO())
    first = (Review.objects.count(), Order.objects.count())
    call_command("seed", stdout=io.StringIO())

    assert (Review.objects.count(), Order.objects.count()) == first
    assert Order.objects.count() == 53
    for review in Review.objects.select_related("user", "product"):
        assert (
            OrderItem.objects.filter(order__user=review.user, product=review.product)
            .exclude(order__status=Order.Status.CANCELLED)
            .exists()
        ), review

    casey = Review.objects.filter(user__username="customer")
    assert [review.product.slug for review in casey] == ["dreamweaver"]
    emory = Review.objects.get(user__username="employee")
    assert emory.by_staff
    assert Review.objects.filter(by_staff=True).count() == 1

    busiest = max(Product.objects.all(), key=lambda product: product.reviews.count())
    assert busiest.reviews.count() > 10
    ratings = set(Review.objects.values_list("rating", flat=True))
    assert ratings == set(Review.Rating.values)
    assert Review.objects.filter(headline="").exists()


def test_the_seeded_seraphine_needs_show_more(client):
    call_command("seed", stdout=io.StringIO())
    seraphine = Product.objects.get(slug="seraphine")

    page = client.get(seraphine.get_absolute_url()).content.decode()

    assert seraphine.reviews.live().count() > 10
    assert len(REVIEW_ID.findall(page)) == 10
    assert "Show more reviews" in page


# --- The rating picker ----------------------------------------------------------


def test_the_picker_offers_one_to_five_stars_in_half_steps():
    options = ReviewForm().rating_options()

    assert [option["value"] for option in options] == list(range(2, 11))
    assert options[0]["label"] == "1 star"
    assert options[1]["label"] == "1½ stars"
    assert options[-1]["label"] == "5 stars"
    assert [option["whole"] for option in options] == [True] + [False] * 8


def test_the_picker_has_a_labelled_radio_per_rating_and_no_half_star(
    client, customer, product
):
    buy(customer, product)
    client.force_login(customer)

    page = client.get(product.get_absolute_url()).content.decode()

    assert "rating-half" in page
    for value, label in Review.Rating.choices:
        assert f'value="{value}" aria-label="{label}"' in page
    assert 'value="1"' not in page
    assert 'aria-label="½ star"' not in page


# --- Catalog ratings: the soft dependency in with_ratings() ---------------------


def test_with_ratings_agrees_with_the_counted_set(
    customer, staff_user, product, featured_product, unavailable_product
):
    """``products`` repeats the counted set by string lookup; this keeps them in step.

    A renamed ``reviews`` field, or a counted-set rule changed on one side
    only, fails here rather than silently skewing the catalog.
    """
    make_review(shopper("dcole"), product, rating=7)
    make_review(shopper("rpatel"), product, rating=10)
    removed = make_review(customer, product, rating=2)
    Review.objects.filter(pk=removed.pk).update(removed_at=timezone.now())
    make_review(staff_user, product, rating=2)
    make_review(staff_user, featured_product, rating=10)
    make_review(customer, featured_product, rating=5)

    annotated = {
        item.pk: (item.rating_count, item.rating_average)
        for item in Product.objects.with_ratings()
    }

    expected = {}
    for item in (product, featured_product, unavailable_product):
        summary = Review.objects.filter(product=item).rating_summary()
        expected[item.pk] = (summary.count, summary.average)
    assert expected == {
        product.pk: (2, 4.25),
        featured_product.pk: (1, 2.5),
        unavailable_product.pk: (0, None),
    }
    assert annotated == expected


# --- Catalog ratings: sort and filter --------------------------------------------


def shelf(category, *names):
    """Products by ``names`` in ``category``, at one price."""
    return [
        Product.objects.create(name=name, price=Decimal("99.00"), category=category)
        for name in names
    ]


def review_all(product, *ratings, staff=False):
    """One review of ``product`` per rating, each by a new shopper."""
    for rating in ratings:
        author = shopper(f"{product.slug}-{Review.objects.count()}")
        author.is_staff = staff
        author.save()
        make_review(author, product, rating=rating)


def test_sort_by_rating_orders_by_average_then_count_then_name(category):
    """Highest average, more reviews breaking ties, then name; unreviewed last.

    Brainwave Buds has only a staff review, so it counts as unreviewed.
    Created in neither name nor rating order, so neither can pass by luck.
    """
    aurora, mnemo, echo, brainwave, zephyr, cogitator, seraphine = shelf(
        category,
        "Aurora Lens",
        "Mnemo Clip",
        "EchoPatch",
        "Brainwave Buds",
        "Zephyr Band",
        "Cogitator Crown",
        "Seraphine Home Hub",
    )
    review_all(zephyr, 9, 9)
    review_all(seraphine, 9)
    review_all(cogitator, 8)
    review_all(echo, 8)
    review_all(mnemo, 2, 2, 2)
    review_all(brainwave, 10, staff=True)

    ordered = Product.objects.with_ratings().by_rating()

    assert [item.name for item in ordered] == [
        "Zephyr Band",
        "Seraphine Home Hub",
        "Cogitator Crown",
        "EchoPatch",
        "Mnemo Clip",
        "Aurora Lens",
        "Brainwave Buds",
    ]


def test_lowest_rated_puts_the_worst_first_and_unreviewed_last(category):
    """Lowest average first, more reviews breaking ties, then name; unreviewed last.

    Created in neither name nor rating order, so neither can pass by luck.
    """
    aurora, zephyr, clip, brainwave, mnemo, cogitator = shelf(
        category,
        "Aurora Lens",
        "Zephyr Band",
        "Clip Two",
        "Brainwave Buds",
        "Mnemo Clip",
        "Cogitator Crown",
    )
    review_all(zephyr, 9)
    review_all(clip, 2)
    review_all(mnemo, 2, 2, 2)
    review_all(cogitator, 8)
    review_all(brainwave, 2, staff=True)

    ordered = Product.objects.with_ratings().by_rating(lowest_first=True)

    assert [item.name for item in ordered] == [
        "Mnemo Clip",
        "Clip Two",
        "Cogitator Crown",
        "Zephyr Band",
        "Aurora Lens",
        "Brainwave Buds",
    ]


BAND_SHELF = {
    # name -> customer ratings in half stars, then staff ratings
    "Five": ([10], []),
    "Four Point Seven Five": ([9, 10], []),
    "Exactly Four": ([7, 9], []),
    "Three Point Seven Five": ([7, 8], []),
    "Three": ([6], [10]),
    "One": ([2], []),
    "Unreviewed": ([], []),
    "Staff Only": ([], [8]),
}


@pytest.mark.parametrize(
    ("stars", "kept"),
    [
        ([5], ["Five"]),
        ([4], ["Exactly Four", "Four Point Seven Five"]),
        ([3, 5], ["Five", "Three", "Three Point Seven Five"]),
        ([1], ["One"]),
        ([2], []),
    ],
)
def test_star_bands_cover_their_whole_star(category, stars, kept):
    """4 is 4.0 up to, not including, 5.0; 5 is exactly 5.0; unreviewed is in none.

    Staff reviews never move a product into a band: "Three" has a staff
    5 stars on top of its customer 3, and "Staff Only" is unreviewed.
    """
    for item in shelf(category, *BAND_SHELF):
        customer_ratings, staff_ratings = BAND_SHELF[item.name]
        review_all(item, *customer_ratings)
        review_all(item, *staff_ratings, staff=True)

    found = Product.objects.with_ratings().rated_in(stars)

    assert sorted(item.name for item in found) == kept


def test_no_star_bands_filters_nothing(category):
    rated, unreviewed = shelf(category, "Rated", "Unreviewed")
    review_all(rated, 6)

    assert Product.objects.with_ratings().rated_in([]).count() == 2


# --- Catalog ratings: the catalog and category pages ------------------------------


def catalog(client, **params):
    return client.get(reverse("products:catalog"), params)


def names(response):
    return [item.name for item in response.context["products"]]


def test_the_annotation_survives_the_tag_filters_join(category, tag):
    """Several tags and several reviews: the tag join mustn't multiply either."""
    hub, other = shelf(category, "Tagged Hub", "Untagged Hub")
    hub.tags.add(
        tag,
        Tag.objects.create(name="smart home", slug="smart-home"),
        Tag.objects.create(name="new", slug="new"),
    )
    review_all(hub, 6, 8, 10)
    review_all(other, 2)

    for products in (
        Product.objects.with_ratings().filter(tags__slug=tag.slug),
        Product.objects.filter(tags__slug=tag.slug).with_ratings(),
    ):
        [found] = products
        assert (found.name, found.rating_count, found.rating_average) == (
            "Tagged Hub",
            3,
            4.0,
        )


def test_the_tag_filtered_catalog_shows_the_right_numbers(client, category, tag):
    hub, other = shelf(category, "Tagged Hub", "Untagged Hub")
    hub.tags.add(tag, Tag.objects.create(name="smart home", slug="smart-home"))
    review_all(hub, 6, 8, 10)

    response = catalog(client, tag=tag.slug)

    [found] = response.context["products"]
    assert (found.rating_count, found.rating_average) == (3, 4.0)
    assert "4.0" in response.content.decode()


def test_the_catalog_stays_in_name_order_by_default(client, category):
    """``with_ratings()`` groups, and a grouped query drops ``Meta.ordering``."""
    shelf(category, "Mnemo Clip", "Aurora Lens", "Zephyr Band")

    assert names(catalog(client)) == ["Aurora Lens", "Mnemo Clip", "Zephyr Band"]


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("highest", ["Zephyr Band", "Mnemo Clip", "Aurora Lens"]),
        ("lowest", ["Mnemo Clip", "Zephyr Band", "Aurora Lens"]),
    ],
)
def test_the_catalog_sorts_by_rating_either_way(client, category, sort, expected):
    aurora, mnemo, zephyr = shelf(category, "Aurora Lens", "Mnemo Clip", "Zephyr Band")
    review_all(mnemo, 6)
    review_all(zephyr, 10)

    assert names(catalog(client, sort=sort)) == expected


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "price"},
        {"sort": "rating"},
        {"rating": "0"},
        {"rating": "6"},
        {"rating": "x"},
    ],
)
def test_unknown_sorts_and_ratings_are_ignored(client, category, params):
    aurora, zephyr = shelf(category, "Aurora Lens", "Zephyr Band")
    review_all(zephyr, 10)

    response = catalog(client, **params)

    assert response.status_code == HTTPStatus.OK
    assert names(response) == ["Aurora Lens", "Zephyr Band"]


def test_ticked_star_boxes_filter_the_catalog(client, category):
    five, four, three, unreviewed = shelf(
        category, "Five Star", "Four Star", "Three Star", "Unreviewed"
    )
    review_all(five, 10)
    review_all(four, 8)
    review_all(three, 7)

    response = catalog(client, rating=["5", "4"])

    assert names(response) == ["Five Star", "Four Star"]
    assert "averaging 4 or 5 stars" in response.content.decode()


@pytest.mark.parametrize(
    ("stars", "phrase"),
    [
        ([1], "1 star"),
        ([5], "5 stars"),
        ([5, 4], "4 or 5 stars"),
        ([5, 3, 1], "1, 3 or 5 stars"),
    ],
)
def test_the_ticked_bands_read_as_words(stars, phrase):
    assert stars_phrase(stars) == phrase


def test_rating_sort_and_filter_compose_with_search_tag_and_category(
    client, category, tag
):
    defense = Category.objects.create(name="Defense", slug="defense")
    hub, hub_low, hub_plain, hub_untagged = shelf(
        category, "Hub Prime", "Hub Lite", "Hub Basic", "Hub Untagged"
    )
    [hub_elsewhere] = shelf(defense, "Hub Shield")
    [other] = shelf(category, "Neural Band")
    for item in (hub, hub_low, hub_plain, hub_elsewhere, other):
        item.tags.add(tag)
    review_all(hub, 8, 9)
    review_all(hub_low, 8)
    review_all(hub_plain, 7)
    review_all(hub_untagged, 10)
    review_all(hub_elsewhere, 10)
    review_all(other, 10)
    params = {"q": "hub", "tag": tag.slug, "sort": "lowest", "rating": ["4", "5"]}

    on_catalog = catalog(client, category=category.slug, **params)
    on_category = client.get(category.get_absolute_url(), params)

    assert names(on_catalog) == ["Hub Lite", "Hub Prime"]
    assert names(on_category) == ["Hub Lite", "Hub Prime"]


def test_pagination_and_both_forms_keep_the_other_controls(client, category, tag):
    for item in shelf(category, *(f"Widget {n:02d}" for n in range(13))):
        item.tags.add(tag)
        review_all(item, 9)
    params = {"q": "widget", "tag": tag.slug, "sort": "highest", "rating": ["4", "5"]}

    first = catalog(client, **params)
    second = catalog(client, **params, page="2")

    page = html.unescape(first.content.decode())
    assert "?q=widget&tag=bestseller&sort=highest&rating=4&rating=5&page=2" in page
    # The search form carries the sort and ratings; the rating form, search and tag.
    for name, value in [
        ("sort", "highest"),
        ("rating", "5"),
        ("rating", "4"),
        ("q", "widget"),
        ("tag", "bestseller"),
    ]:
        assert f'<input type="hidden" name="{name}" value="{value}" />' in page
    assert names(second) == ["Widget 12"]
    assert "Page 2 of 2" in second.content.decode()


CHECKED_BOX = re.compile(r'value="(\d)"\s+class="[^"]*"\s+checked')


def test_the_controls_show_which_are_active(client, category):
    shelf(category, "Aurora Lens")

    plain = catalog(client).content.decode()
    active = catalog(client, sort="lowest", rating=["4", "5"]).content.decode()

    assert re.search(r'aria-current="true">\s*Name', plain)
    assert CHECKED_BOX.findall(plain) == []
    assert re.search(r'aria-current="true">\s*Lowest rated', active)
    assert "lowest rated first" in active
    assert CHECKED_BOX.findall(active) == ["5", "4"]
    assert "Nothing here averages 4 or 5 stars yet" in active


def test_cards_show_the_customer_average_or_no_reviews_yet(
    client, customer, staff_user, category
):
    rated, staff_only = shelf(category, "Rated Hub", "Staff Only")
    review_all(rated, 7, 9)
    removed = make_review(customer, rated, rating=2)
    Review.objects.filter(pk=removed.pk).update(removed_at=timezone.now())
    review_all(staff_only, 10, staff=True)

    page = catalog(client).content.decode()

    assert '4.0<span class="sr-only"> out of 5 stars</span> · 2 reviews' in page
    assert page.count("No reviews yet") == 1


def test_rendering_the_catalog_adds_no_query_per_card(client, category):
    [first] = shelf(category, "Product 00")
    review_all(first, 8)
    with CaptureQueriesContext(connection) as one_card:
        catalog(client)

    for item in shelf(category, *(f"Product {n:02d}" for n in range(1, 8))):
        review_all(item, 6, 9)
    with CaptureQueriesContext(connection) as eight_cards:
        response = catalog(client)

    assert len(response.context["products"]) == 8
    assert len(eight_cards) == len(one_card)


# --- Staff edit (HTMX) ------------------------------------------------------------


def moderate_url(review):
    return reverse("reviews:moderate", kwargs={"pk": review.pk})


STAFF_FIX = {"headline": "Tidied up", "comment": "Corrected by the store."}


def test_only_staff_moderate_and_only_other_peoples_reviews(
    client, customer, staff_user, product
):
    """Staff edit someone else's review here; everyone else, and their own, is a 404.

    Another customer is outside the one permission rule. An author, staff
    or not, edits their own review as its author, so the moderate
    endpoints never touch it.
    """
    customers = make_review(customer, product, comment="The customer's words.")
    staffs = make_review(staff_user, product, comment="The employee's words.")
    dana = shopper("dcole", "Dana", "Cole")

    refused = [
        (dana, customers),
        (customer, customers),
        (staff_user, staffs),
    ]
    for user, review in refused:
        client.force_login(user)
        shown = client.get(moderate_url(review))
        saved = client.post(moderate_url(review), STAFF_FIX)
        assert (shown.status_code, saved.status_code) == (
            HTTPStatus.NOT_FOUND,
            HTTPStatus.NOT_FOUND,
        ), (user.username, review.comment)

    for review, comment in [
        (customers, "The customer's words."),
        (staffs, "The employee's words."),
    ]:
        review.refresh_from_db()
        assert (review.comment, review.moderated_at) == (comment, None)

    client.force_login(staff_user)
    assert client.get(moderate_url(customers)).status_code == HTTPStatus.OK


def test_a_staff_save_corrects_the_text_and_never_the_rating(
    client, customer, staff_user, product
):
    """Headline and comment change; a POSTed rating is ignored; it's moderation, not an edit."""
    review = make_review(customer, product, rating=8, comment="Something abusive here.")
    client.force_login(staff_user)

    client.post(moderate_url(review), {**STAFF_FIX, "rating": "2"})

    review.refresh_from_db()
    assert (review.rating, review.headline, review.comment) == (
        8,
        "Tidied up",
        "Corrected by the store.",
    )
    assert review.moderated_at is not None
    assert review.moderated_by == staff_user
    assert review.edited_at is None


EDITED_LABEL = re.compile(r"·\s*Edited\b(?! by)")


def test_the_staff_label_wins_and_never_names_the_staff_member(client, product):
    """Edited by its author and then by staff: shoppers see only the staff label."""
    moderator = get_user_model().objects.create_user(
        username="qmoderator", first_name="Quinn", last_name="Ashby", is_staff=True
    )
    review = make_review(shopper("dcole", "Dana", "Cole"), product)
    review.edited_at = timezone.now()
    review.moderated_at = timezone.now()
    review.moderated_by = moderator
    review.save()

    page = client.get(product.get_absolute_url()).content.decode()

    assert "· Edited by ThoughtTronix staff" in page
    assert not EDITED_LABEL.search(page)
    for name in ("qmoderator", "Quinn", "Ashby"):
        assert name not in page


def test_staff_see_edit_on_other_peoples_reviews_and_customers_dont(
    client, customer, staff_user, product
):
    theirs = make_review(shopper("dcole", "Dana", "Cole"), product)
    buy(staff_user, product)
    own = make_review(staff_user, product)

    client.force_login(staff_user)
    as_staff = client.get(product.get_absolute_url()).content.decode()
    client.force_login(customer)
    as_customer = client.get(product.get_absolute_url()).content.decode()

    assert moderate_url(theirs) in as_staff
    assert moderate_url(own) not in as_staff
    assert edit_url(own) in as_staff
    assert moderate_url(theirs) not in as_customer


def test_the_staff_form_has_no_rating_and_changes_nothing(
    client, customer, staff_user, product
):
    review = make_review(customer, product, rating=7, comment="As first written.")
    client.force_login(staff_user)

    response = client.get(moderate_url(review))

    page = response.content.decode()
    assert "<html" not in page
    assert f'<form id="review-{review.pk}"' in page
    assert f'hx-post="{moderate_url(review)}"' in page
    assert f'hx-get="{detail_url(review)}"' in page
    assert 'name="rating"' not in page
    assert 'name="headline"' in page
    assert "As first written." in page
    assert "3½ stars" in page
    review.refresh_from_db()
    assert (review.comment, review.moderated_at) == ("As first written.", None)


def test_staff_cancel_returns_the_review_as_it_was(
    client, customer, staff_user, product
):
    review = make_review(customer, product, comment="Untouched by Cancel.")
    client.force_login(staff_user)
    client.get(moderate_url(review))

    page = client.get(detail_url(review)).content.decode()

    assert page.strip().startswith(f'<article id="review-{review.pk}"')
    assert "Untouched by Cancel." in page
    assert "Edited" not in page
    assert f'hx-get="{moderate_url(review)}"' in page


def test_a_staff_save_answers_with_the_labelled_review(
    client, customer, staff_user, product
):
    review = make_review(customer, product, comment="Something abusive here.")
    client.force_login(staff_user)

    response = client.post(moderate_url(review), STAFF_FIX)

    page = response.content.decode()
    assert page.strip().startswith(f'<article id="review-{review.pk}"')
    assert "Corrected by the store." in page
    assert "· Edited by ThoughtTronix staff" in page
    assert "hx-swap-oob" not in page
    assert "employee" not in page


def test_a_staff_save_without_a_change_isnt_moderation(
    client, customer, staff_user, product
):
    review = make_review(customer, product, comment="Nothing to fix here.")
    client.force_login(staff_user)

    client.post(
        moderate_url(review), {"headline": "", "comment": "Nothing to fix here."}
    )

    review.refresh_from_db()
    assert (review.moderated_at, review.moderated_by) == (None, None)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"headline": "h" * 101}, "Ensure this value has at most 100 characters"),
        ({"comment": "   too short   "}, "Write at least 10 characters."),
        ({"comment": "x" * 2001}, "Keep it to 2,000 characters (this has 2,001)."),
    ],
)
def test_an_invalid_staff_edit_re_renders_the_form_and_saves_nothing(
    client, customer, staff_user, product, changes, message
):
    review = make_review(customer, product, comment="Still the original.")
    client.force_login(staff_user)

    response = client.post(moderate_url(review), {**STAFF_FIX, **changes})

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert f'<form id="review-{review.pk}"' in page
    assert f'hx-post="{moderate_url(review)}"' in page
    assert page.count(message) == 1
    review.refresh_from_db()
    assert (review.comment, review.moderated_at) == ("Still the original.", None)


def test_staff_cannot_moderate_a_removed_review(client, customer, staff_user, product):
    review = make_review(customer, product)
    review.removed_at = timezone.now()
    review.save()
    client.force_login(staff_user)

    assert client.get(moderate_url(review)).status_code == HTTPStatus.NOT_FOUND


def test_visitors_are_sent_to_sign_in_from_moderate(client, customer, product):
    review = make_review(customer, product)

    response = client.post(moderate_url(review), STAFF_FIX)

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url
    review.refresh_from_db()
    assert review.moderated_at is None


def test_moderated_wins_over_edited_in_the_label(customer, product):
    review = make_review(customer, product)
    assert review.edit_label == ""

    review.edited_at = timezone.now()
    assert review.edit_label == "Edited"

    review.moderated_at = timezone.now()
    assert review.edit_label == "Edited by ThoughtTronix staff"


def test_the_seed_has_one_review_edited_by_staff(client):
    call_command("seed", stdout=io.StringIO())

    moderated = Review.objects.get(moderated_at__isnull=False)
    page = client.get(moderated.product.get_absolute_url()).content.decode()

    assert moderated.moderated_by.username == "employee"
    assert moderated.moderated_at > moderated.created_at
    assert "4417" not in moderated.comment
    assert "· Edited by ThoughtTronix staff" in page


# --- Staff remove (HTMX) ----------------------------------------------------------


def remove_url(review):
    return reverse("reviews:remove", kwargs={"pk": review.pk})


def test_only_staff_remove_and_only_other_peoples_reviews(
    client, customer, staff_user, product
):
    """Staff remove someone else's review; everyone else, and their own, is a 404.

    Another customer is outside the one permission rule; an author, staff
    or not, deletes their own review rather than removing it. The
    confirmation GET changes nothing, even for staff.
    """
    customers = make_review(customer, product, comment="The customer's words.")
    staffs = make_review(staff_user, product, comment="The employee's words.")
    dana = shopper("dcole", "Dana", "Cole")

    for user, review in [
        (dana, customers),
        (customer, customers),
        (staff_user, staffs),
    ]:
        client.force_login(user)
        shown = client.get(remove_url(review))
        removed = client.post(remove_url(review))
        assert (shown.status_code, removed.status_code) == (
            HTTPStatus.NOT_FOUND,
            HTTPStatus.NOT_FOUND,
        ), (user.username, review.comment)

    client.force_login(staff_user)
    confirm = client.get(remove_url(customers))
    assert confirm.status_code == HTTPStatus.OK
    assert "Remove this review?" in confirm.content.decode()
    assert not Review.objects.filter(removed_at__isnull=False).exists()

    client.post(remove_url(customers))

    customers.refresh_from_db()
    staffs.refresh_from_db()
    assert customers.removed_at is not None
    assert customers.removed_by == staff_user
    assert (staffs.removed_at, staffs.removed_by) == (None, None)


def test_a_removed_review_leaves_every_list_and_number(client, staff_user, category):
    """Removing the one-star review lifts the average from 3.0 to 5.0 everywhere.

    The response swaps both averages out of band; the product page, the
    list endpoint, ``with_ratings()``, the catalog's rating sort and its
    star filter all forget the review.
    """
    gadget, rival = shelf(category, "Gadget", "Rival")
    make_review(shopper("dcole", "Dana", "Cole"), gadget, rating=10)
    removed = make_review(
        shopper("gfinch", "Gordon", "Finch"),
        gadget,
        rating=2,
        comment="Taken down by the store.",
    )
    review_all(rival, 8)
    assert names(catalog(client, sort="highest")) == ["Rival", "Gadget"]
    client.force_login(staff_user)

    answer = client.post(remove_url(removed)).content.decode()

    assert re.search(r'id="reviews-summary"[^>]*hx-swap-oob="true"', answer)
    assert re.search(r'id="details-rating"[^>]*hx-swap-oob="true"', answer)
    assert "5.0 from 1 customer review" in answer
    assert "5.0 · 1 customer review" in answer
    assert f"review-{removed.pk}" not in answer

    page = client.get(gadget.get_absolute_url()).content.decode()
    listed = client.get(list_url(gadget)).content.decode()
    for shown in (page, listed):
        assert str(removed.pk) not in REVIEW_ID.findall(shown)
        assert "Taken down by the store." not in shown
    assert "5.0 from 1 customer review" in page

    rated = Product.objects.with_ratings().get(pk=gadget.pk)
    assert (rated.rating_count, rated.rating_average) == (1, 5.0)
    assert names(catalog(client, sort="highest")) == ["Gadget", "Rival"]
    assert names(catalog(client, sort="lowest")) == ["Rival", "Gadget"]
    assert names(catalog(client, rating="5")) == ["Gadget"]
    assert names(catalog(client, rating="1")) == []


REMOVED_NOTICE = "Your review was removed by ThoughtTronix staff."
TEXT_DELETED = "You've deleted its text."


def test_a_removed_review_still_blocks_its_author(
    client, customer, staff_user, product
):
    """The author sees the notice, never the form, before and after deleting its text.

    Their delete blanks the headline and comment but keeps the row, which
    still holds the one-review-per-product constraint, so a direct create
    POST writes nothing either side of it.
    """
    buy(customer, product)
    review = make_review(customer, product, comment="Words staff took down.")
    review.headline = "A headline too"
    review.save()
    review.remove(staff_user)
    client.force_login(customer)

    page = client.get(product.get_absolute_url()).content.decode()
    assert REMOVED_NOTICE in page
    assert TEXT_DELETED not in page
    assert "Words staff took down." not in page
    assert create_url(product) not in page
    assert f'hx-get="{delete_url(review)}"' in page

    blocked = client.post(create_url(product), VALID).content.decode()
    assert REMOVED_NOTICE in blocked
    assert Review.objects.filter(user=customer).count() == 1

    answer = client.post(delete_url(review)).content.decode()

    review.refresh_from_db()
    assert (review.headline, review.comment) == ("", "")
    assert review.removed_at is not None
    assert REMOVED_NOTICE in answer
    assert TEXT_DELETED in answer
    assert delete_url(review) not in answer
    assert create_url(product) not in answer

    client.post(create_url(product), VALID)
    assert list(Review.objects.filter(user=customer)) == [review]


def test_staff_see_remove_on_other_peoples_reviews_and_customers_dont(
    client, customer, staff_user, product
):
    theirs = make_review(shopper("dcole", "Dana", "Cole"), product)
    buy(staff_user, product)
    own = make_review(staff_user, product)

    client.force_login(staff_user)
    as_staff = client.get(product.get_absolute_url()).content.decode()
    client.force_login(customer)
    as_customer = client.get(product.get_absolute_url()).content.decode()

    assert f'hx-get="{remove_url(theirs)}"' in as_staff
    assert f'id="review-row-{theirs.pk}"' in as_staff
    assert remove_url(own) not in as_staff
    assert remove_url(theirs) not in as_customer


def test_the_remove_confirmation_swaps_the_row_away_or_cancels(
    client, customer, staff_user, product
):
    """Remove targets the review's whole row; Cancel fetches the review back unchanged."""
    review = make_review(customer, product, comment="Still here after Cancel.")
    client.force_login(staff_user)

    confirm = client.get(remove_url(review)).content.decode()

    assert "<html" not in confirm
    assert confirm.strip().startswith(f'<div id="review-{review.pk}"')
    assert f'hx-post="{remove_url(review)}"' in confirm
    assert f'hx-target="#review-row-{review.pk}"' in confirm
    assert f'hx-get="{detail_url(review)}"' in confirm

    cancelled = client.get(detail_url(review)).content.decode()

    assert cancelled.strip().startswith(f'<article id="review-{review.pk}"')
    assert "Still here after Cancel." in cancelled
    review.refresh_from_db()
    assert (review.removed_at, review.removed_by) == (None, None)


def test_a_removed_review_is_out_of_staff_reach_on_the_product_page(
    client, customer, staff_user, product
):
    """Once removed, staff can't fetch, remove, edit or delete it from here."""
    review = make_review(customer, product)
    review.remove(staff_user)
    client.force_login(staff_user)

    for url in (
        detail_url(review),
        remove_url(review),
        moderate_url(review),
        delete_url(review),
    ):
        assert client.get(url).status_code == HTTPStatus.NOT_FOUND, url
    assert client.post(remove_url(review)).status_code == HTTPStatus.NOT_FOUND


def test_visitors_are_sent_to_sign_in_from_remove(client, customer, product):
    review = make_review(customer, product)

    response = client.post(remove_url(review))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url
    review.refresh_from_db()
    assert review.removed_at is None


def test_deleting_a_removed_reviews_text_asks_first(
    client, customer, staff_user, product
):
    """The confirmation names the text, changes nothing, and Keep it brings back the notice."""
    review = make_review(customer, product, comment="Words staff took down.")
    review.remove(staff_user)
    client.force_login(customer)

    confirm = client.get(delete_url(review)).content.decode()

    assert "Delete your review's text? This can't be undone." in confirm
    assert "Words staff took down." not in confirm
    assert f'hx-post="{delete_url(review)}"' in confirm
    assert f'hx-get="{detail_url(review)}"' in confirm
    review.refresh_from_db()
    assert review.comment == "Words staff took down."


def test_another_customer_cannot_delete_a_removed_reviews_text(
    client, customer, staff_user, product
):
    review = make_review(customer, product, comment="Words staff took down.")
    review.remove(staff_user)
    client.force_login(shopper("dcole", "Dana", "Cole"))

    assert client.post(delete_url(review)).status_code == HTTPStatus.NOT_FOUND
    review.refresh_from_db()
    assert review.comment == "Words staff took down."


def test_the_seed_has_one_removed_review_and_its_author_sees_the_notice(client):
    call_command("seed", stdout=io.StringIO())

    removed = Review.objects.get(removed_at__isnull=False)
    assert removed.removed_by.username == "employee"
    assert removed.removed_at > removed.created_at
    assert not removed.by_staff

    visitor = client.get(removed.product.get_absolute_url()).content.decode()
    assert removed.comment not in visitor
    assert str(removed.pk) not in REVIEW_ID.findall(visitor)

    client.force_login(removed.user)
    page = client.get(removed.product.get_absolute_url()).content.decode()
    assert REMOVED_NOTICE in page
    assert removed.comment not in page
