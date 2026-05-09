from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Iterable


from fin.models.book_template import Account
from fin.models.book import Book, Line, Move, LineQuerySet


__all__ = (
    "LedgerView",
    "LedgerFlowView",
    "LedgerStateView",
    "OpeningView",
    "ProfitAndLossView",
    "BalanceSheetView",
)


class LedgerView:
    """
    Centralize all recurring ledger book logic, as a resolved time-bounded view
    of the book.
    """

    book: Book
    as_of: date
    """ View date. """
    opening_move: Move
    """ Latest opening move. """
    lines: LineQuerySet
    """ Queryset of lines from opening move (excluded) up to date. """

    is_flow: bool = False
    """ [class attribute] Whether the view is used as a flow or state  """

    include_move_types: Iterable[Move.Type] | None = None
    """ [class attribute] Include only lines with one of those move types. """
    include_move_types: Iterable[Move.Type] | None = None
    """ [class attribute] Exclude lines with one of those move types. """
    include_account_types: Iterable[Account.Type] | None = None
    """ [class attribute] Only include lines with one of those account types. """

    def __init__(self, book, as_of, **kwargs):
        self.book = book
        self.as_of = as_of

        self.opening_move = self.moves.opening().filter(date__lte=as_of).order_by("-date").first()
        if not self.opening_move:
            raise ValueError("Missing opening move.")

        self.lines = self.get_lines_queryset()
        for k, v in kwargs.items():
            setattr(self, k, v)

    @property
    def start_date(self):
        """Start of the view period."""
        return self.opening_move.date

    @property
    def end_date(self):
        """End of the view period."""
        return self.as_of

    @cached_property
    def initial_balances(self) -> dict[int, Decimal]:
        """Return opening balances, by account id."""
        if self.is_flow:
            return {}
        return dict(self.opening_move.lines.all().values_list("account_id", "amount"))

    def get_lines_queryset(self, all_types: bool = False):
        """Return base queryset for ledger view. It does not filter by move types.

        :param all_types: don't filter by move type or account type.
        :return the queryset, with related account and move selected
        """
        qs = (
            Line.objects.filter(move__book=self.book, move__date__gte=self.opening.date, move__date__lte=self.as_of)
            .exclude(move=self.opening)
            .select_related("move", "account")
        )
        if not all_types:
            if types := self.include_move_types:
                qs = qs.filter(move__type__in=types)
            if types := self.include_account_types:
                qs = qs.filter(account__type__in=types)
        return qs

    def is_balanced(self) -> bool:
        """Check if ledger is balanced (all balances' sum is 0)."""
        return sum(self.balances().values()) == Decimal("0.00")

    def has_closing(self) -> bool:
        """Check if a closing move exists in the same exercise window."""
        return (
            self.book.moves.closing()
            .filter(
                date__lte=self.as_of,
                exercise=self.book.get_exercise(self.as_of),
            )
            .exists()
        )

    def balances(self) -> dict[int, Decimal]:
        """Return balances for all accounts."""
        balances = self.initial_balances.copy()
        for account_id, norm_amount in self.lines.values_list("account_id", "norm_amount"):
            balances[account_id] += norm_amount
        return balances

    def balance(self, account_id: int) -> Decimal:
        """Return balance for a specific account id."""
        balance = self.initial_balances.get(account_id, Decimal("0."))
        qs = self.lines.filter(account_id=account_id)
        for norm_amount in qs.values_list("norm_amount", flat=True):
            balance += norm_amount
        return balance

    def trial_balance(self) -> dict[int, dict[str, Decimal]]:
        """
        Return a trial balance per account.
        This separates: debit total, credit total, net balance.
        """

        debit = defaultdict(Decimal)
        credit = defaultdict(Decimal)

        # Opening
        for acc_id, amount in self.initial_balances.items():
            if amount >= 0:
                debit[acc_id] += amount
            else:
                credit[acc_id] += -amount

        # Movements
        for acc_id, norm_amount in self.lines.values_list("account_id", "norm_amount"):
            if norm_amount >= 0:
                debit[acc_id] += norm_amount
            else:
                credit[acc_id] += -norm_amount

        accounts = set(debit) | set(credit)

        return {
            acc_id: {
                "debit": debit[acc_id],
                "credit": credit[acc_id],
                "balance": debit[acc_id] - credit[acc_id],
            }
            for acc_id in accounts
        }

    def balance_sheet_lines(self) -> LineQuerySet:
        """Return only balance sheet movement lines."""
        return self.lines.filter(
            account__type__in=(
                Account.Type.ASSET,
                Account.Type.LIABILITY,
                Account.Type.EQUITY,
            )
        )


class LedgerFlowView(LedgerView):
    """
    Operational flow view, representing the economic activity during a period.

    It can be used for P&L reports, closing computations, movement analysis.

    Includes: NORMAL, ADJUSTEMENT
    """

    is_flow = True
    include_move_types = (Move.Type.NORMAL, Move.Type.ADJUSTMENT)


class LedgerStateView(LedgerView):
    """
    Financial state view, representing the accumulated financial position at a given
    date.

    This view is used for: balance sheets, opening reconstruction, financial continuity.
    """

    pass


class OpeningView(LedgerStateView):
    """
    Opening reconstruction view.

    Represents the post-closing state used to generate
    the opening move of a new exercise.

    Since it derives from ``LedgerStateView``, all move types are included implicitly.
    """

    pass


class ProfitAndLossView(LedgerFlowView):
    """
    Profit & Loss view.

    Restricts the operational flow to economic result accounts only.

    Includes: REVENUE, EXPENSE

    Uses flow semantics: no opening, closing, equity adjustments
    """

    include_account_types = (Account.Type.REVENUE, Account.Type.EXPENSE)


class BalanceSheetView(LedgerStateView):
    """
    Balance sheet view.

    Restricts the financial state to balance sheet accounts.

    Includes: ASSET, LIABILITY, EQUITY

    Uses accumulated state semantics: opening, closing, equity adjustments included
    """

    include_account_types = (Account.Type.ASSET, Account.Type.LIABILITY, Account.Type.EQUITY)
