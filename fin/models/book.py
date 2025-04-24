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
            path.mkdir()
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


class Line(models.Model):
    """A debit or credit in the :py:class:`Move`."""

    move = models.ForeignKey(Move, models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, models.PROTECT, verbose_name=_("Account"))
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = _("Line")
        verbose_name_plural = _("Lines")

    @cached_property
    def is_debit(self):
        return (self.account.is_debit and self.amount > 0) or (self.account.is_debit is False and self.amount < 0)

    @cached_property
    def is_credit(self):
        return (self.account.is_debit and self.amount < 0) or (self.account.is_debit is False and self.amount > 0)

    def clean(self):
        if self.account.template != self.move.book.template:
            raise ValidationError("Account is not allowed in this book")
