from pathlib import Path
import pytest

from fin import models


TEST_MEDIA_ROOT = Path(__file__).parent / 'media'


@pytest.fixture
def book_template(transactional_db):
    return models.BookTemplate.objects.create(name='Template')

@pytest.fixture
def account(book_template):
    return models.Account.objects.create(template=book_template, name='Account 10', short='cap', code='10')

@pytest.fixture
def accounts(book_template, account):
    return [account] + models.Account.objects.bulk_create([
        models.Account(template=book_template, name='Account 101', code='101'),
        models.Account(template=book_template, name='Account 102', code='102'),
        models.Account(template=book_template, name='Account 20', code='20'),
        models.Account(template=book_template, name='Account 21', code='21'),
        models.Account(template=book_template, name='Account 210', code='210')
    ])


@pytest.fixture
def book(book_template):
    return models.Book.objects.create(name='Book', template=book_template, path=TEST_MEDIA_ROOT / Path('fin/book_1'))


@pytest.fixture
def journal(book_template):
    return models.Journal.objects.create(name='Finance', template=book_template, code='FIN')

@pytest.fixture
def journals(book_template, journal):
    return [journal] + models.Journal.objects.bulk_create([
        models.Journal(template=book_template, name='Diverse', code='DO'),
        models.Journal(template=book_template, name='Sells', code='SEL'),
    ])

@pytest.fixture
def move(book, journal):
    return models.Move.objects.create(book=book, journal=journal, label='Line 1', reference='2025001')

@pytest.fixture
def line(move, account):
    return models.Line.objects.create(move=move, account=account, amount=100)

@pytest.fixture
def lines(move, accounts, line):
    return [line] + models.Line.objects.bulk_create([
        models.Line(move=move, account=accounts[-1], amount=-10),
        models.Line(move=move, account=accounts[-2], amount=-80),
    ])
