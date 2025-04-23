from datetime import datetime
from decimal import Decimal
from pathlib import Path
from functools import cached_property
import re

from django.conf import settings

from ..models import Account, Book, Journal, Move, Line


__all__ = ("JournalScanner", "BookScanner")


class JournalScanner:
    """Scan directory for a provided journal and generate related lines in the book."""

    reg = re.compile(
        r"^(?P<date>[0-9]{8})( - (?P<reference>[0-9]{7,9}))? - "
        # r"((?P<contact>[^-]*?) - )?"
        r"(?P<label>[^0-9].+?)"
        r"( - (?P<lines>([a-z0-9.:, -]+)))?$"
    )
    exts = {
        "pdf",
        "doc",
        "odt",
        "docx",
        "png",
        "jpeg",
    }

    def __init__(self, journal: Journal, path: Path):
        self.journal = journal
        self.path = path

    @cached_property
    def accounts(self) -> dict[str, Account]:
        """A dictionnary of Account by short name and code."""
        accounts = self.journal.template.accounts.all()
        items = {a.code: a for a in accounts}
        items.update({a.short: a for a in accounts if a.short})
        return items

    def run(self, book: Book) -> tuple[list[Move], list[Line]]:
        """Run scan, listing file and match lines."""
        moves, lines = [], []

        for path in self.path.iterdir():
            if not path.is_file() or path.suffix[1:] not in self.exts:
                continue

            if result := self.get_move(book, path):
                moves.append(result[0])
                lines.extend(result[1])

        return moves, lines

    def get_move(self, book: Book, path: Path, force: bool = False) -> None | tuple[Move, list[Line]]:
        """Read a file name and generate Move and related lines."""
        lookup = path.relative_to(settings.MEDIA_ROOT)
        if not force and Move.objects.filter(document=str(lookup)):
            return

        if dat := self.parse_filename(path.stem):
            move = Move(
                book=book,
                journal=self.journal,
                document=str(path),
                date=dat["date"],
                reference=dat["reference"],
                label=dat["label"],
            )
            lines = [
                Line(
                    move=move,
                    account=self.accounts.get(key),
                    amount=Decimal(value),
                )
                for key, value in dat["lines"]
            ]
            return move, lines

    def parse_filename(self, filename: str) -> dict[str, str] | None:
        """Parse the file name and return a dict of informations based on it."""
        m = self.reg.match(filename)
        dat = m and m.groupdict() or None
        if dat:
            dat.update(
                {"date": datetime.strptime(dat["date"], "%Y%m%d").date(), "lines": list(self.read_lines(dat["lines"]))}
            )
        return dat

    def read_lines(self, lines: str) -> dict[str, str]:
        """Read the lines part of the file name, returning values"""
        for item in lines.split(","):
            k, v = item.split(":")
            yield (k.strip(), v.strip())


class BookScanner:
    def __init__(self, book):
        self.book = book

    def run(self):
        moves, lines = [], []

        for journal in self.book.template.journals.all():
            scanner = JournalScanner(journal, Path(self.book.path) / journal.code)
            result = scanner.run(self.book)

            moves.extend(result[0])
            lines.extend(result[1])

        Move.objects.bulk_create(moves)
        Line.objects.bulk_create(lines)
        return moves, lines
