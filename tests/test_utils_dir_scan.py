from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.test import override_settings

from fin import models
from fin.utils.dir_scan import JournalScanner, BookScanner
from .conftest import TEST_MEDIA_ROOT


@pytest.fixture
def j_scanner(journal, book):
    return JournalScanner(journal=journal, path=Path(book.path) / "FIN")

@pytest.fixture
def b_scanner(book, journal, accounts):
    return BookScanner(book)


class TestJournalScanner:
    path_1 = Path("20250401 - 2025001 - Some label - cap:100, 20:80.5,21:19.5.pdf")
    dat_1 = {
        "date": date(2025, 4, 1),
        "reference": "2025001",
        "label": "Some label",
        "lines": [("cap", "100"), ("20", "80.5"), ("21", "19.5")]
    }
    path_2 = Path("20250402 - Some label 2 - cap:100, 20:80.5,21:19.5.pdf")
    dat_2 = {
        "date": date(2025, 4, 2),
        "label": "Some label 2",
        "lines": [("cap", "100"), ("20", "80.5"), ("21", "19.5")]
    }
    
    def test_accounts(self, j_scanner, account, accounts):
        assert j_scanner.accounts == {
            account.short: account,
            **{a.code: a for a in accounts}
        }

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_run(self, book, j_scanner, accounts):
        j_lines, lines = j_scanner.run(book)
        assert (len(j_lines), len(lines)) == (2, 6)
        assert all(isinstance(e, models.Move) for e in j_lines)
        assert all(isinstance(e, models.Line) for e in lines)

    def test_get_move(self, book, j_scanner, accounts):
        move, lines = j_scanner.get_move(book, Path(self.path_1))

        assert (move.journal, Path(move.document.path).stem) == (j_scanner.journal, self.path_1.stem)
        assert move.date == self.dat_1['date']
        assert move.reference == self.dat_1['reference']
        assert move.label == self.dat_1['label']

        for line, (key, amount) in zip(lines, self.dat_1['lines']):
            assert line.move == move
            assert line.account.code == key or line.account.short == key
            assert line.amount == Decimal(amount)

    def test_parse_filename(self, j_scanner):
        assert j_scanner.parse_filename(self.path_1.stem) == self.dat_1

    def test_read_lines(self, j_scanner):
        assert list(j_scanner.read_lines("a:12.3, b: 32.1,c:456")) == [
            ("a", "12.3"),
            ("b", "32.1"),
            ("c", "456"),
        ]


class TestBookScanner:
    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_run(self, book, b_scanner):
        b_scanner.run()
        assert book.moves.all().count() == 2
        assert models.Line.objects.filter(move__book=book).count() == 6

