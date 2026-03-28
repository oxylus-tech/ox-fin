from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dateutils import relativedelta
from django.db import models
from django.utils.translation import gettext_lazy as _


from .utils import Described
from .book import ProrataPolicy, Book, Move


__all__ = ("FixedAsset", "Amortization", "AmortizationEntry")


# class FixedAssetQuerySet(models.QuerySet):
#     def with_amortized_value(self, period_end=None):
#         """ Annotate assets with the remaining value after amortizations applied.
#         """
#         if end_date:
#             filter = Q(amortization__entries__period_end__lte=period_end)
#         else:
#             filter = None
#         # FIXME: value-amortized_value
#         return self.annotate(amortized_value=Sum("amortization__entries__amount", filter=filter))


class FixedAsset(Described):
    """A fixed asset that is ammortized."""

    class Type(models.IntegerChoices):
        INTANGIBLE = 0x00, _("Intangible Asset")
        TANGIBLE = 0x01, _("Tangible Asset")
        FINANCIAL = 0x01, _("Financial Asset")

    book = models.ForeignKey(Book, models.PROTECT, related_name="fixed_assets")
    move = models.ForeignKey(
        Move,
        models.CASCADE,
        verbose_name=_("Journal Entry"),
        help_text=_("The journal entry of the asset's acquisition."),
    )
    type = models.PositiveSmallIntegerField(_("Type"), choices=Type.choices)
    date = models.DateField()
    initial_value = models.DecimalField(_("Initial Value"), max_digits=12, decimal_places=2)
    # real_value = models.DecimalField(
    #    _("Residual Value"), max_digits=12, decimal_places=2,
    #    help_text=_("Value after amortization have been applied.")
    # )

    class Meta:
        verbose_name = _("Fixed Asset")
        verbose_name_plural = _("Fixed Assets")


#    def get_amortized_value(self, period_end=None) -> Decimal|None:
#        """ Return amortized value from annotation or by computing it. """
#        if not period_end and hasattr(self, "amortized_value"):
#            return self.amortized_value
#        if amortization := getattr(self, "amortization", None):
#            entries = amortization.entries.all()
#            if period_end:
#                entries = entries.filter(period_end__lte=period_end)
#            return sum(v for v in entries.values_list("amount", flat=True))


