from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from fin.models.book import Exercise, Move, Line


@pytest.fixture
def exercise(book, accounts):
    return book.get_exercise(date.today(), create=True)


@pytest.fixture
def next_exercise(book, exercise):
    return book.get_exercise(exercise.end_date + timedelta(days=1), create=True)


@pytest.fixture
def exercise_move(book, exercise, journal, accounts):
    exercise.open()

    move = Move.objects.create(book=book, exercise=exercise, journal=journal)
    Line.objects.bulk_create(
        [
            # REVENUE
            Line(move=move, account=accounts[0], amount=Decimal("100.0"), is_debit=True),
            # EXPENSE
            Line(move=move, account=accounts[4], amount=Decimal("60.0"), is_debit=True),
            # ASSET
            Line(move=move, account=accounts[-1], amount=Decimal("160.0"), is_debit=False),
        ]
    )
    return move


class TestBook:
    def test_get_exercise_create(self, book):
        exercise = book.get_exercise(date.today(), create=True)
        assert exercise.state == exercise.State.DRAFT

        assert book.get_exercise(date.today()) == exercise

        next_exercise = book.get_exercise(exercise.end_date + timedelta(days=4), create=True)
        assert next_exercise != exercise
        assert next_exercise.start_date == exercise.end_date + timedelta(days=1)

    def test_get_exercise_create_open(self, book):
        exercise = book.get_exercise(date.today(), create=True, open=True)
        assert exercise.state == exercise.State.OPEN
        assert exercise.opening_move is not None

    def test_get_exercise_no_create_raises_not_found(self, book):
        with pytest.raises(ValueError):
            book.get_exercise(date.today())


class TestExercise:
    def test_open(self, exercise):
        move = exercise.open()
        assert exercise.state == Exercise.State.OPEN
        assert exercise.opening_move == move
        assert move.exercise == exercise
        assert move.lines.all().exists()

        created = dict(move.lines.all().values_list("account_id", "amount"))
        for account_id in exercise.book.template.accounts.all().values_list("id", flat=True):
            assert created[account_id] == Decimal("0.00")

    def test_open_next_exercise(self, next_exercise, exercise_move, accounts):
        move = next_exercise.open()
        lines = move.lines.all()

        expected = {
            account_id: amount for account_id, amount in exercise_move.lines.all().values_list("account_id", "amount")
        }
        assert len(lines) >= len(expected)

        counter = 0
        for line in lines:
            if amount := expected.get(line.account_id):
                counter += 1
                assert line.amount == amount
        assert counter == len(expected)

    def test_close(self, exercise, exercise_move):
        move = exercise.close()

        assert exercise.state == Exercise.State.CLOSED
        assert move.exercise == exercise
        assert move.lines.all().exists()

        template = exercise.book.template
        retained_earnings = move.lines.filter(account_id=template.retained_earnings_account_id).first()

        assert retained_earnings.amount == Decimal("40")

    def test_reopen(self, exercise):
        raise NotImplementedError("todo")

    def test_validate_next_state(self, exercise):
        assert exercise.validate_next_state(Exercise.State.OPEN)
        assert not exercise.validate_next_state(Exercise.State.CLOSED, no_exc=True)

        with pytest.raises(ValidationError):
            exercise.validate_next_state(Exercise.State.CLOSED)

    def test_validate_move_type(self, exercise):
        assert exercise.validate_move_type(Move.Type.OPENING)
        assert not exercise.validate_move_type(Move.Type.NORMAL, no_exc=True)

        with pytest.raises(ValidationError):
            exercise.validate_move_type(Move.Type.NORMAL)
