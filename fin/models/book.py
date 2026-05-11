from __future__ import annotations
from datetime import date
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Iterable

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Value, Case, When, Sum, ExpressionWrapper
from django.utils.translation import gettext_lazy as _, gettext as __
from django.utils.text import slugify


from .utils import Described, Titled
from .enums import ProrataPolicy, Period
from .book_template import BookTemplate, Journal, Account


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

    def get_exercise(self, date: date | None = None, create: bool = False, open: bool = False) -> Exercise:
        """
        Resolve the Exercise corresponding to a given date.

        If no Exercise exists for the given date and ``create=True``,
        the missing Exercise will be generated automatically.

        :param date: The date for which the Exercise must be resolved.
            If None, defaults to today's date.
        :param create: Whether to automatically create the Exercise if it
            does not exist.
        :param open: Open exercise if created.
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

        exercise = self._create_exercise_for_date(date)
        if open:
            exercise.open()
        return exercise

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


class Exercise(models.Model):
    """Accounting period (fiscal year or sub-period)."""

    class State(models.IntegerChoices):
        DRAFT = 0, _("Draft")
        OPEN = 1, _("Open")
        CLOSING = 2, _("Closing")
        CLOSED = 3, _("Closed")
        REOPENED = 4, _("Reopened")
        FINALIZED = 5, _("Finalized")

    MOVE_RULES = {
        State.DRAFT: {"OPENING"},
        State.OPEN: {"NORMAL", "ADJUSTMENT", "EQUITY_ADJUSTMENT"},
        State.CLOSED: {"CLOSING"},
        State.REOPENED: {"OPENING", "NORMAL", "ADJUSTMENT", "EQUITY_ADJUSTMENT"},
    }
    """ Validation rules of move type for each state. """
    STATE_RULES = {
        State.DRAFT: {State.OPEN},
        State.OPEN: {State.CLOSING, State.CLOSED},
        State.CLOSING: {State.CLOSED},
        State.CLOSED: {State.REOPENED},
        State.REOPENED: {State.FINALIZED},
    }
    """ Validation rules of next state for each state. """

    book = models.ForeignKey(Book, models.CASCADE, related_name="exercises", db_index=True, verbose_name=_("Book"))
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"))
    state = models.PositiveSmallIntegerField(_("State"), choices=State.choices, default=State.DRAFT, db_index=True)
    opening_move = models.ForeignKey(
        "ox_fin.move",
        models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Opening Move"),
    )

    objects = ExerciseQuerySet.as_manager()

    class Meta:
        verbose_name = _("Exercise")
        verbose_name_plural = _("Exercises")
        constraints = [models.UniqueConstraint(fields=["book", "start_date", "end_date"], name="unique_book_start_end")]

    @property
    def is_locked(self):
        return self.state in (Exercise.State.CLOSED, Exercise.State.CLOSING, Exercise.State.FINALIZED)

    def open(self, force: bool = False) -> Move:
        """Create the opening move for the exercise, and return it.

        Return the existing move if any unless ``force`` is set. In such
        case it is recreated.

        Generate opening lines based on balance at the end of the previous
        exercise.

        :param date: a date in the exercise
        :param force: force re-creation if it exists;
        """
        from fin.engine.ledger import OpeningView

        self.validate_next_state(Exercise.State.OPEN)
        opening = self.moves.opening().first()

        if opening and not force:
            return opening

        with transaction.atomic():
            if opening:
                opening.delete()

            if Move.objects.filter(book=self.book).exists():
                ledger = OpeningView(self.book, self.start_date, self.end_date)
                balances = ledger.balances()
            else:
                # Enforce accounts initialization with 0.00 amount balances
                balances = self.book.template.get_initial_balances()

            move = Move.objects.create(
                book=self.book,
                exercise=self,
                type=Move.Type.OPENING,
                date=self.start_date,
                description=__("Opening {exercise}").format(exercise=self),
            )

            lines = [
                Line(move=move, account_id=account_id, amount=balance, is_debit=balance >= 0)
                for account_id, balance in balances.items()
            ]
            Line.objects.bulk_create(lines)

            self.state = Exercise.State.OPEN
            self.opening_move = move
            self.save(update_fields=["state", "opening_move"])
            return move

    def close(self, force: bool = False):
        """Close the exercise containing ``date``.

        It will:
            - compute final P&L
            - creates the closing move
            - transfers results to retained earning
        """
        from fin.engine.ledger import ProfitAndLossView

        self.validate_next_state(Exercise.State.CLOSING)
        self.state = Exercise.State.CLOSING
        self.save(update_fields=["state"])

        template = self.book.template
        if not template.retained_earnings_account:
            raise ValueError("The book template does not defined a retained earning account")

        closing = self.moves.closing().first()
        if closing and not force:
            return closing

        with transaction.atomic():
            if closing:
                closing.delete()

            ledger = ProfitAndLossView(self.book, self.end_date, self.start_date)
            balances = ledger.balances()

            # ---- Compute result (P&L only)
            profit = Decimal("0.00")
            for account_id, balance in balances.items():
                account = Account.objects.get(pk=account_id)
                if account.type in (Account.Type.REVENUE, Account.Type.EXPENSE):
                    profit += balance

            closing = Move.objects.create(
                book=self.book,
                exercise=self,
                type=Move.Type.CLOSING,
                date=self.end_date,
                description=__("Closing {exercise}").format(exercise=self),
            )
            lines = []

            for account_id, balance in balances.items():
                # FIXME: optimize it
                account = Account.objects.get(pk=account_id)
                if account.type in (Account.Type.REVENUE, Account.Type.EXPENSE):
                    if balance != 0:
                        amount = -balance
                        lines.append(Line(move=closing, account_id=account_id, amount=amount, is_debit=(amount >= 0)))

            # ---- Transfer result to retained earnings
            retained_earnings = template.retained_earnings_account
            lines.append(Line(move=closing, account=retained_earnings, amount=-profit, is_debit=(profit < 0)))

            Line.objects.bulk_create(lines)

            # ---- Finalize self state
            self.state = Exercise.State.CLOSED
            self.save(update_fields=["state"])
            return closing

    def reopen(self):
        """
        Reopen a previously closed exercise.

        This removes:
        - closing, equity adjustment moves
        - dependent opening moves of following exercises

        Economic journal entries are preserved.
        """
        self.validate_next_state(Exercise.State.REOPENED)

        with transaction.atomic():
            # ---- Remove closing move(s)
            self.moves.closing().delete()
            self.moves.equity_adjustment().delete()

            # ---- Remove next opening move
            next_exercise = (
                Exercise.objects.filter(book_id=self.book_id, start_date__gt=self.end_date)
                .order_by("start_date")
                .first()
            )

            if next_exercise:
                if next_exercise.state in (Exercise.State.OPEN, Exercise.State.REOPENED):
                    next_exercise.state = Exercise.State.DRAFT

                if next_opening := next_exercise.opening_move:
                    next_exercise.opening_move = None
                    next_exercise.save(update_fields=["state", "opening_move"])
                    next_opening.delete()
                else:
                    next_exercise.save(update_fields=["state"])

            # ---- Reopen current exercise
            self.state = Exercise.State.OPEN
            self.save(update_fields=["state"])

    def validate_next_state(self, next_state: State, no_exc: bool = False) -> bool:
        """Validate next exercise state again'st current one.

        :param next_state: next state to validate
        :param no_exc: return a boolean instead of raising an error
        :raises ValidationError: invalid state.
        """
        allowed = self.STATE_RULES.get(self.state)
        if allowed and next_state in allowed:
            return True
        if no_exc:
            return False
        raise ValidationError(
            f"Invalid next state {self.State(next_state).name} for state {self.State(self.state).name}"
        )

    def validate_move_type(self, move_type: Move.Type, no_exc: bool = False) -> bool:
        """Validate move type again'st exercise state..

        :param move_type: move type to validate
        :param no_exc: return a boolean instead of raising an error.
        :raises ValidationError: invalid move type.
        """
        allowed = self.MOVE_RULES.get(self.state)
        move_type = Move.Type(move_type).name
        if allowed and move_type in allowed:
            return True
        if no_exc:
            return False
        raise ValidationError(f"Invalid move type {move_type} for state {self.State(self.state).name}")

    def contains(self, date: date) -> bool:
        """Return wether a date is contained within this period."""
        return self.start_date <= date <= self.end_date

    def __str__(self):
        return f"{self.book} [{self.start_date} → {self.end_date}]"


class MoveQuerySet(models.QuerySet):
    def exercise(self, exercise):
        """Return moves in the following exercise."""
        return self.filter(exercise=exercise)

    def economic(self):
        """Return moves contributing to economic activity (normal and adjustments)."""
        return self.filter(type__in=(Move.Type.NORMAL, Move.Type.ADJUSTMENT))

    def opening(self):
        return self.filter(type=Move.Type.OPENING)

    def closing(self):
        return self.filter(type=Move.Type.CLOSING)

    def snapshot(self, exclude=False):
        """OPENING and CLOSING moves."""
        if exclude:
            return self.exclude(type__in=(Move.Type.OPENING, Move.Type.CLOSING))
        return self.filter(type__in=(Move.Type.OPENING, Move.Type.CLOSING))

    def equity_adjustment(self):
        return self.filter(type=Move.Type.EQUITY_ADJUSTMENT)

    def non_opening(self):
        return self.exclude(type=Move.Type.OPENING)

    def non_closing(self):
        return self.exclude(type=Move.Type.CLOSING)

    def with_balance(self):
        """Annotate objects with ``balance`` and ``is_balance``."""
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
        """ Describes a regular account movements. """
        OPENING = 0x01, _("Opening")
        """
        The move describes an opening snapshot.

        This implies that all previous moves of the will be ignored for balance
        calculation. When an account is not present, this is assumed that the
        account balance is 0.
        """
        CLOSING = 0x02, _("Closing")
        """ The move describes a closing snapshot. """
        ADJUSTMENT = 0x03, _("Adjustment")
        """ The move describes an adjustment. """
        EQUITY_ADJUSTMENT = 0x04, _("Equity Adjustment")
        """ Adjustement for accounts equity. """

    book = models.ForeignKey(Book, models.PROTECT, related_name="moves", verbose_name=_("Book"), db_index=True)
    journal = models.ForeignKey(Journal, models.PROTECT, null=True, verbose_name=_("Journal"))
    exercise = models.ForeignKey(
        Exercise, models.PROTECT, related_name="moves", verbose_name=_("Exercise"), db_index=True
    )
    type = models.PositiveSmallIntegerField(_("Type"), choices=Type.choices, default=Type.NORMAL)
    document = models.FileField(_("Document"), blank=True, null=True)

    date = models.DateField(_("Date"), default=date.today)
    reference = models.CharField(_("Reference"), max_length=64, null=True, blank=True)
    description = models.CharField(_("Description"), max_length=128)

    objects = MoveQuerySet.as_manager()

    class Meta:
        verbose_name = _("Journal Entry")
        verbose_name_plural = _("Journal Entries")
        indexes = [
            models.Index(fields=["exercise", "date"]),
            models.Index(fields=["book", "exercise"]),
        ]

    @cached_property
    def full_reference(self):
        if not self.reference:
            return f"Move {self.pk}"
        if not self.reference.startswith(self.journal.code):
            return f"{self.journal.code}/{self.reference}"
        return self.reference

    def validate(self, lines: Iterable[Line] | None = None):
        """Validate move type and values.

        :param lines: use those lines instead of move.lines;
        :raises ValidationError: a validation failed.
        """
        if self.book.template != self.journal.template:
            raise ValidationError("Journal is not allowed in this book")

        self.exercise.validate_move_type(self.type)

        if self.type == self.Type.OPENING and self.exercise.opening_move_id != self.pk:
            raise ValidationError("There can only be one opening move per exercise.")
        elif self.type != self.Type.OPENING and self.exercise.opening_move_id is None:
            raise ValidationError("You first must open the move exercise.")

        if lines or self.pk:
            self.validate_lines(lines)

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

    def clean(self):
        if self.book.template != self.journal.template:
            raise ValidationError("Journal is not allowed in this book")

        # enforce line account is clean
        # TODO: enforce different accounts
        if self.pk:
            for line in self.lines.all():
                line.clean()

    # def save(self, *args, **kwargs):
    #    self.validate()
    #    return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} - {self.full_reference}"


class LineQuerySet(models.QuerySet):
    def movements(self):
        """Only return lines that are movements (normal and adjustment moves)."""
        return self.filter(move__type__in=(Move.Type.NORMAL, Move.Type.ADJUSTMENT))

    def with_norm_amount(self):
        """Annotate with ``norm_amount``, which is the right amount based on
        account and line type (debit/credit)."""
        if hasattr(self.query, "annotations") and "norm_amount" in self.query.annotations:
            return self

        return self.annotate(
            norm_amount=Case(
                When(
                    move__type__in=(Move.Type.OPENING, Move.Type.CLOSING),
                    then=F("amount"),
                ),
                When(account__type__in=[Account.Type.VIEW], then=Value(0)),
                When(is_debit=F("account__is_debit"), then=F("amount")),
                default=-F("amount"),
                output_field=models.DecimalField(),
            )
        )

    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.ensure_debit()
        return super().bulk_create(objs, **kwargs)


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
