from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


from fin.models import ProrataPolicy, AmortizationSchedule, AmortizationEntry, Move, Line


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
            period_start = schedule.start_date
            applied_amount = Decimal("0.")
            is_first = True
        else:
            # Clear entries after period_end
            if period_end < schedule.start_date:
                raise ValueError("Period end is lower that start date.")

            schedule.clear_entries(period_end + timedelta(days=1))
            last = schedule.entries.order_by("date").last()
            is_first = last is None
            period_start = last and (last.date + timedelta(days=1)) or schedule.start_date
            applied_amount = schedule.get_applied_amount()

        # Remaining value
        remaining_value = schedule.asset.initial_value - applied_amount
        if remaining_value < schedule.asset.residual_value:
            raise ValueError("The assets amortized value is lower than amortization residual value.")
        if remaining_value == schedule.asset.residual_value:
            return []

        entries = []

        periods_count = schedule.count_periods()
        print(">>>", schedule, periods_count)
        for start, end in schedule.iter_periods(period_start, period_end):
            amount = self._apply_method(schedule, remaining_value, start, end, periods_count)
            amount = min(amount, remaining_value - schedule.asset.residual_value)
            if is_first:
                amount = amount * self._prorata_factor(schedule, start, end)

            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            entry = AmortizationEntry(schedule=schedule, date=end, amount=amount)
            entries.append(entry)
            is_first = False
            remaining_value -= amount

            # Protect against rounding issue and future changes
            if remaining_value <= schedule.asset.residual_value:
                break
        return entries

    def build_moves(
        self, entries: Iterable[AmortizationEntry], date=None, description=""
    ) -> tuple[list[Move], list[Line]]:
        """Create moves and lines applying the provided amortization entries.

        Skip entries that already are have been applied.

        :param entries: entries to create moves from
        :param description: description to set on the move (formatted using arguments: ``entry``, ``asset``)
        :return a two-tuple of moves and lines
        """
        moves, lines = [], []

        if not description:
            description = "Amortization - {asset.description}"

        for entry in entries:
            if entry.move_id:
                continue

            if vals := entry.create_move(description, date):
                entry.move = vals[0]
                moves.append(vals[0])
                lines.extend(vals[1])

        return moves, lines

    def _apply_method(
        self,
        schedule: AmortizationSchedule,
        remaining_value: Decimal,
        period_start: date,
        period_end: date,
        periods_count: int,
    ) -> Decimal:
        """Apply method and return the amortization value."""

        # prorata temporis
        match schedule.method:
            case schedule.Method.LINEAR:
                return (schedule.asset.initial_value - schedule.asset.residual_value) / Decimal(periods_count)

            case schedule.Method.DEGRESSIVE:
                if not schedule.rate:
                    raise ValueError("Rate is not set.")

                degressive_amount = remaining_value * schedule.rate * (Decimal(schedule.frequency) / 12)
                if self._is_first_period(schedule, period_start):
                    # first period: we're sure it's degressive
                    return degressive_amount

                # Otherwise, compare whats left to linear.
                remaining_months = (
                    (schedule.end_date.year - period_start.year) * 12 + schedule.end_date.month - period_start.month + 1
                )
                linear_amount = (remaining_value - schedule.asset.residual_value) / Decimal(
                    max(remaining_months // schedule.frequency, 1)
                )
                return max(degressive_amount, linear_amount)

            case _:
                raise ValueError(f"Unsupported method {schedule.get_method_display()}")

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
            case ProrataPolicy.MONTHLY:
                months_used = (end.year - start.year) * 12 + (end.month - start.month) + 1
                return Decimal(months_used) / Decimal(schedule.frequency * (12 // schedule.frequency))
            case _:
                label = ProrataPolicy(policy).label
                raise ValueError(f"Invalid prorata policy: {label}")

    @staticmethod
    def _is_leap_year(year: int) -> bool:
        """Return True if the given year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    @staticmethod
    def _is_first_period(schedule: AmortizationSchedule, period_start: date):
        return period_start.year == schedule.start_date.year and period_start.month == schedule.start_date.month
