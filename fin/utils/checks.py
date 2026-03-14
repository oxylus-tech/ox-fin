from decimal import Decimal
from typing import Iterable

from rich import print

from .. import models


def check_lines_balance(lines: Iterable[models.Line]) -> Decimal | None:
    """Run balance check over lines."""

    print("Run checks...")
    by_move = {}
    debit, credit = Decimal("0"), Decimal("0")
    for line in lines:
        by_move.setdefault(line.move_id, []).append(line)
        debit += line.debit
        credit += line.credit

    if debit != credit:
        print(f"- [yellow]Debit != credit[/yellow] => {debit-credit}\n")
    else:
        print("Balance Debit == credit => return")

    print("Check move balances...")
    for move_lines in by_move.values():
        move = move_lines[0].move
        d = sum(line.debit for line in move_lines)
        c = sum(line.credit for line in move_lines)
        if d != c:
            print(
                f"- [yellow]{move.date}[/yellow] [magenta]{move.journal.code}[/magenta] {move.label}:"
                f" {d} != {c} => {d-c}"
            )
