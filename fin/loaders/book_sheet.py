from datetime import date
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd
from rich import print

from ..models import ProrataPolicy, Book, Journal, Move, Line, FixedAsset, AmortizationSchedule
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
        "entry": str,
        "type": str,
        "value": decimal,
        "amort_end": as_date,
        "amort_freq": str,
        "amort_pro": str,
    }
    entry_columns = {"date", "account", "description", "debit", "credit", "contact", "reference"}
    asset_columns = {
        "date",
        "reference",
        "account",
        "entry",
        "type",
        "description",
        "value",
        "amort_end",
        "amort_freq",
        "amort_pro",
    }

    mapping = {
        "date": "date",
        "description": "description",
        "debit": "debit",
        "credit": "credit",
        "reference": "reference",
        "type": "type",
        "value": "value",
        "tangible": "tangible",
        "intangible": "intangible",
        "financial": "financial",
        "entry": "entry",
        "amort_end": "amort_end",
        "amort_freq": "amort_freq",
        "amort_pro": "amort_pro",
        "monthly": "monthly",
        "quarterly": "quarterly",
        "annual": "annual",
        "none": "none",
        "daily": "daily",
    }
    """ Label mapping to programmatic names. """

    def __init__(self, book, year=None):
        self.book = book
        self.year = year
        self.journals = {j.code: j for j in self.book.template.journals.all()}
        self.accounts = {j.code: j for j in self.book.template.accounts.all()}

    def load(self, path) -> list[tuple[Journal, pd.DataFrame]]:
        dfs = pd.read_excel(path, header=None, sheet_name=None, dtype=str)
        results = []

        sheet = dfs.get("Mapping")
        if sheet is not None:
            self.get_mapping(sheet)

        for sheet_name, sheet in dfs.items():
            if journal := self.journals.get(sheet_name):
                results.append((journal, sheet))

        return {"journals": results, "assets": dfs.get("Assets")}

    def get_items(self, schema, **_):
        moves, lines = [], []
        for journal, sheet in schema["journals"]:
            j_moves, j_lines = self.read_journal(journal, sheet)
            moves.extend(j_moves)
            lines.extend(j_lines)

        sheet = schema["assets"]
        if sheet is not None:
            assets, schedules = self.read_assets(sheet, moves)

        return {"moves": moves, "lines": lines, "assets": assets, "schedules": schedules}

    def save(self, moves, lines, assets, schedules):
        Move.objects.bulk_create(moves)
        Line.objects.bulk_create(lines)

        assets and FixedAsset.objects.bulk_create(assets)
        schedules and AmortizationSchedule.objects.bulk_create(schedules)

    def clear(self, **kw):
        query = self.book.moves.all()
        if self.year:
            query = query.filter(date__year=self.year)
        query.delete()

        query = self.book.fixed_assets.all()
        if self.year:
            query = query.filter(date__year=self.year)
        query.delete()

    # ---- Mapping & values
    def get_mapping(self, df):
        mapping = {}
        for row in df.iloc[0:].itertuples(index=False, name=None):
            mapping[row[1]] = row[0]
        self.mapping = {
            **(type(self).mapping),
            **mapping,
        }

    def get_values(self, row, columns, required: Iterable[str] | None = None) -> dict[str, Any] | None:
        """
        Return a dictionary of internal values from a row.

        :param row: pandas DF row
        :param column: a list of internal column names already mapped
        :param required: required field values (if not provided on sheet, return None)
        """
        if len(row) < len(columns):
            print(f"[yellow][WARNING][/yellow]Row is missing {len(columns) - len(row)} columns")
            return None

        values = {}
        for val, col in zip(row, columns):
            if not col:
                continue
            ty = self.columns.get(col)
            if ty and pd.notna(val):
                try:
                    val = ty(val)
                except Exception as e:
                    print(f"[yellow][WARNING][/yellow]Cannot convert {val} to {ty}: {e}")
                    val = None
            else:
                val = None
            values[col] = val

        if required and any(True for k in required if values.get(k) is None):
            return None

        return values

    # ---- Journal & entries
    def read_journal(self, journal, df):
        """Read moves and lines from a dataframe."""
        print(f"Read [magenta]{journal.code}[/magenta] {journal.name}")

        columns = [self.mapping.get(v) for v in df.iloc[0].tolist()]
        if missings := [c for c in self.entry_columns if c not in columns]:
            raise ValueError(f"There are missing columns for journal {journal.code}:" + ", ".join(missings))

        move_values = []
        moves, lines = [], []

        for row in df.iloc[1:].itertuples(index=False, name=None):
            values = self.get_values(row, columns)
            if not values or (not values.get("debit") and not values.get("credit")):
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

    # Assets & amortizations
    def read_assets(self, df, moves):
        """Read assets."""
        print("Read [magenta]assets[/magenta]")

        columns = [self.mapping.get(v) for v in df.iloc[0].tolist()]
        # if missings := [c for c in self.asset_columns if c not in columns]:
        #    raise ValueError("There are missing columns for assets:" + ", ".join(missings))
        columns = [c for c in columns if c in self.asset_columns]

        assets, schedules = [], []
        for row in df.iloc[1:].itertuples(index=False, name=None):
            values = self.get_values(row, columns, ("entry", "account", "type", "description", "value"))
            if not values:
                print(f"[yellow]Skip asset row (missing data): {row}[/yellow]")
                continue

            ref = values["reference"]
            print(f"- Read asset [magenta]{ref}[/magenta]")
            move = next((m for m in moves if m.reference == values["entry"]), None)
            if not move:
                raise ValueError(f"Journal entry {values['entry']} not found")

            asset_date = values.get("date", move.date)
            if "date" in values:
                if values["date"] < move.date:
                    raise ValueError("Asset has his date before its entry.")
                if values["date"].year != move.date.year:
                    raise ValueError("Asset's date is not on the same year as the related entry")

            type = self.mapping[values["type"]]
            asset = FixedAsset(
                book=self.book,
                move=move,
                account=self.get_account(values["account"]),
                reference=ref,
                description=values["description"],
                type=getattr(FixedAsset.Type, type.upper()),
                date=asset_date,
                initial_value=values["value"],
            )

            assets.append(asset)

            if amort_end := values.get("amort_end"):
                schedule = AmortizationSchedule(
                    asset=asset,
                    start_date=asset.date,
                    end_date=amort_end,
                )
                if freq := values.get("amort_freq"):
                    freq = self.mapping[freq].upper()
                    schedule.frequency = getattr(AmortizationSchedule.Frequency, freq)
                if pro := values.get("amort_pro"):
                    pro = self.mapping[pro].upper()
                    schedule.prorata = getattr(ProrataPolicy, pro)

                schedules.append(schedule)

        print(f"- {len(assets)} assets and {len(schedules)} schedules read")
        return assets, schedules
