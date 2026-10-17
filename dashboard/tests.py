"""The dashboard: aggregation queries against hand-computed data, then the view.

Orders here are created directly — small, explicit datasets whose
expected numbers fit in a code review.
"""

from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem
from reviews.models import Review

from . import queries

pytestmark = pytest.mark.django_db


def make_order(user, total, *, days_ago=0, status=Order.Status.PLACED):
    """One order, backdated ``days_ago``, with the addresses boilerplate.

    Backdates by a hair under ``days_ago`` days, so an order sits just
    inside a ``since(days_ago)`` cutoff computed moments later.
    """
    return Order.objects.create(
        user=user,
        status=status,
        total=Decimal(total),
        email="casey@example.com",
        shipping_name="Casey Monroe",
        shipping_street="9 Synapse Court",
        shipping_city="Canyon",
        shipping_state="TX",
        shipping_zip="79015",
        billing_name="Casey Monroe",
        billing_street="9 Synapse Court",
        billing_city="Canyon",
        billing_state="TX",
        billing_zip="79015",
        card_last4="4242",
        created_at=timezone.now() - timedelta(days=days_ago) + timedelta(seconds=5),
    )


def add_item(order, name, unit_price, quantity=1):
    return OrderItem.objects.create(
        order=order,
        product=None,
        product_name=name,
        unit_price=Decimal(unit_price),
        quantity=quantity,
    )


def since(days):
    return timezone.now() - timedelta(days=days)


# --- Totals: revenue, count, average ------------------------------------------


def test_the_empty_store_reports_zeros(db):
    assert queries.total_revenue() == Decimal("0.00")
    assert queries.order_count() == 0
    assert queries.average_order_value() == Decimal("0.00")
    assert queries.revenue_over_time() == []
    assert queries.top_products() == []


def test_revenue_sums_order_totals(customer):
    make_order(customer, "100.00")
    make_order(customer, "49.50")

    assert queries.total_revenue() == Decimal("149.50")
    assert queries.order_count() == 2


def test_cancelled_orders_never_count(customer):
    make_order(customer, "100.00", status=Order.Status.DELIVERED)
    make_order(customer, "999.00", status=Order.Status.CANCELLED)

    assert queries.total_revenue() == Decimal("100.00")
    assert queries.order_count() == 1
    assert queries.average_order_value() == Decimal("100.00")


def test_since_cuts_off_older_orders(customer):
    make_order(customer, "100.00", days_ago=100)
    make_order(customer, "40.00", days_ago=5)

    assert queries.total_revenue(since(30)) == Decimal("40.00")
    assert queries.order_count(since(30)) == 1
    assert queries.total_revenue() == Decimal("140.00")


def test_average_order_value_rounds_to_cents(customer):
    make_order(customer, "10.00")
    make_order(customer, "10.00")
    make_order(customer, "10.01")

    # 30.01 / 3 = 10.00333... -> 10.00
    assert queries.average_order_value() == Decimal("10.00")


# --- Revenue over time ---------------------------------------------------------


def test_daily_series_fills_quiet_days_with_zero(customer):
    make_order(customer, "100.00", days_ago=3)
    make_order(customer, "25.00", days_ago=3)
    make_order(customer, "50.00", days_ago=1)

    series = queries.revenue_over_time(since(3), bucket="day")

    assert [point["revenue"] for point in series] == [
        Decimal("125.00"),  # 3 days ago
        Decimal("0.00"),  # 2 days ago — no sales
        Decimal("50.00"),  # yesterday
        Decimal("0.00"),  # today — no sales
    ]
    assert [point["bucket"] for point in series] == [
        timezone.localdate() - timedelta(days=days) for days in (3, 2, 1, 0)
    ]


def test_weekly_buckets_start_on_monday(customer):
    make_order(customer, "75.00")

    series = queries.revenue_over_time(since(0), bucket="week")

    assert len(series) == 1
    assert series[0]["bucket"].weekday() == 0
    assert series[0]["revenue"] == Decimal("75.00")


def test_monthly_series_spans_first_sale_to_today(customer):
    make_order(customer, "60.00", days_ago=70)

    series = queries.revenue_over_time(bucket="month")

    assert series[0]["bucket"].day == 1
    assert series[0]["revenue"] == Decimal("60.00")
    assert series[-1]["bucket"] == timezone.localdate().replace(day=1)
    assert sum(point["revenue"] for point in series) == Decimal("60.00")
    assert 3 <= len(series) <= 4  # 70 days back is 2–3 calendar months ago


def test_series_excludes_cancelled_and_out_of_period_orders(customer):
    make_order(customer, "999.00", status=Order.Status.CANCELLED)
    make_order(customer, "100.00", days_ago=50)

    assert queries.revenue_over_time(since(7), bucket="day") == []


# --- Top products --------------------------------------------------------------


def test_top_products_rank_by_revenue_not_units(customer):
    order = make_order(customer, "0.00")
    add_item(order, "Electrode Contact Gel (3-Pack)", "14.00", quantity=5)  # 70.00
    add_item(order, "MindSync Solo", "899.00", quantity=1)  # 899.00

    top = queries.top_products()

    assert [entry["product_name"] for entry in top] == [
        "MindSync Solo",
        "Electrode Contact Gel (3-Pack)",
    ]
    assert top[0]["revenue"] == Decimal("899.00")
    assert top[1] == {
        "product_name": "Electrode Contact Gel (3-Pack)",
        "revenue": Decimal("70.00"),
        "units": 5,
    }


