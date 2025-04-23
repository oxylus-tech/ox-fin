from decimal import Decimal

from fin import models


class TestAccount:
    def test_long_code(self):
        assert models.Account(code="12").long_code == "120000"


class TestMove:
    def test_full_reference(self, journal, move):
        assert move.full_reference == f"{journal.code}/{move.reference}"

    def test_clean(self, move, lines):
        # TODO: redo
        move.clean()


class TestLine:
    def test_is_debit(self, line):
        line.account.is_debit = True
        assert line.is_debit

    def test_is_debit_false(self, line):
        line.account.is_debit = True
        line.amount = Decimal("-10")
        assert not line.is_debit

    def test_clean(self, line):
        # TODO
        pass
