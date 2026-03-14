from datetime import date
from decimal import Decimal

import pandas as pd
from rich import print

from ..models import Book, Journal, Move, Line
from .base import BaseLoader


__all__ = ("BookSheetLoader",)


def as_date(val):
    year, month, day = val.split("/")
    return date(int(year), int(month.lstrip("0")), int(day.lstrip("0")))


def decimal(val):
    # val = val.replace('.', '').replace(',', '.')
    if not val:
        return None
    return round(Decimal(val), 2)


class BookSheetLoader(BaseLoader):
    """
    Import a book moves from an XLS or ODS sheet file
    """

    book: Book = None
    year: int = None
    journals: dict[str, Journal] = None

    columns = {
        "date": as_date,
        "account": str,
        "description": str,
        "debit": decimal,
        "credit": decimal,
        "contact": None,
        "reference": str,
    }

    def __init__(self, book, year=None):
        self.book = book
        self.year = year
        self.journals = {j.code: j for j in self.book.template.journals.all()}
        self.accounts = {j.code: j for j in self.book.template.accounts.all()}

    def load(self, path) -> list[tuple[Journal, pd.DataFrame]]:
        dfs = pd.read_excel(path, header=None, sheet_name=None, dtype=str)
        results = []
        for sheet_name, sheet in dfs.items():
            if journal := self.journals.get(sheet_name):
                results.append((journal, sheet))
        return results

    def get_items(self, schema, **_):
        moves, lines = [], []
        for journal, sheet in schema:
            j_moves, j_lines = self.read_journal(journal, sheet)
            moves.extend(j_moves)
            lines.extend(j_lines)
        return {"moves": moves, "lines": lines}

    def save(self, moves, lines):
        Move.objects.bulk_create(moves)
        Line.objects.bulk_create(lines)

    def clear(self, moves, lines):
        query = self.book.moves.all()
        if self.year:
            query = query.filter(date__year=self.year)
        query.delete()

    def read_journal(self, journal, df):
        """Read moves and lines from a dataframe."""
        move_values = []
        moves, lines = [], []

        print(f"Read [magenta]{journal.code}[/magenta] {journal.name}")

        for row in df.iloc[1:].itertuples(index=False, name=None):
            values = self.get_values(row)
            if not values:
                continue

            if values.get("date") and move_values:
                move, line = self.create_move(journal, move_values)
                moves.append(move)
                lines.extend(line)
                move_values = []
            move_values.append(values)

        if move_values and move_values[0].get("date"):
            move, line = self.create_move(journal, move_values)
            moves.append(move)
            lines.extend(line)

        print(f"- {len(moves)} moves and {len(lines)} lines read")
        return moves, lines

    def get_values(self, row):
        """Return values a row"""
        if len(row) < len(self.columns):
            print(f"[yellow][WARNING][/yellow]Row is missing {len(self.columns) - len(row)} columns")
            return

        values = {col: row[idx] for idx, col in enumerate(self.columns.keys()) if col}
        for key, ty in self.columns.items():
            if ty is not None:
                value = values.get(key)
                if value and pd.notna(value):
                    values[key] = ty(value)
                    continue
            values[key] = None

        if values.get("debit") is values.get("credit") is None:
            return None
        return values

    def create_move(self, journal, move_values):
        """Create a move and its lines for the provided values."""
        values = move_values[0]
        move = Move(
            book=self.book,
            journal=journal,
            date=values["date"],
            reference=values["reference"],
            description=values["description"],
        )

        lines = []
        for vals in move_values:
            code = vals.get("account")
            if not code:
                if any(v for v in vals.values()):
                    print(f"[yellow][{journal.code}/SKIP] no account provided: {vals}[/yellow]")
                continue

            account = self.get_account(code)
            if not account:
                print(f"[yellow][{journal.code}/SKIP] account {code} not found[/yellow]\n  {vals}")

            line = Line(
                move=move,
                account=account,
                amount=vals.get("debit") or vals.get("credit"),
                is_debit=bool(vals.get("debit")),
            )

            # print out:
            amount_str = str(line.amount).ljust(12, " ")
            if line.is_debit:
                amount_str = f"[green]+{amount_str}[/green]"
            else:
                amount_str = f"[red]-{amount_str}[/red]"

            lines.append(line)
        return move, lines

    def get_account(self, code, parent=True):
        """Get account by code, defaulting to parent if True."""
        while code:
            if account := self.accounts.get(code):
                return account
            elif not parent:
                break
            code = code[:-1]