class Amortization(models.Model):
    """Describe an asset's ammortization."""

    class Method(models.IntegerChoices):
        LINEAR = 0x00, _("Linear")
        DEGRESSIVE = 0x01, _("Degressive")

    class Frequency(models.IntegerChoices):
        MONTHLY = 1, _("Monthly")
        QUARTERLY = 3, _("Quarterly")
        ANNUAL = 12, _("Annual")

    asset = models.OneToOneField(FixedAsset, models.CASCADE, related_name="amortization")
    start_date = models.DateField(
        _("Start Date"), help_text=_("Start of the amortization (usually acquisition date or first use).")
    )
    end_date = models.DateField(_("End Date"))
    duration_months = models.PositiveIntegerField(_("Duration (months)"))
    method = models.PositiveSmallIntegerField(_("Method"), choices=Method.choices, default=Method.LINEAR)
    frequency = models.PositiveSmallIntegerField(_("Frequency"), choices=Frequency.choices, default=Frequency.ANNUAL)
    rate = models.DecimalField(_("Rate"), max_digits=5, decimal_places=4, null=True, blank=True)
    prorata = models.BooleanField(_("Prorata"), default=True, help_text=_("Whether first year is prorated"))
    residual_value = models.DecimalField(
        _("Residual Value"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0."),
        help_text=_("Expected asset value after amortization has been fully applied."),
    )
    prorata = models.PositiveSmallIntegerField(
        _("Prorata Policy"),
        choices=ProrataPolicy.choices,
        null=True,
        blank=True,
        help_text=_("Override ledger book's prorata policy of amortization."),
    )

    class Meta:
        verbose_name = _("Amortization")
        verbose_name_plural = _("Amortizations")

    def normalize(self):
        """Ensure residual value is correct among other things."""
        pass

    def get_applied_amount(self) -> Decimal:
        """Total applied values."""
        return sum(self.entries.all().values_list("amount", flat=True))

    def generate_entries(self, period_end: date, clear: bool = False) -> list[AmortizationEntry]:
        """Generate amortization entries for the provided period.

         Keep existing entries before last entry when ``not clear``. Generate
         everything from :py:attr:`start_date` to ``period_end`` otherwise.

        :param period_end: end of the period.
        :param clear: delete all previous amortization entries
        """
        if clear:
            # Clear all entries
            self.clear_entries()
            current_date = self.start_date
            applied_amount = Decimal("0.")
            is_first = True
        else:
            # Clear entries after period_end
            if period_end < self.start_date:
                raise ValueError("Period end is lower that start date.")

            self.clear_entries(period_end + timedelta(days=1))
            last = self.entries.order_by("date").last()
            is_first = last is None
            current_date = last and (last.date + timedelta(days=1)) or self.start_date
            applied_amount = self.get_applied_amount()

        # Remaining value
        remaining_value = self.asset.initial_value - applied_amount
        self.validate_remaining(remaining_value)
        if remaining_value == self.residual_value:
            return []

        entries = []
        period_end = min(period_end, self.end_date)
        while current_date <= period_end and remaining_value > self.residual_value:
            next_date = self._period_end(current_date)
            amount = self._apply_method(remaining_value, current_date, next_date)
            amount = min(amount, remaining_value - self.residual_value)
            if is_first:
                amount = amount * self._prorata_factor(current_date, next_date)
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            entry = AmortizationEntry(amortization=self, date=next_date, amount=amount)
            entries.append(entry)
            is_first = False
            remaining_value -= amount
            current_date = next_date + timedelta(days=1)

            # Protect against rounding issue and future changes
            if remaining_value <= self.residual_value:
                break
        return entries

    def clear_entries(self, from_date: Decimal | None = None):
        """Clear entries from the provided date.

        :yield RuntimeError: some entries are linked to a move.
        """
        if from_date:
            query = self.entries.filter(date__gte=from_date)
        else:
            query = self.entries.all()

        moves = Move.objects.filter(amortization_entries__in=query)
        if moves.exists():
            raise RuntimeError("Some entries are linked to journal entries. Delete them before clearing them.")
        query.delete()

    def validate_remaining(self, remaining_value: Decimal):
        """
        Validate remaining value.
        :yield ValueError when value is invalid.
        """
        if remaining_value < self.residual_value:
            raise ValueError("The assets amortized value is lower than amortization residual value.")

    def _period_end(self, date: date) -> date:
        if self.frequency == 12:
            # end of year
            return date.replace(month=12, day=31)

        if self.frequency == 1:
            return (date + relativedelta(months=1, day=1)) - relativedelta(days=1)

        if self.frequency == 3:
            quarter = (date.month - 1) // 3 + 1
            quarter_end_month = quarter * 3
            return date.replace(month=quarter_end_month, day=1) + relativedelta(months=1)

        # Support custom frequencies (in months)
        return (date + relativedelta(months=self.frequency, day=1)) - relativedelta(days=1)

    def _prorata_factor(self, start: date, end: date) -> Decimal:
        """Return coefficient to use to apply prorata policy."""
        if self.prorata is None:
            policy = self.asset.book.amortization_prorata
        else:
            policy = self.prorata

        match policy:
            case ProrataPolicy.NONE:
                return Decimal("1.")
            case ProrataPolicy.DAILY:
                days_used = (end - start).days + 1
                days_year = 366 if self._is_leap_year(start.year) else 365
                return Decimal(days_used) / Decimal(days_year)
            case ProrataPolicy.FULL_MONTH:
                months_used = (end.year - start.year) * 12 + (end.month - start.month) + 1
                return Decimal(months_used) / Decimal(12)
            case _:
                label = ProrataPolicy(policy).label
                raise ValueError(f"Invalid prorata policy: {label}")

    def _is_leap_year(self, year: int) -> bool:
        """Return True if the given year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    def _apply_method(self, remaining_value: Decimal, period_start: date, period_end: date) -> Decimal:
        """Apply method and return the amortization value."""
        match self.method:
            case self.Method.LINEAR:
                total_months = (
                    (self.end_date.year - period_start.year) * 12 + self.end_date.month - period_start.month + 1
                )
                total_periods = max(total_months // self.frequency, 1)
                return (remaining_value - self.residual_value) / Decimal(total_periods)

            case self.Method.DEGRESSIVE:
                if not self.rate:
                    raise ValueError("Rate is not set.")
                return remaining_value * self.rate * (Decimal(self.frequency) / 12)

            case _:
                raise NotImplementedError(f"Unsupported method {self.get_method_display()}")


class AmortizationEntry(models.Model):
    # TODO:
    # - on post save: check validity of the value

    amortization = models.ForeignKey(
        Amortization, models.CASCADE, related_name="entries", verbose_name=_("Amortization")
    )
    date = models.DateField()
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)
    move = models.ForeignKey(
        Move,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="amortization_entries",
        verbose_name=_("Journal Entry"),
        help_text=_("The journal entry applying the amortization."),
    )

    class Meta:
        verbose_name = _("Amortization Entry")
        verbose_name_plural = _("Amortization Entries")
