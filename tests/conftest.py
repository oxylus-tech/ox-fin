from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta
import pytest

from fin import models


TEST_MEDIA_ROOT = Path(__file__).parent / "media"


@pytest.fixture
def data_dir():
    return Path(__file__).parent / "data"


# ---- Book Template
@pytest.fixture
def book_template(transactional_db):
    return models.BookTemplate.objects.create(name="Template")


@pytest.fixture
def account(book_template):
    return models.Account.objects.create(template=book_template, name="Account 10", short="cap", code="10")


@pytest.fixture
def accounts(book_template, account):
    return [account] + models.Account.objects.bulk_create(
        [
            models.Account(template=book_template, name="Account 101", code="101"),
            models.Account(template=book_template, name="Account 102", code="102"),
            models.Account(template=book_template, name="Account 20", code="20"),
            models.Account(template=book_template, name="Account 21", code="21"),
            models.Account(template=book_template, name="Account 210", code="210"),
        ]
    )


@pytest.fixture
def journal(book_template):
    return models.Journal.objects.create(name="Finance", template=book_template, code="FIN")


@pytest.fixture
def journals(book_template, journal):
    return [journal] + models.Journal.objects.bulk_create(
        [
            models.Journal(template=book_template, name="Diverse", code="DO"),
            models.Journal(template=book_template, name="Sells", code="SEL"),
        ]
    )


# ---- Book
@pytest.fixture
def book(book_template):
    return models.Book.objects.create(title="Book", template=book_template, path=TEST_MEDIA_ROOT / Path("fin/book_1"))


@pytest.fixture
def move(book, journal):
    return models.Move.objects.create(book=book, journal=journal, description="Line 1", reference="2025001")


@pytest.fixture
def line(move, account):
    return models.Line.objects.create(move=move, account=account, amount=100)


@pytest.fixture
def lines(move, accounts, line):
    return [line] + models.Line.objects.bulk_create(
        [
            models.Line(move=move, account=accounts[-1], amount=-10),
            models.Line(move=move, account=accounts[-2], amount=-80),
        ]
    )


# ---- Assets
@pytest.fixture
def fixed_asset(book, move):
    return models.FixedAsset.objects.create(
        book=book,
        move=move,
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
    items = [models.Move(book=book, journal=journal, date=entry.date) for entry in amortization_entries]
    models.Move.objects.bulk_create(items)

    for entry, move in zip(amortization_entries, items):
        entry.move = move

    models.AmortizationEntry.objects.bulk_update(amortization_entries, ["move"])
    return items


# ---- Rules
@pytest.fixture
def move_rule(book_template, journal):
    return models.MoveRule.objects.create(template=book_template, journal=journal, name="Invoice Sent", code="INV-IN")


@pytest.fixture
def line_rule(move_rule, account):
    return models.LineRule.objects.create(
        move_rule=move_rule,
        name="Client HT",
        account=account,
        code="ht",
        formula="tt-vat",
    )


@pytest.fixture
def line_rules(move_rule, line_rule, accounts):
    return [line_rule] + models.LineRule.objects.bulk_create(
        [
            models.LineRule(
                move_rule=move_rule,
                name="VAT",
                account=accounts[1],
                code="vat",
                formula="ht*0.21 if ht else tt/1.21",
            ),
            models.LineRule(
                move_rule=move_rule,
                name="Client Total",
                account=accounts[2],
                code="tt",
                formula="vat+ht",
            ),
        ]
    )
