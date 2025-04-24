import sys
import csv

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from fin import models


class Command(BaseCommand):
    help = _("Export ledger book to CSV")

    def add_arguments(self, parser):
        parser.add_argument("--book", "-b", type=int, help=_("Select a book"))
        parser.add_argument("--year", "-y", action="append", type=int, help=_("Select year"))

    def handle(self, *args, book, year=None, **kwargs):
        lines = models.Line.objects.filter(book_id=book).order_by("move__date", "move_id")

        if year:
            lines = lines.filter(move__date__year__in=year)

        lines = lines.select_related("account", "move", "move__journal")
        values = self.get_values()

        writer = csv.writer(sys.stdout, delimiter=";")
        writer.writerow(self.columns)
        for value in values:
            writer.writerow(value)

    columns = ("date", "journal", "account", "reference", "label", "amount", "debit", "credit", "file")

    def get_values(self, lines):
        for line in lines:
            move, journal, account = line.move, line.move.journal, line.account
            yield (
                move.date,
                journal.code,
                account.code,
                move.reference,
                move.label,
                line.amount,
                line.is_debit and line.amount or "",
                line.is_credit and line.amount or "",
                move.document.name,
            )
