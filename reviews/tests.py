"""Reviews: eligibility, the model's rules, the "Your review" slot and create."""

from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem

from .forms import ReviewForm
from .models import Review

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
