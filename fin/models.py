from __future__ import annotations
from functools import cached_property
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Value, Case, When, Sum, ExpressionWrapper
from django.utils.translation import gettext_lazy as _


# class Contact(models.Model):
#     fullname = models.CharField(max_length=64, db_index=True)
#     short = models.CharField(max_length=16, default='', blank=True)
#     vat = models.CharField(max_length=64, db_index=True, blank=True, null=True)
#
#     first_name = models.CharField(max_length=64, default='', blank=True)
#     last_name = models.CharField(max_length=64, default='', blank=True)
#
#     email = models.EmailField(blank=True, null=True)
#     phone = models.CharField(max_length=34, blank=True, null=True)
#
#     address_1 = models.CharField(max_length=128, blank=True, null=True)
#     address_2 = models.CharField(max_length=128, blank=True, null=True)
#
#     country = models.CharField(max_length=32, blank=True, null=True)


class BookTemplate(models.Model):
    """
    This class provide full template for a ledger book, including accounts
    and journals.
    """

    name = models.CharField(_("Name"), max_length=64)
    description = models.TextField(_("Description"), default="", blank=True)

    class Meta:
        verbose_name = _("Book template")
        verbose_name_plural = _("Book templates")

    def __str__(self):
        return self.name


class Account(models.Model):
    """A ledger account."""

    class Type(models.IntegerChoices):
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
    name = models.CharField(_("Name"), max_length=128)
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
        return f"{self.code} - {self.name}{postfix}"


class Journal(models.Model):
    template = models.ForeignKey(BookTemplate, models.CASCADE, related_name="journals")
    name = models.CharField(_("Name"), max_length=64)
    code = models.CharField(_("Code"), max_length=10, help_text=_('For example "FIN" for "Finance".'))

    class Meta:
        verbose_name = _("Journal")
        verbose_name_plural = _("Journals")

    def __str__(self):
        return f"{self.code} - {self.name}"


class Book(models.Model):
    template = models.ForeignKey(BookTemplate, models.PROTECT)
    name = models.CharField(_("Name"), max_length=64)
    description = models.TextField(_("Description"), default="", blank=True)
    # code = models.CharField(max_length=10, default='')
    # owner = models.ForeignKey(Contact, models.CASCADE)
    path = models.FilePathField(_("Document directory"), unique=True)

    class Meta:
        verbose_name = _("Ledger Book")
        verbose_name_plural = _("Ledger books")

    def __str__(self):
        return self.name


class MoveQuerySet(models.QuerySet):
    def with_balance(self):
        return self.annotate(
            balance=Sum(
                Case(
                    When(lines__is_debit=True, then=F("lines__amount")),
                    When(lines__is_debit=False, then=F("lines__amount") * -1),
                )
            ),
            is_balanced=ExpressionWrapper(
                Case(When(balance=0, then=Value(True)), default=Value(False)), output_field=models.BooleanField()
            ),
        )


class Move(models.Model):
    book = models.ForeignKey(Book, models.PROTECT, related_name="moves")
    journal = models.ForeignKey(Journal, models.PROTECT)
    document = models.FileField(_("Document"), blank=True, null=True)

    date = models.DateField(_("Date"), default=date.today)
    reference = models.CharField(_("Reference"), max_length=64, null=True, blank=True)
    label = models.CharField(_("Label"), max_length=128)

    class Meta:
        verbose_name = _("Move")
        verbose_name_plural = _("Moves")

    @cached_property
    def full_reference(self):
        return f"{self.journal.code}/{self.reference}"

    def clean(self):
        if self.book.template != self.journal.template:
            raise ValidationError("Journal is not allowed in this book")

        # enforce line account is clean
        # TODO: enforce different accounts
        for line in self.lines.all():
            line.clean()

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} - {self.full_reference}"


class Line(models.Model):
    """A debit or credit in the :py:class:`Move`."""

    move = models.ForeignKey(Move, models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, models.PROTECT, verbose_name=_("Account"))
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = _("Move line")
        verbose_name_plural = _("Move lines")

    @cached_property
    def is_debit(self):
        return (self.account.is_debit and self.amount > 0) or (self.account.is_debit is False and self.amount < 0)

    @cached_property
    def is_credit(self):
        return (self.account.is_debit and self.amount < 0) or (self.account.is_debit is False and self.amount < 0)

    def clean(self):
        if self.account.template != self.move.book.template:
            raise ValidationError("Account is not allowed in this book")


class InvoiceFlow(models.Model):
    template = models.OneToOneField(BookTemplate, models.PROTECT)
    bank = models.ForeignKey(Account, models.PROTECT, related_name="+")

    in_invoice_debt = models.ForeignKey(Account, models.PROTECT, related_name="+")
    in_invoice_vat = models.ForeignKey(Account, models.PROTECT, related_name="+")
    in_invoice_client = models.ForeignKey(Account, models.PROTECT, related_name="++")

    out_invoice_debt = models.ForeignKey(Account, models.PROTECT, related_name="+")
    out_invoice_vat = models.ForeignKey(Account, models.PROTECT, related_name="+")
    out_invoice_client = models.ForeignKey(Account, models.PROTECT, related_name="++")
