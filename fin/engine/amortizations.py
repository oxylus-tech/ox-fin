from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta


from fin.models import ProrataPolicy, AmortizationSchedule, AmortizationEntry


__all__ = ("AmortizationEntryBuilder",)


class AmortizationEntryBuilder:
    """Generate amortization entries for the provided schedule."""

    def build(self, schedule: AmortizationSchedule, period_end: date, clear: bool = False) -> list[AmortizationEntry]:
        """Generate amortization entries for the provided period.

         Keep existing entries before last entry when ``not clear``. Generate
         everything from :py:attr:`start_date` to ``period_end`` otherwise.

        :param amortization: the amortization to create entries from
        :param period_end: end of the period.
        :param clear: delete all previous amortization entries
        """
        if clear:
            # Clear all entries
            schedule.clear_entries()
            current_date = schedule.start_date
            applied_amount = Decimal("0.")
            is_first = True
        else:
            # Clear entries after period_end
            if period_end < schedule.start_date:
                raise ValueError("Period end is lower that start date.")

            schedule.clear_entries(period_end + timedelta(days=1))
            last = schedule.entries.order_by("date").last()
            is_first = last is None
            current_date = last and (last.date + timedelta(days=1)) or schedule.start_date
            applied_amount = schedule.get_applied_amount()

        # Remaining value
        remaining_value = schedule.asset.value - applied_amount
        if remaining_value < schedule.residual_value:
            raise ValueError("The assets amortized value is lower than amortization residual value.")
        if remaining_value == schedule.residual_value:
            return []

        entries = []
        period_end = min(period_end, schedule.end_date)
        while current_date <= period_end and remaining_value > schedule.residual_value:
            next_date = self._period_end(schedule.frequency, current_date)
            amount = self._apply_method(schedule, remaining_value, current_date, next_date)
            amount = min(amount, remaining_value - schedule.residual_value)
            if is_first:
                amount = amount * self._prorata_factor(schedule, current_date, next_date)
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            entry = AmortizationEntry(schedule=schedule, date=next_date, amount=amount)
            entries.append(entry)
            is_first = False
            remaining_value -= amount
            current_date = next_date + timedelta(days=1)

            # Protect against rounding issue and future changes
            if remaining_value <= schedule.residual_value:
                break
        return entries

    def _period_end(self, frequency: int, date: date) -> date:
        match frequency:
            case 12:
                return date.replace(month=12, day=31)
            case 1:
                return (date + relativedelta(months=1, day=1)) - relativedelta(days=1)
            case 3:
                quarter = (date.month - 1) // 3 + 1
                quarter_end_month = quarter * 3
                return date.replace(month=quarter_end_month, day=1) + relativedelta(months=1) - relativedelta(days=1)
            case _:
                # Support custom frequencies (in months)
                return (date + relativedelta(months=frequency, day=1)) - relativedelta(days=1)

    def _prorata_factor(self, schedule: AmortizationSchedule, start: date, end: date) -> Decimal:
        """Return coefficient to use to apply prorata policy."""
        if schedule.prorata is None:
            policy = schedule.asset.book.amortization_prorata
        else:
            policy = schedule.prorata

        match policy:
            case ProrataPolicy.NONE | None:
                return Decimal("1.")
            case ProrataPolicy.DAILY:
                days_used = (end - start).days + 1
                days_year = 366 if self._is_leap_year(start.year) else 365
                return Decimal(days_used) / Decimal(days_year)
            case ProrataPolicy.FULL_MONTH:
                months_used = (end.year - start.year) * 12 + (end.month - start.month) + 1
                return Decimal(months_used) / Decimal(schedule.frequency * (12 // schedule.frequency))
            case _:
                label = ProrataPolicy(policy).label
                raise ValueError(f"Invalid prorata policy: {label}")

    def _is_leap_year(self, year: int) -> bool:
        """Return True if the given year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    def _apply_method(
        self, schedule: AmortizationSchedule, remaining_value: Decimal, period_start: date, period_end: date
    ) -> Decimal:
        """Apply method and return the amortization value."""
        match schedule.method:
            case schedule.Method.LINEAR:
                total_months = (
                    (schedule.end_date.year - period_start.year) * 12 + schedule.end_date.month - period_start.month + 1
                )
                total_periods = max(total_months // schedule.frequency, 1)
                return (remaining_value - schedule.residual_value) / Decimal(total_periods)

            case schedule.Method.DEGRESSIVE:
                if not schedule.rate:
                    raise ValueError("Rate is not set.")
                return remaining_value * schedule.rate * (Decimal(schedule.frequency) / 12)

            case _:
                raise ValueError(f"Unsupported method {schedule.get_method_display()}")
