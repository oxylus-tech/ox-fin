from __future__ import annotations
from functools import cached_property
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Iterable

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Value, Case, When, Sum, ExpressionWrapper
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify


from .utils import Described, Titled
from .book_template import ProrataPolicy, Period, BookTemplate, Journal, Account


__all__ = ("Book", "MoveQuerySet", "Move", "Line")


class Book(Titled, Described):
    """The ledger book model."""

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
    amortization_prorata = models.PositiveSmallIntegerField(
        _("Amortizations Prorata Policy"),
        default=ProrataPolicy.NONE,
        choices=ProrataPolicy.choices,
    )
    exercise_period = models.PositiveSmallIntegerField(
        _("Exercise length"), choices=Period.choices, default=Period.MONTH_12
    )
    exercise_start = models.PositiveSmallIntegerField(_("Exercise's start month"), default=1)

    class Meta:
        verbose_name = _("Ledger Book")
        verbose_name_plural = _("Ledger books")

    def get_exercise(self, date: date | None = None, create: bool = False) -> Exercise:
        """
        Resolve the Exercise corresponding to a given date.

        If no Exercise exists for the given date and ``create=True``,
        the missing Exercise will be generated automatically.

        :param date: The date for which the Exercise must be resolved.
            If None, defaults to today's date.
        :param create: Whether to automatically create the Exercise if it
            does not exist.
        :returns: The Exercise matching the provided date (or newly created if requested).

        :raises ValueError: If no Exercise exists for the given date and ``create=False``.
        :raises ValidationError: If Exercise generation fails due to invalid fiscal configuration.
        """

        if date is None:
            date = date.today()

        if exercise := self.exercises.date(date).select_related("book").first():
            return exercise

        if not create:
            raise ValueError(f"No exercise found for date {date} in book {self.id}")

        return self._create_exercise_for_date(date)

    def _create_exercise_for_date(self, date):
        """
        Internal helper responsible for generating missing Exercises.

        This method uses the BookTemplate configuration to determine:
        - period length
        - fiscal alignment rules
        - start/end boundaries
        """
        start_date = Period.get_start(date, self.exercise_start, self.exercise_period)
        end_date = start_date + relativedelta(months=self.exercise_period) - relativedelta(days=1)
        return Exercise.objects.create(book=self, start_date=start_date, end_date=end_date)

    def save(self, *args, **kwargs):
        if not self.path:
            path = Path(settings.BOOKS_ROOT) / slugify(self.title)
            path.mkdir(exist_ok=True)
            self.path = str(path)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class ExerciseQuerySet(models.QuerySet):
    def date(self, date: date) -> ExerciseQuerySet:
        """Filter exercises that contains the provided date"""
        return self.filter(start_date__lte=date, end_date__gte=date)

    def between(self, start: date, end: date) -> ExerciseQuerySet:
        """Filter exercises withing the provided date range."""
        # FIXME: remove or better heuristic
        return self.filter(start_date__gte=start, end_date__lte=end)


class Exercise(models.Model):
    """Accounting period (fiscal year or sub-period)."""

    class State(models.IntegerChoices):
        OPEN = 1, _("Open")
        CLOSING = 2, _("Closing")
        CLOSED = 3, _("Closed")
        REOPENED = 4, _("Reopened")

    book = models.ForeignKey(Book, models.CASCADE, related_name="exercises", db_index=True, verbose_name=_("Book"))
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"))
    state = models.PositiveSmallIntegerField(_("State"), choices=State.choices, default=State.OPEN, db_index=True)

    objects = ExerciseQuerySet.as_manager()

    class Meta:
        verbose_name = _("Exercise")
        verbose_name_plural = _("Exercises")
        constraints = [models.UniqueConstraint(fields=["book", "start_date", "end_date"], name="unique_book_start_end")]

    @property
    def is_locked(self):
        return self.state == self.State.CLOSED

    def contains(self, date):
        return self.start_date < date < self.end_date

    def __str__(self):
        return f"{self.book} [{self.start_date} → {self.end_date}]"


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
    """A Journal entry."""

    class Type(models.IntegerChoices):
        """Type of entry line."""

        NORMAL = 0x00, _("Movement")
        OPENING = 0x01, _("Opening")
        CLOSING = 0x02, _("Closing")
        ADJUSTMENT = 0x03, _("Adjustment")

    book = models.ForeignKey(Book, models.PROTECT, related_name="moves", verbose_name=_("Book"), db_index=True)
    journal = models.ForeignKey(Journal, models.PROTECT, verbose_name=_("Journal"))
    exercise = models.ForeignKey(
        Exercise, models.PROTECT, related_name="moves", verbose_name=_("Exercise"), db_index=True
    )
    type = models.PositiveSmallIntegerField(_("Type"), choices=Type.choices, default=Type.NORMAL)
    document = models.FileField(_("Document"), blank=True, null=True)

    date = models.DateField(_("Date"), default=date.today)
    reference = models.CharField(_("Reference"), max_length=64, null=True, blank=True)
    description = models.CharField(_("Description"), max_length=128)

    class Meta:
        verbose_name = _("Journal Entry")
        verbose_name_plural = _("Journal Entries")
        indexes = [
            models.Index(fields=["exercise", "date"]),
            models.Index(fields=["book", "exercise"]),
        ]

    @cached_property
    def full_reference(self):
        if not self.reference.startswith(self.journal.code):
            return f"{self.journal.code}/{self.reference}"
        return self.reference

    def clean(self):
        if self.book.template != self.journal.template:
            raise ValidationError("Journal is not allowed in this book")

        # enforce line account is clean
        # TODO: enforce different accounts
        if self.pk:
            for line in self.lines.all():
                line.clean()

    def validate_lines(self, lines: Iterable[models.Line] | None = None):
        """
        Validate lines for a move, using provided lines (or related ones if any).

        :param lines: use those lines instead of ``self.lines.all()``
        :yield ValidationError: on invalid type between move and lines
        :yield ValidationError: on invalid balance.
        """
        debit, credit = Decimal("0.0"), Decimal("0.0")

        if lines is None:
            lines = self.lines.all()

        for line in self.lines.all():
            debit += line.debit
            credit += line.credit

        if debit != credit:
            raise ValidationError(f"The balance is not 0 ({debit-credit}): debit={debit} credit={credit}")

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} - {self.full_reference}"


class LineQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.ensure_debit()
        return super().bulk_create(objs, **kwargs)

    def with_norm_amount(self):
        """Annotate with ``norm_amount``, which is the right amount based on
        account and line type (debit/credit)."""
        if hasattr(self.query, "annotations") and "norm_amount" in self.query.annotations:
            return self

        return self.annotate(
            norm_amount=Case(
                When(account__type__in=[Account.Type.VIEW], then=Value(0)),
                When(is_debit=F("account__is_debit"), then=F("amount")),
                default=-F("amount"),
                output_field=models.DecimalField(),
            )
        )


class Line(models.Model):
    """A debit or credit in the :py:class:`Move`."""

    move = models.ForeignKey(Move, models.CASCADE, related_name="lines", db_index=True)
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
        verbose_name = _("Journal Entry Line")
        verbose_name_plural = _("Journal Entry Lines")
        indexes = [models.Index(fields=["move", "account"])]

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

    def __str__(self):
        return f"{self.move} - {self.account.code}={self.amount}"
