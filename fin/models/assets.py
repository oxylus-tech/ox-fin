from __future__ import annotations
from decimal import Decimal
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.db import models
from django.utils.translation import gettext_lazy as _


from .book_template import ProrataPolicy, Account
from .book import Book, Move, Line


__all__ = ("FixedAsset", "AmortizationSchedule", "AmortizationEntry")


def iter_periods(frequency, start_date, end_date):
    """Iterate over start-end periods."""
    start = start_date
    while start <= end_date:
        end = period_end(frequency, start)
        if end > end_date:
            break

        yield start, end
        start = end + timedelta(days=1)


def count_periods(frequency, start_date, end_date):
    """Count periods between start and end."""
    return sum(1 for _ in iter_periods(frequency, start_date, end_date))


def period_end(frequency: int, date: date) -> date:
    """Return the end of a period based on provided frequency and date."""
    match frequency:
        case 12:
            return date.replace(month=12, day=31)
        case 1:
            return (date + relativedelta(months=1, day=1)) - relativedelta(days=1)
        case 3:
            quarter = (date.month - 1) // 3 + 1
            end_month = quarter * 3
            return date.replace(month=end_month, day=1) + relativedelta(months=1, days=-1)
        case _:
            # Support custom frequencies (in months)
            return (date + relativedelta(months=frequency, day=1)) - relativedelta(days=1)


