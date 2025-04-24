from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from fin import models
from fin.utils import dir_scan
from .conftest import TEST_MEDIA_ROOT


@pytest.fixture
def m_scan(book, journal):
    return dir_scan.MoveScan(book, journal)


@pytest.fixture
def j_scan(journal, book):
    return dir_scan.JournalScan(book, journal)


@pytest.fixture
def mr_scan(move_rule, book):
    return dir_scan.JournalScan(book, move_rule)


@pytest.fixture
def b_scan(book, journal, accounts):
    return dir_scan.BookScan(book)


path_1 = Path("20250401 - 2025001 - Some label - cap:100, 20:80.5,21:19.5.pdf")
dat_1 = {
    "date": date(2025, 4, 1),
    "reference": "2025001",
    "label": "Some label",
    "values": [("cap", Decimal("100")), ("20", Decimal("80.5")), ("21", Decimal("19.5"))],
}
path_2 = Path("20250402 - Some label 2 - cap:100, 20:80.5,21:19.5.pdf")
dat_2 = {
    "date": date(2025, 4, 2),
    "label": "Some label 2",
    "reference": None,
    "values": [("cap", Decimal("100")), ("20", Decimal("80.5")), ("21", Decimal("19.5"))],
}
dat_3 = {
    "date": date(2025, 4, 2),
    "label": "Some label 2",
    "values": [("tt", Decimal("121")), ("ht", Decimal("100")), ("vat", Decimal("21"))],
}


class TestMoveScan:
    def test_scan(self, m_scan, line):
        m_scan.iterdir = lambda *a: [path_1, path_2]
        m_scan.get_lines = lambda *a, **kw: [line]

        moves, lines = m_scan.scan(Path())

        # two lines, because get_lines is called twice
        assert (len(moves), len(lines)) == (2, 2)
        assert all(isinstance(m, models.Move) for m in moves)
        assert all(isinstance(ln, models.Line) for ln in lines)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_iterdir(self, m_scan, book, journal):
        path = Path(book.path) / "FIN"
        paths = m_scan.iterdir(path)
        assert len(paths) > 0

        models.Move.objects.create(book=book, journal=journal, document=str(paths[0].relative_to(settings.MEDIA_ROOT)))
        paths_2 = m_scan.iterdir(path)
        assert len(paths_2) < len(paths)

    def test_parse_path(self, m_scan):
        assert m_scan.parse_path(path_1) == dat_1
        assert m_scan.parse_path(path_2) == dat_2

    def test_parse_values(self, m_scan):
        assert list(m_scan.parse_values("a:12.3, b: 32.1,c:456")) == [
            ("a", Decimal("12.3")),
            ("b", Decimal("32.1")),
            ("c", Decimal("456")),
        ]

    def test_get_move(self, m_scan, book, journal):
        move = m_scan.get_move(path_1, dat_1)
        assert (move.book, move.journal, move.document.name) == (book, journal, str(path_1))
        assert move.date == dat_1["date"]
        assert move.reference == dat_1["reference"]
        assert move.label == dat_1["label"]


class TestJournalScan:
    def test_accounts(self, j_scan, account, accounts):
        assert j_scan.accounts == {account.short: account, **{a.code: a for a in accounts}}

    def test_get_lines(self, j_scan, move, accounts):
        lines = j_scan.get_lines(move, dat_1)

        for line, (key, amount) in zip(lines, dat_1["values"]):
            assert line.move == move
            assert line.account.code == key or line.account.short == key
            assert line.amount == amount


class TestMoveScenarioScan:
    def test_get_lines(self, mr_scan, move, accounts):
        lines = mr_scan.get_lines(move, dat_3)
        for line, (key, amount) in zip(lines, dat_3["values"]):
            assert line.move == move
            assert line.amount == amount


class TestBookScan:
    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_run(self, book, b_scan):
        b_scan.run()
        assert book.moves.all().count() == 2
        assert models.Line.objects.filter(move__book=book).count() == 6
