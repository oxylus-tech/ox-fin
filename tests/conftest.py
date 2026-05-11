from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta
import pytest

from fin import models
from fin.models import Account, Journal, Move, Line


TEST_MEDIA_ROOT = Path(__file__).parent / "media"


# TODO: move it in utilities.
class QuerySetSpy:
    """Helper class to check about queryset call statements."""

    def __init__(self, model=None, calls=None):
        self.model = model
        self.calls = calls or []

    def __getattr__(self, name):
        def recorder(*args, **kwargs):
            return type(self)(self.model, self.calls + [(name, args, kwargs)])

        return recorder

    def __eq__(self, other):
        return other.model == self.model and other.calls == self.calls

    # --- helpers ---
    def clear(self):
        self.calls = []

    def called(self, method_name):
        return any(call[0] == method_name for call in self.calls)

    def called_with(self, method_name, *expected_args, **expected_kwargs):
        return any(
            call[0] == method_name and call[1] == expected_args and call[2] == expected_kwargs for call in self.calls
        )

    def get_calls(self, method_name):
        return [c for c in self.calls if c[0] == method_name]


@pytest.fixture
def data_dir():
    return Path(__file__).parent / "data"


# ---- Book Template
@pytest.fixture
def book_template(transactional_db):
    return models.BookTemplate.objects.create(name="Template")


@pytest.fixture
def account(book_template):
    return Account.objects.create(
        template=book_template, name="Account 10", short="cap", code="10", type=Account.Type.REVENUE
    )


@pytest.fixture
def accounts(book_template, account):
    accounts = [account] + Account.objects.bulk_create(
        [
            Account(template=book_template, name="Account 101", code="101", type=Account.Type.REVENUE),
            Account(template=book_template, name="Account 102", code="102", type=Account.Type.REVENUE),
            Account(template=book_template, name="Account 20", code="20", type=Account.Type.EXPENSE),
            Account(template=book_template, name="Account 21", code="21", type=Account.Type.EXPENSE),
            Account(template=book_template, name="Account 210", code="210", type=Account.Type.EXPENSE),
            Account(template=book_template, name="Account 30", code="30", type=Account.Type.ASSET),
            Account(template=book_template, name="Account 31", code="31", type=Account.Type.ASSET),
            Account(template=book_template, name="Account 310", code="310", type=Account.Type.ASSET),
        ]
    )
    book_template.retained_earnings_account = accounts[-1]
    book_template.save(update_fields=["retained_earnings_account"])
    return accounts


@pytest.fixture
def journal(book_template):
    return Journal.objects.create(name="Finance", template=book_template, code="FIN")


@pytest.fixture
def journals(book_template, journal):
    return [journal] + Journal.objects.bulk_create(
        [
            Journal(template=book_template, name="Diverse", code="DO"),
            Journal(template=book_template, name="Sells", code="SEL"),
        ]
    )


# ---- Book
@pytest.fixture
def book(book_template):
    return models.Book.objects.create(title="Book", template=book_template, path=TEST_MEDIA_ROOT / Path("fin/book_1"))


@pytest.fixture
def move(book, journal):
    exercise = book.get_exercise(date.today(), create=True)
    return Move.objects.create(
        book=book, exercise=exercise, journal=journal, date=date.today(), description="Line 1", reference="2025001"
    )


@pytest.fixture
def moves(book, journal, move):
    return [move] + Move.objects.bulk_create(
        [
            Move(
                book=book,
                exercise=move.exercise,
                date=move.date,
                journal=journal,
                description="Line 2",
                reference="2025002",
            ),
            Move(
                book=book,
                exercise=move.exercise,
                date=move.date,
                journal=journal,
                description="Line 3",
                reference="2025003",
            ),
        ]
    )


@pytest.fixture
def line(move, account):
    return Line.objects.create(move=move, account=account, amount=100, is_debit=True)


@pytest.fixture
def lines(move, accounts, line):
    """Lines for move."""
    return [line] + Line.objects.bulk_create(
        [
            Line(move=move, account=accounts[-1], amount=-10, is_debit=False),
            Line(move=move, account=accounts[-2], amount=-80, is_debit=False),
        ]
    )


@pytest.fixture
def all_lines(moves, accounts, lines):
    """Lines for all moves."""
    return lines + Line.objects.bulk_create(
        [
            Line(move=moves[1], account=accounts[1], amount=200, is_debit=True),
            Line(move=moves[1], account=accounts[-4], amount=-100, is_debit=False),
            Line(move=moves[1], account=accounts[-3], amount=-100, is_debit=False),
            Line(move=moves[2], account=accounts[2], amount=-80, is_debit=True),
            Line(move=moves[2], account=accounts[-6], amount=-10, is_debit=False),
            Line(move=moves[2], account=accounts[-5], amount=-70, is_debit=False),
        ]
    )


# ---- Assets
@pytest.fixture
def fixed_asset(book, move, account):
    return models.FixedAsset.objects.create(
        book=book,
        move=move,
        account=account,
        type=models.FixedAsset.Type.TANGIBLE,
        date=move.date.replace(month=6, day=1),
        initial_value=10000,
    )


@pytest.fixture
def amortization_schedule(fixed_asset):
    return models.AmortizationSchedule.objects.create(
        asset=fixed_asset,
        start_date=fixed_asset.date,
        end_date=fixed_asset.date + relativedelta(years=5),
        method=models.AmortizationSchedule.Method.LINEAR,
        frequency=models.AmortizationSchedule.Frequency.ANNUAL,
        prorata=models.ProrataPolicy.NONE,
    )


@pytest.fixture
def amortization_entries(amortization_schedule):
    asset = amortization_schedule.asset
    return models.AmortizationEntry.objects.bulk_create(
        [
            models.AmortizationEntry(
                schedule=amortization_schedule,
                date=date(asset.date.year, 12, 31),
                amount=2000,
            )
            for i in range(0, 5)
        ]
    )


@pytest.fixture
def amortization_entry_moves(book, journal, amortization_entries):
    items = [Move(book=book, journal=journal, date=entry.date) for entry in amortization_entries]
    Move.objects.bulk_create(items)

    for entry, move in zip(amortization_entries, items):
        entry.move = move

    models.AmortizationEntry.objects.bulk_update(amortization_entries, ["move"])
    return items