class FixedAsset(models.Model):
    """A fixed asset that is ammortized."""

    class Type(models.IntegerChoices):
        INTANGIBLE = 0x00, _("Intangible Asset")
        TANGIBLE = 0x01, _("Tangible Asset")
        FINANCIAL = 0x02, _("Financial Asset")

    book = models.ForeignKey(Book, models.PROTECT, related_name="fixed_assets")
    account = models.ForeignKey(
        Account,
        models.CASCADE,
        verbose_name=_("Account"),
    )
    move = models.ForeignKey(
        Move,
        models.CASCADE,
        verbose_name=_("Journal Entry"),
        help_text=_("The journal entry of the asset's acquisition."),
    )
    description = models.CharField(_("Description"), max_length=128)
    reference = models.CharField(_("Reference"), max_length=64, null=True, blank=True)
    type = models.PositiveSmallIntegerField(_("Type"), choices=Type.choices)
    date = models.DateField()
    initial_value = models.DecimalField(_("Initial Value"), max_digits=12, decimal_places=2)
    # real_value = models.DecimalField(
    #    _("Residual Value"), max_digits=12, decimal_places=2,
    #    help_text=_("Value after amortization have been applied.")
    # )
    residual_value = models.DecimalField(
        _("Residual Value"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0."),
        help_text=_("Expected asset value at the end of its usefull life."),
    )

    class Meta:
        verbose_name = _("Fixed Asset")
        verbose_name_plural = _("Fixed Assets")

    def get_applied_amortizations(self) -> Decimal:
        """Total applied amortizations."""
        query = AmortizationEntry.objects.filter(schedule__asset=self)
        return sum(query.values_list("amount", flat=True))

    def get_amortized_value(self) -> Decimal:
        return self.initial_value - self.get_applied_amortizations()


#    def get_amortized_value(self, period_end=None) -> Decimal|None:
#        """ Return amortized value from annotation or by computing it. """
#        if not period_end and hasattr(self, "amortized_value"):
#            return self.amortized_value
#        if amortization := getattr(self, "amortization", None):
#            entries = amortization.entries.all()
#            if period_end:
#                entries = entries.filter(period_end__lte=period_end)
#            return sum(v for v in entries.values_list("amount", flat=True))


class AmortizationScheduleQuerySet(models.QuerySet):
    def book(self, book):
        return self.filter(asset__book=book)


class AmortizationSchedule(models.Model):
    """Describe how an asset is ammortized."""

    class Method(models.IntegerChoices):
        LINEAR = 0x00, _("Linear")
        DEGRESSIVE = 0x01, _("Degressive")

    class Frequency(models.IntegerChoices):
        MONTHLY = 1, _("Monthly")
        QUARTERLY = 3, _("Quarterly")
        ANNUAL = 12, _("Annual")

    # TODO: multiple amortization schedule per assets (revisions)
    asset = models.ForeignKey(FixedAsset, models.CASCADE, related_name="amortizations")
    start_date = models.DateField(
        _("Start Date"), help_text=_("Start of the amortization (usually acquisition date or first use).")
    )
    end_date = models.DateField(_("End Date"))
    method = models.PositiveSmallIntegerField(_("Method"), choices=Method.choices, default=Method.LINEAR)
    frequency = models.PositiveSmallIntegerField(_("Frequency"), choices=Frequency.choices, default=Frequency.ANNUAL)
    rate = models.DecimalField(_("Rate"), max_digits=5, decimal_places=4, null=True, blank=True)
    prorata = models.PositiveSmallIntegerField(
        _("Prorata Policy"),
        choices=ProrataPolicy.choices,
        null=True,
        blank=True,
        help_text=_("Override ledger book's prorata policy of amortization."),
    )

    objects = AmortizationScheduleQuerySet.as_manager()

    class Meta:
        verbose_name = _("Amortization")
        verbose_name_plural = _("Amortizations")

    def normalize(self):
        """Ensure residual value is correct among other things."""
        pass

    def get_applied_amount(self) -> Decimal:
        """Total applied values."""
        return sum(self.entries.all().values_list("amount", flat=True))

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
            raise RuntimeError(
                "Some entries are linked to journal entries. Delete them or set move to null before clearing them."
            )
        query.delete()

    def count_periods(self, start_date=None, end_date=None):
        start_date = start_date or self.start_date
        end_date = end_date or self.end_date
        return count_periods(self.frequency, start_date, end_date)

    def iter_periods(self, start_date=None, end_date=None):
        start_date = min(start_date or self.start_date, self.end_date)
        end_date = min(end_date or self.end_date, self.end_date)
        return iter_periods(self.frequency, start_date, end_date)

    def period_end(self, end_date=None):
        end_date = end_date or self.end_date
        return period_end(self.frequency, end_date)

    def __str__(self):
        return (
            "Amortization("
            f"frequency={self.get_frequency_display()}, "
            f"method={self.get_method_display()}, "
            f"start_date={self.start_date}, "
            f"end_date={self.end_date}"
            ")"
        )


class AmortizationEntryQuerySet(models.QuerySet):
    def asset(self, asset):
        return self.filter(schedule__asset=asset)

    def book(self, book):
        return self.filter(schedule__asset__book=book)


class AmortizationEntry(models.Model):
    # TODO:
    # - on post save: check validity of the value

    schedule = models.ForeignKey(
        AmortizationSchedule, models.CASCADE, related_name="entries", verbose_name=_("Amortization")
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

    objects = AmortizationEntryQuerySet.as_manager()

    class Meta:
        verbose_name = _("Amortization Entry")
        verbose_name_plural = _("Amortization Entries")

    @property
    def asset(self) -> FixedAsset:
        """Return asset related to this entry."""
        return self.schedule.asset

    @property
    def book(self) -> Book:
        """Return book related to this entry."""
        return self.asset.book

    def create_move(self, description, date=None) -> tuple[Move, tuple[Line, Line]] | None:
        """Create the move and line for this entry.

        Description is a string that will be formatted using ``entry`` and ``asset``.

        When no account or journal exists on the book template, returns None.
        """
        template = self.book.template
        debit_account = self.asset.account.dep_exp_account
        credit_account = self.asset.account.acc_dep_account
        journal = template.amortization_journal
        if not debit_account or not credit_account or not journal:
            return None

        date = date or self.date
        move = Move(
            book=self.book,
            journal=journal,
            date=date,
            description=description.format(entry=self, asset=self.asset, date=self.date),
        )
        lines = (
            Line(move=move, account=debit_account, is_debit=True, amount=self.amount),
            Line(move=move, account=credit_account, is_debit=False, amount=self.amount),
        )
        return move, lines
