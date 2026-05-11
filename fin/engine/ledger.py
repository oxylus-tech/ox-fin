from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Iterable

from django.db.models import Sum
from fin.models.book_template import Account
from fin.models.book import Book, Line, Move


__all__ = (
    "LedgerFlowView",
    "LedgerStateView",
    "OpeningView",
    "ProfitAndLossView",
    "BalanceSheetView",
)


class BaseLedgerView:
    """
    Shared technical layer for ledger queries.

    Does NOT define accounting semantics.
    """

    book: Book
    start_date: date | None
    end_date: date

    include_move_types: Iterable[Move.Type] | None = None
    exclude_move_types: Iterable[Move.Type] | None = None
    include_account_types: Iterable[Account.Type] | None = None

    def __init__(self, book, end_date: date, start_date: date | None = None):
        self.book = book
        self.start_date = min(start_date, end_date)
        self.end_date = max(start_date, end_date)
        self.qs = self.get_lines_queryset()

    def get_lines_queryset(self):
        qs = Line.objects.filter(move__book=self.book, move__date__lte=self.end_date)

        if self.include_move_types:
            qs = qs.filter(move__type__in=self.include_move_types)

        if self.exclude_move_types:
            qs = qs.exclude(move__type__in=self.exclude_move_types)

        if self.include_account_types:
            qs = qs.filter(account__type__in=self.include_account_types)

        return qs.with_norm_amount().select_related("move", "account")

    def balances(self):
        """Return balances."""
        return dict(self.qs.values("account_id").annotate(total=Sum("norm_amount")).values_list("account_id", "total"))

    def balance(self, account_id: int):
        return self.qs.filter(account_id=account_id).aggregate(total=Sum("norm_amount"))["total"] or Decimal("0.00")


class LedgerFlowView(BaseLedgerView):
    """Flow view: only movements within a period."""

    include_move_types = {
        Move.Type.NORMAL,
        Move.Type.ADJUSTMENT,
        Move.Type.EQUITY_ADJUSTMENT,
    }

    # Enforce start_date to be provided
    def __init__(self, book, end_date: date, start_date: date):
        super().__init__(book, end_date, start_date)

    def get_lines_queryset(self):
        return super().get_lines_queryset().filter(move__date__gte=self.start_date)


class LedgerStateView(BaseLedgerView):
    """
    State view: full reconstructed ledger state.
    """

    include_move_types = {
        Move.Type.OPENING,
        Move.Type.NORMAL,
        Move.Type.ADJUSTMENT,
        Move.Type.CLOSING,
        Move.Type.EQUITY_ADJUSTMENT,
    }

    def __init__(self, book, end_date: date, start_date: date | None = None):
        super().__init__(book, end_date, start_date)

        self.opening_move = (
            Move.objects.filter(book=book, type=Move.Type.OPENING, date__lte=end_date).order_by("-date").first()
        )

        if not self.opening_move:
            raise ValueError("Missing opening move")

    def get_lines_queryset(self):
        return super().get_lines_queryset().filter(move__date__gte=self.opening_move.date)

    def balance(self, account_id: int):
        return self.balances().get(account_id, Decimal("0.00"))


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
