from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import cached_property
import re
from typing import Any

from django.conf import settings

from ..models import Account, Book, Journal, Move, Line, MoveRule


__all__ = ("JournalScan", "BookScan")


class MoveScan:
    """
    Base class to scan directory and generate move+lines based on
    file names.
    """

    reg = re.compile(
        r"^(?P<date>[0-9]{8})( - (?P<reference>[0-9]{7,9}))? - "
        r"(?P<label>[^0-9].+?)"
        r"( - (?P<values>([a-z0-9.:, -_]+)))?$"
    )
    exts = {
        "pdf",
        "doc",
        "odt",
        "docx",
        "png",
        "jpeg",
    }

    def __init__(self, book: Book, journal: Journal):
        self.book = book
        self.journal = journal

    def scan(self, path: Path, force: bool = False) -> tuple[list[Move], list[Line]]:
        """List files in directory, parse and return ."""
        moves, lines = [], []
        for path in self.iterdir(path, force):
            if dat := self.parse_path(path):
                move = self.get_move(path, dat)
                lines = move and self.get_lines(move, dat)

                move and moves.append(move)
                lines and lines.extend(lines)
        return moves, lines

    def iterdir(self, path, force: bool = False) -> list[Path]:
        """Return a list of file paths to scan inside directory.

        By default, it exclude thoses already associated with a Move.
        """
        paths = [p for p in path.iterdir() if p.is_file() and p.suffix[1:] in self.exts]
        if not force:
            paths = {str(p.relative_to(settings.MEDIA_ROOT)): p for p in paths}
            in_db = Move.objects.filter(document__in=paths.keys()).values_list("document", flat=True)
            paths = (p for r, p in paths.items() if r not in in_db)
        return list(paths)

    def parse_path(self, path: Path) -> dict[str, str] | None:
        """Parse the file name and return a dict of informations based on it."""
        m = self.reg.match(path.stem)
        dat = m and m.groupdict() or None
        if dat:
            dat.update(
                {
                    "date": datetime.strptime(dat["date"], "%Y%m%d").date(),
                    "values": list(self.parse_values(dat["values"])),
                }
            )
        return dat

    def parse_values(self, lines: str) -> dict[str, str]:
        """Read the lines part of the file name, returning values"""
        for item in lines.split(","):
            k, v = item.split(":")
            v = v.strip()
            try:
                v = Decimal(v)
            except InvalidOperation:
                pass
            yield (k.strip(), v)

    def get_move(self, path: Path, dat, **kwargs) -> Any | list[Any]:
        """Read a file name and generate Move and related lines."""
        return Move(
            book=self.book,
            journal=self.journal,
            document=str(path),
            date=dat["date"],
            reference=dat["reference"],
            label=dat["label"],
            **kwargs,
        )

    def get_lines(self, move: Move, dat: dict[str, Any], **kwargs) -> list[Line]:
        raise NotImplementedError("Not implemented")


class JournalScan(MoveScan):
    """Scan directory for a provided Journal and generate move+lines."""

    @cached_property
    def accounts(self) -> dict[str, Account]:
        """A dictionnary of Account by short name and code."""
        accounts = self.book.template.accounts.all()
        items = {a.code: a for a in accounts}
        items.update({a.short: a for a in accounts if a.short})
        return items

    def get_lines(self, move: Move, dat: dict[str, Any], **kwargs) -> list[Line]:
        """Read a file name and generate Move and related lines."""
        return [Line(move=move, account=self.accounts.get(key), amount=value, **kwargs) for key, value in dat["values"]]


class MoveRuleScan(MoveScan):
    """Scan directory for a provided MoveRule and generate move+lines."""

    def __init__(self, book: Book, move_rule: MoveRule):
        super().__init__(book, move_rule.journal)
        self.move_rule = move_rule

    def get_lines(self, move: Move, dat: dict[str, Any], **kwargs) -> list[Line]:
        return self.move_rule.get_lines(move, dat["values"])


class BookScan:
    def __init__(self, book):
        self.book = book

    def run(self):
        self.scan_journals()
        self.scan_move_rules()

    def scan_journals(self):
        moves, lines = [], []

        for journal in self.book.template.journals.all():
            scan = JournalScan(self.book, journal)
            result = scan.scan(Path(self.book.path) / journal.code)

            moves.extend(result[0])
            lines.extend(result[1])

        Move.objects.bulk_create(moves)
        Line.objects.bulk_create(lines)
        return moves, lines

    def scan_move_rules(self):
        moves, lines = [], []

        for move_rule in self.book.template.move_rules.all():
            scan = MoveRuleScan(self.book, move_rule)
            result = scan.scan(Path(self.book.path) / move_rule.code)

            moves.extend(result[0])
            lines.extend(result[1])

        Move.objects.bulk_create(moves)
        Line.objects.bulk_create(lines)
        return moves, lines
