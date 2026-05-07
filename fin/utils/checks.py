from decimal import Decimal
from typing import Iterable

from django.core.exceptions import ValidationError
from rich import print

from .. import models


def check_lines_balance(lines: Iterable[models.Line]) -> Decimal | None:
    """Run balance check over lines."""

    print("Run checks...")
    by_move = {}
    for line in lines:
        by_move.setdefault(line.move_id, []).append(line)

    print("Validate entries lines...")
    for move_lines in by_move.values():
        move = move_lines[0].move
        try:
            move.validate_lines(move_lines)
        except ValidationError as err:
            print(
                f"- Validation failed for [yellow]{move.date}[/yellow] [magenta]{move.journal.code}[/magenta] "
                f"{move.label}: {err}"
            )
