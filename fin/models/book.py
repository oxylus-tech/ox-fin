from __future__ import annotations
from functools import cached_property
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Value, Case, When, Sum, ExpressionWrapper
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify


from .utils import Described
from .template import BookTemplate, Journal, Account


__all__ = ("Book", "MoveQuerySet", "Move", "Line")


class Book(Described):
    template = models.ForeignKey(BookTemplate, models.PROTECT)
    # code = models.CharField(max_length=10, default='')
    # owner = models.ForeignKey(Contact, models.CASCADE)
    path = models.FilePathField(
        _("Document directory"),
        path=settings.BOOKS_ROOT,
        unique=True,
        blank=True,
        allow_files=False,
        allow_folders=True,
    )

    class Meta:
        verbose_name = _("Ledger Book")
        verbose_name_plural = _("Ledger books")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.path:
            path = Path(settings.BOOKS_ROOT) / slugify(self.name)
            path.mkdir(exist_ok=True)
            self.path = str(path)
        super().save(*args, **kwargs)


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
        if self.pk:
            for line in self.lines.all():
                line.clean()

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} - {self.full_reference}"


class LineQuerySet(models.QuerySet):
    def bulk_create(self, objs):
        for obj in objs:
            obj.ensure_debit()
        return super().bulk_create(objs)


class Line(models.Model):
    """A debit or credit in the :py:class:`Move`."""

    move = models.ForeignKey(Move, models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, models.PROTECT, verbose_name=_("Account"))
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)
    is_debit = models.BooleanField(_("Is Debit"))
    is_credit = models.GeneratedField(
        expression=Case(
            When(is_debit=False, then=Value(True)), default=Value(False), output_field=models.BooleanField()
        ),
        output_field=models.BooleanField(),
        db_persist=True,
        verbose_name=_("Is Credit"),
    )

    objects = LineQuerySet.as_manager()

    class Meta:
        verbose_name = _("Line")
        verbose_name_plural = _("Lines")

    @property
    def debit(self):
        return self.amount if self.is_debit else 0

    @debit.setter
    def debit(self, value):
        self.amount = value
        self.is_debit = True

    @property
    def credit(self):
        return self.amount if not self.is_debit else 0

    @credit.setter
    def credit(self, value):
        self.amount = value
        self.is_debit = False

    @cached_property
    def norm_amount(self):
        """Normalized amount depending on account's type."""
        if self.is_debit == self.account.is_debit:
            return self.amount
        return -self.amount

    def clean(self):
        self.ensure_debit()
        if self.account.template != self.move.book.template:
            raise ValidationError("Account is not allowed in this book")

    def ensure_debit(self):
        if self.amount < 0:
            # FIXME: case: self.account.is_debit is None
            self.is_debit = not (self.is_debit if self.is_debit is not None else self.account.is_debit)
            self.amount = -self.amount

    def save(self, *args, **kwargs):
        self.ensure_debit()
        super().save(*args, **kwargs)
