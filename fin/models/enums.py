from __future__ import annotations
from datetime import date

from django.db import models
from django.utils.translation import gettext_lazy as _


__all__ = (
    "ProrataPolicy",
    "Period",
)


class ProrataPolicy(models.IntegerChoices):
    """Policy for prorata."""

    NONE = 0x00, _("None")
    DAILY = 0x01, _("Daily")
    MONTHLY = 0x02, _("Monthly")


class Period(models.IntegerChoices):
    MONTH_1 = 1, _("1 month")
    MONTH_3 = 3, _("A quarter")
    MONTH_6 = 6, _("6 months")
    MONTH_12 = 12, _("A year")

    @classmethod
    def get_start(cls, target_date: date, anchor_month: int, period_months: int) -> date:
        """
        Resolve the start date of the Exercise period that contains the given date.

        The logic performs month-based bucketing relative to a fiscal anchor.

        :param target_date: Date to resolve.
        :param anchor_month: Fiscal year starting month (1–12).
        :param period_months: Size of the fiscal period in months.
        :returns: Start date of the corresponding Exercise period.
        """

        # Convert to absolute month index
        absolute_month = target_date.year * 12 + (target_date.month - 1)
        anchor = target_date.year * 12 + (anchor_month - 1)

        diff = absolute_month - anchor
        bucket = diff // period_months
        start_index = anchor + bucket * period_months

        start_year = start_index // 12
        start_month = (start_index % 12) + 1
        return date(start_year, start_month, 1)
