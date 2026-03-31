from __future__ import annotations
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


from .book_template import ProrataPolicy
from .book import Book, Move


__all__ = ("FixedAsset", "AmortizationSchedule", "AmortizationEntry")


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


class FixedAsset(models.Model):
    """A fixed asset that is ammortized."""

    class Type(models.IntegerChoices):
        INTANGIBLE = 0x00, _("Intangible Asset")
        TANGIBLE = 0x01, _("Tangible Asset")
        FINANCIAL = 0x02, _("Financial Asset")

    book = models.ForeignKey(Book, models.PROTECT, related_name="fixed_assets")
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
    value = models.DecimalField(_("Initial Value"), max_digits=12, decimal_places=2)
    # real_value = models.DecimalField(
    #    _("Residual Value"), max_digits=12, decimal_places=2,
    #    help_text=_("Value after amortization have been applied.")
    # )

    class Meta:
        verbose_name = _("Fixed Asset")
        verbose_name_plural = _("Fixed Assets")

    def get_applied_amortizations(self) -> Decimal:
        """Total applied amortizations."""
        query = AmortizationEntry.objects.filter(schedule__asset=self)
        return sum(query.values_list("amount", flat=True))

    def get_amortized_value(self) -> Decimal:
        return self.value - self.get_applied_amortizations()


#    def get_amortized_value(self, period_end=None) -> Decimal|None:
#        """ Return amortized value from annotation or by computing it. """
#        if not period_end and hasattr(self, "amortized_value"):
#            return self.amortized_value
#        if amortization := getattr(self, "amortization", None):
#            entries = amortization.entries.all()
#            if period_end:
#                entries = entries.filter(period_end__lte=period_end)
#            return sum(v for v in entries.values_list("amount", flat=True))


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
    residual_value = models.DecimalField(
        _("Residual Value"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0."),
        help_text=_("Expected asset value after amortization has been fully applied."),
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

    class Meta:
        verbose_name = _("Amortization Entry")
        verbose_name_plural = _("Amortization Entries")
