"""Reviews: eligibility, the model's rules, the "Your review" slot and create."""

import io
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem
from products import images
from products.models import Product

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