def test_top_products_merge_lines_across_orders(customer):
    add_item(make_order(customer, "0.00"), "NapCap", "89.00", quantity=1)
    add_item(make_order(customer, "0.00"), "NapCap", "89.00", quantity=2)

    top = queries.top_products()

    assert len(top) == 1
    assert top[0]["units"] == 3
    assert top[0]["revenue"] == Decimal("267.00")


def test_top_products_respect_limit_cancellation_and_period(customer):
    cancelled = make_order(customer, "0.00", status=Order.Status.CANCELLED)
    add_item(cancelled, "SoulSear Mark II", "2400000.00")
    old = make_order(customer, "0.00", days_ago=100)
    add_item(old, "ThoughtPad Classic", "199.00")
    for price, name in enumerate(["Hush", "Whisper", "Pulse Halo"], start=1):
        add_item(make_order(customer, "0.00"), name, price)

    top = queries.top_products(since(30), limit=2)

    assert [entry["product_name"] for entry in top] == ["Pulse Halo", "Whisper"]


# --- Reviews ------------------------------------------------------------------


def make_review(username, product, rating, *, days_ago=0, staff=False):
    """One review by a fresh user, backdated like ``make_order``."""
    author = get_user_model().objects.create_user(username=username, is_staff=staff)
    return Review.objects.create(
        user=author,
        product=product,
        rating=rating,
        comment="Does what it promises.",
        created_at=timezone.now() - timedelta(days=days_ago) + timedelta(seconds=5),
    )


def test_review_summary_counts_only_live_customer_reviews(product):
    make_review("ada", product, 8)
    make_review("bo", product, 10)
    make_review("employee", product, 2, staff=True)
    removed = make_review("cy", product, 2)
    removed.removed_at = timezone.now()
    removed.save()

    summary = queries.review_summary()

    assert (summary.count, summary.average) == (2, 4.5)


def test_review_summary_counts_from_since_or_all_time(product):
    make_review("ada", product, 10, days_ago=5)
    make_review("bo", product, 6, days_ago=29)
    make_review("cy", product, 2, days_ago=60)

    recent = queries.review_summary(since(30))
    ever = queries.review_summary(None)

    assert (recent.count, recent.average) == (2, 4.0)
    assert (ever.count, ever.average) == (3, 3.0)


def test_review_summary_of_an_empty_period_is_zero_with_no_average(product):
    make_review("ada", product, 8, days_ago=60)

    summary = queries.review_summary(since(30))

    assert (summary.count, summary.average) == (0, None)


def test_review_summary_is_documented_and_typed():
    assert queries.review_summary.__doc__
    assert set(queries.review_summary.__annotations__) == {"since", "return"}


# --- The view ------------------------------------------------------------------


def test_anonymous_users_are_sent_to_login(client):
    response = client.get(reverse("dashboard:index"))

    assert response.status_code == HTTPStatus.FOUND
    assert reverse("accounts:login") in response.url


def test_customers_get_403(client, customer):
    client.force_login(customer)

    assert client.get(reverse("dashboard:index")).status_code == HTTPStatus.FORBIDDEN


def test_staff_see_the_numbers(client, staff_user, customer):
    make_order(customer, "1234.56")
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "$1,234.56" in page
    assert "Total revenue" in page
    assert "Top products" in page


def test_default_period_is_30_days(client, staff_user, customer):
    make_order(customer, "100.00", days_ago=60)
    make_order(customer, "40.00", days_ago=5)
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "$40.00" in page
    assert "$140.00" not in page


def test_all_time_counts_everything(client, staff_user, customer):
    make_order(customer, "100.00", days_ago=60)
    make_order(customer, "40.00", days_ago=5)
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index"), {"period": "all"}).content.decode()

    assert "$140.00" in page


def test_an_unknown_period_falls_back_to_30_days(client, staff_user, customer):
    make_order(customer, "100.00", days_ago=60)
    client.force_login(staff_user)

    page = client.get(
        reverse("dashboard:index"), {"period": "fortnight"}
    ).content.decode()

    assert "$0.00" in page


def test_the_dashboard_has_a_designed_empty_state(client, staff_user):
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "No sales yet" in page


def test_a_quiet_period_is_not_the_empty_store(client, staff_user, customer):
    make_order(customer, "100.00", days_ago=60)
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "No sales yet" not in page
    assert "No sales in this period" in page


def test_the_reviews_card_follows_the_period(client, staff_user, customer, product):
    make_order(customer, "100.00")
    make_review("ada", product, 6, days_ago=5)
    make_review("bo", product, 10, days_ago=60)
    client.force_login(staff_user)

    recent = client.get(reverse("dashboard:index"))
    ever = client.get(reverse("dashboard:index"), {"period": "all"})

    assert (recent.context["reviews"].count, recent.context["reviews"].average) == (
        1,
        3.0,
    )
    assert (ever.context["reviews"].count, ever.context["reviews"].average) == (2, 4.0)
    page = ever.content.decode()
    assert "Reviews in this period" in page
    assert "Average customer rating in this period" in page
    assert "out of 5, excluding staff and removed reviews" in page


def test_a_period_without_reviews_shows_zero_and_a_dash(client, staff_user, customer):
    make_order(customer, "100.00")
    client.force_login(staff_user)

    page = client.get(reverse("dashboard:index")).content.decode()

    assert '<div class="stat-value">0</div>' in page
    assert '<div class="stat-value opacity-50">—</div>' in page
    assert "no customer reviews in this period" in page
