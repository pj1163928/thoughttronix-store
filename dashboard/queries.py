"""Dashboard aggregations — the second of the codebase's two deep modules.

The interface is the product: six functions that answer the questions
leadership actually asks. Every one takes an optional ``since`` cutoff
(``None`` means all time) and excludes cancelled orders — cancelled
revenue is money the store never keeps.

Two of these count money differently, deliberately. ``total_revenue``
sums what was charged, after discounts. ``top_products`` sums line items
at their purchase prices, before them. The gap between the two is
``discounts_given``, so the three read together the way a P&L does:
gross sales, less discounts, equals net revenue.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import DateField, DecimalField, F, QuerySet, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone

from orders.models import Order, OrderItem

ZERO = Decimal("0.00")

CENT = Decimal("0.01")


def _sold(since: datetime | None) -> QuerySet[Order]:
    """Orders that count as sales: every status except cancelled."""
    orders = Order.objects.exclude(status=Order.Status.CANCELLED)
    if since is not None:
        orders = orders.filter(created_at__gte=since)
    return orders


def total_revenue(since: datetime | None = None) -> Decimal:
    """Sum of order totals placed at or after ``since``."""
    return _sold(since).aggregate(revenue=Sum("total"))["revenue"] or ZERO


def order_count(since: datetime | None = None) -> int:
    """Number of orders placed at or after ``since``."""
    return _sold(since).count()


def discounts_given(since: datetime | None = None) -> Decimal:
    """Total taken off by discount codes on orders placed at or after ``since``.

    Read from each order's frozen ``discount_amount``, not recomputed from
    the codes — so retiring or editing a code never moves a past figure.
    """
    return _sold(since).aggregate(given=Sum("discount_amount"))["given"] or ZERO


def average_order_value(since: datetime | None = None) -> Decimal:
    """Revenue divided by order count, rounded to cents; zero if no orders."""
    count = order_count(since)
    if count == 0:
        return ZERO
    return (total_revenue(since) / count).quantize(CENT)


def revenue_over_time(
    since: datetime | None = None, *, bucket: str = "month"
) -> list[dict]:
    """Revenue per time bucket, oldest first, with empty buckets at zero.

    ``bucket`` is ``"day"``, ``"week"`` (Monday-start), or ``"month"``.
    Each entry is ``{"bucket": date, "revenue": Decimal}``. The series
    runs from ``since`` (or the first sale, for all time) through today,
    so quiet stretches show as zero — a time axis with no gaps. A period
    with no sales at all returns an empty list.
    """
    trunc = {"day": TruncDate, "week": TruncWeek, "month": TruncMonth}[bucket]
    rows = (
        _sold(since)
        .annotate(period=trunc("created_at", output_field=DateField()))
        .values("period")
        .annotate(revenue=Sum("total"))
        .order_by("period")
    )
    revenue_by_bucket = {row["period"]: row["revenue"] for row in rows}
    if not revenue_by_bucket:
        return []

    # Trunc* buckets in the active timezone; use the same clock here.
    start = _floor(
        timezone.localdate(since) if since else min(revenue_by_bucket), bucket
    )
    end = _floor(timezone.localdate(), bucket)
    series = []
    while start <= end:
        series.append({"bucket": start, "revenue": revenue_by_bucket.get(start, ZERO)})
        start = _advance(start, bucket)
    return series


def top_products(since: datetime | None = None, *, limit: int = 5) -> list[dict]:
    """The best-selling products by gross sales, best first.

    Grouped by the order lines' denormalized ``product_name``, so the
    ranking reflects what was actually charged per line — later catalog
    edits and deletions don't rewrite history. Order-level discounts are
    not deducted here; see ``discounts_given``. Each entry is
    ``{"product_name", "revenue", "units"}``.
    """
    items = OrderItem.objects.exclude(order__status=Order.Status.CANCELLED)
    if since is not None:
        items = items.filter(order__created_at__gte=since)
    return list(
        items.values("product_name")
        .annotate(
            revenue=Sum(
                F("unit_price") * F("quantity"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            units=Sum("quantity"),
        )
        .order_by("-revenue")[:limit]
    )


def _floor(day: date, bucket: str) -> date:
    """The first day of the bucket containing ``day``."""
    if bucket == "day":
        return day
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _advance(day: date, bucket: str) -> date:
    """The first day of the bucket after the one starting at ``day``."""
    if bucket == "day":
        return day + timedelta(days=1)
    if bucket == "week":
        return day + timedelta(days=7)
    return (day + timedelta(days=31)).replace(day=1)
