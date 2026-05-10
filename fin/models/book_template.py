from __future__ import annotations
from datetime import date
from decimal import Decimal

from django.db import models
from django.db.models import Value, Case, When
from django.utils.translation import gettext_lazy as _

from .utils import Named, LongNamed, Described, Titled


__all__ = ("ProrataPolicy", "BookTemplate", "Account", "Journal")


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


class BookTemplate(Titled, Named, Described):
    """
    This class provide full template for a ledger book, including accounts
    and journals.
    """

    # Accounts & Journal usage:
    # - fields providing usage to an account must finish with "_account";
    # - those for journals with "_journal"
    #
    # Naming convention:
    # acc: accumulated, dep: depreciation, amort: amortization
    # imp: impairment, exp: expense
    inventory_journal = models.ForeignKey(
        "ox_fin.journal", models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Inventory Journal")
    )
    amortization_journal = models.ForeignKey(
        "ox_fin.journal",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Amortization Journal"),
    )
    exercise_period = models.PositiveSmallIntegerField(
        _("Exercise length"), choices=Period.choices, default=Period.MONTH_12
    )
    exercise_start = models.PositiveSmallIntegerField(_("Exercise's start month"), default=1)

    retained_earnings_account = models.ForeignKey(
        "ox_fin.account",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Retained Earnings Account"),
    )

    class Meta:
        verbose_name = _("Book template")
        verbose_name_plural = _("Book templates")

    @classmethod
    def get_account_fields(cls) -> list[str]:
        return [f for f in cls._meta.get_fields() if f.name.endswith("_account")]

    @classmethod
    def get_journal_fields(cls) -> list[str]:
        return [f for f in cls._meta.get_fields() if f.name.endswith("_account")]

    def get_initial_balances(self) -> dict[int, Decimal]:
        """
        Return a dict of book initial balances (amount is always 0) by account id.
        """
        return {account_id: Decimal("0.") for account_id in self.accounts.all().values_list("id", flat=True)}

    def __str__(self):
        return self.name


class Account(LongNamed):
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

    # ---- Related accounts for different usages
    dep_exp_account = models.ForeignKey(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="expense_for_accounts",
        verbose_name=_("Depreciation / Amortization Expense Account"),
    )
    acc_dep_account = models.ForeignKey(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="accumulated_for_accounts",
        verbose_name=_("Accumulated Depreciation / Amortization Account"),
    )
    gain_account = models.ForeignKey(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="gain_for_accounts",
        verbose_name=_("Gains on asset Account"),
    )
    loss_account = models.ForeignKey(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="loss_for_accounts",
        verbose_name=_("Losses on asset Account"),
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

    @classmethod
    def get_account_fields(cls) -> list[str]:
        return [f for f in cls._meta.get_fields() if f.name.endswith("_account")]

    def __str__(self):
        postfix = f" [{self.short}]" if self.short else ""
        postfix += " - Debit" if self.is_debit else " - Credit" if self.is_debit is False else " - ?"
        return f"{self.code} - {self.name[:32]}{postfix}"


class Journal(Named):
    template = models.ForeignKey(BookTemplate, models.CASCADE, related_name="journals")
    code = models.CharField(_("Code"), max_length=10, help_text=_('For example "FIN" for "Finance".'))

    class Meta:
        verbose_name = _("Journal")
        verbose_name_plural = _("Journals")

    def __str__(self):
        return f"{self.code} - {self.name}"
