from __future__ import annotations

from django.db import models
from django.db.models import Value, Case, When
from django.utils.translation import gettext_lazy as _

from .utils import Named, Described

__all__ = ("BookTemplate", "Account", "Journal")


class BookTemplate(Described):
    """
    This class provide full template for a ledger book, including accounts
    and journals.
    """

    class Meta:
        verbose_name = _("Book template")
        verbose_name_plural = _("Book templates")

    def __str__(self):
        return self.name


class Account(models.Model):
    """A ledger account."""

    class Type(models.IntegerChoices):
        """Account type."""

        OTHER = 0x00, _("Other (General ledger account)")
        VIEW = 0x01, _("View (Non-postable group)")
        DEPRECIATION = 0x02, _("Depreciation")
        TAX = 0x03, _("Tax (VAT, Corporate, etc.)")
        OFF_BALANCE = 0x04, _("Off Balance Sheet")
        ASSET = 0x10, _("Assets")
        EXPENSE = 0x11, _("Expense")
        RECEIVABLE = 0x12, _("Receivable (Customer)")
        LIQUIDITY = 0x13, _("Liquidity (Cash/Bank)")
        STOCK_INVENTORY = 0x14, _("Stock Inventory")
        LIABILITY = 0x20, _("Liability")
        EQUITY = 0x21, _("Equity")
        REVENUE = 0x22, _("Revenue")
        PAYABLE = 0x23, _("Payable (Vendor)")

        @classmethod
        def debit_types(cls):
            return [v for v in cls.values if v & 0x10]

        @classmethod
        def credit_types(cls):
            return [v for v in cls.values if v & 0x20]

        @classmethod
        def from_str(cls, value: str):
            """Return instance of self from provided type string."""
            if value == "cash":
                return cls.LIQUIDITY
            return getattr(cls, value.upper(), cls.OTHER)

    template = models.ForeignKey(BookTemplate, models.PROTECT, related_name="accounts")
    name = models.CharField(_("Name"), max_length=256)
    code = models.CharField(_("Code"), max_length=10, null=True, blank=True)
    short = models.CharField(_("Abbreviation"), max_length=10, blank=True, null=True)
    type = models.PositiveIntegerField(_("Type"), choices=Type.choices, default=Type.OTHER)
    is_debit = models.GeneratedField(
        expression=Case(
            When(type__in=Type.debit_types(), then=Value(True)),
            When(type__in=Type.credit_types(), then=Value(False)),
            default=Value(None),
        ),
        verbose_name=_("Is debit"),
        output_field=models.BooleanField(null=True),
        db_persist=True,
    )

    class Meta:
        verbose_name = _("Account")
        verbose_name_plural = _("Accounts")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(self.type, str):
            self.type = self.Type.from_str(self.type)

    @property
    def long_code(self):
        """Code padded to 6 numbers."""
        return self.code.ljust(6, "0")

    def __str__(self):
        postfix = f" [{self.short}]" if self.short else ""
        postfix += " - Debit" if self.is_debit else " - Credit" if self.is_debit is False else " - ?"
        return f"{self.code} - {self.name}{postfix}"


class Journal(Named):
    template = models.ForeignKey(BookTemplate, models.CASCADE, related_name="journals")
    code = models.CharField(_("Code"), max_length=10, help_text=_('For example "FIN" for "Finance".'))

    class Meta:
        verbose_name = _("Journal")
        verbose_name_plural = _("Journals")

    def __str__(self):
        return f"{self.code} - {self.name}"
