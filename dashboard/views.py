"""The analytics dashboard — a thin view over ``dashboard.queries``."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.views.generic import TemplateView

from accounts.mixins import StaffRequiredMixin

from . import queries

# period key -> (label, days back, revenue-over-time bucket). Each period
# gets the bucket that yields a readable number of bars.
PERIODS = {
    "30": ("30 days", 30, "day"),
    "90": ("90 days", 90, "week"),
    "all": ("All time", None, "month"),
}

DEFAULT_PERIOD = "30"


class DashboardView(StaffRequiredMixin, TemplateView):
    """Revenue, order volume, and top products for the selected period."""

    template_name = "dashboard/dashboard.html"
    extra_context = {"section": "dashboard"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", DEFAULT_PERIOD)
        if period not in PERIODS:
            period = DEFAULT_PERIOD
        label, days, bucket = PERIODS[period]
        since = timezone.now() - timedelta(days=days) if days else None
        series = queries.revenue_over_time(since, bucket=bucket)
        context.update(
            {
                "periods": [(key, entry[0]) for key, entry in PERIODS.items()],
                "active_period": period,
                "period_label": label,
                "bucket": bucket,
                "revenue": queries.total_revenue(since),
                "discounts_given": queries.discounts_given(since),
                "order_count": queries.order_count(since),
                "average_order_value": queries.average_order_value(since),
                "series": series,
                "max_revenue": max(
                    (point["revenue"] for point in series), default=Decimal("0")
                ),
                "top_products": queries.top_products(since),
                # The all-time check: a quiet period is not an empty store.
                "store_has_sales": queries.order_count() > 0,
            }
        )
        return context
