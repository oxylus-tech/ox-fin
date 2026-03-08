import csv
import logging
from pathlib import Path
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from fin import models
from fin.utils.csv_import import ModelCSVImport
from fin.utils.dir_scan import BookScan


class Command(BaseCommand):
    help = _("Ledger book management")

    models = {
        "account": models.Account,
        "journal": models.Journal,
    }

    @staticmethod
    def parse_key_value(value):
        key, value = value.split("=", 1)
        value = value.strip()
        if value.isnumeric():
            value = int(value)
        return key.strip(), value

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers()

        # --- CSV export
        subparser = subparsers.add_parser("csv-export", help=_("Export ledger book to CSV"))
        subparser.set_defaults(func=self.handle_export)
        subparser.add_argument("book", metavar="BOOK", type=int, help=_("Select a book"))
        subparser.add_argument("--year", "-y", action="append", type=int, help=_("Select year"))

        # --- CSV import
        subparser = subparser.add_parser(
            "csv-import",
            help=_("Import ledger informations from CSV file. The CSV must have a row specifying column names."),
        )
        subparser.set_defaults(func=self.handle_import)
        parser.add_argument("model", metavar=_("MODEL"), choices=self.models.keys())
        parser.add_argument("path", metavar=_("PATH"), type=Path, nargs="+")

        parser.add_argument(
            "--map", "-m", action="append", type=self.parse_key_value, help=_("Map column to field name")
        )
        parser.add_argument(
            "--set",
            "-s",
            action="append",
            type=self.parse_key_value,
            help=_("Initial argument to all object instances."),
        )

        # --- Book scan
        subparser = subparsers.add_parser("dir-scan", help=_("Scan book directory for new moves."))
        subparser.set_defaults(func=self.handle_dir_scan)
        subparser.add_argument(
            "--book", "-b", type=int, action="append", help=_("Select a book by id (default: all books are selected)")
        )

    def handle(self, func, **kwargs):
        return func(**kwargs)

    # --- Book dir scan
    def handle_dir_scan(self, *args, book=None, **kwargs):
        books = models.Book.objects.all()
        if book:
            books = books.filter(id__in=book)

        for book in books:
            print(f">>> Scan book {book}")
            BookScan(book).run()

    # --- CSV export
    def handle_export(self, *args, book, year=None, **kwargs):
        lines = models.Line.objects.filter(book_id=book).order_by("move__date", "move_id")

        if year:
            lines = lines.filter(move__date__year__in=year)

        lines = lines.select_related("account", "move", "move__journal")
        values = self.get_export_values()

        writer = csv.writer(sys.stdout, delimiter=";")
        writer.writerow(self.export_columns)
        for value in values:
            writer.writerow(value)

    export_columns = ("date", "journal", "account", "reference", "label", "amount", "debit", "credit", "file")

    def get_export_values(self, lines):
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

    # --- CSV import
    def handle_import(self, *args, model, path, map, set, **kwargs):
        model = self.models[model]
        csv_import = ModelCSVImport(model, dict(set), map and dict(map))
        for path_ in path:
            try:
                logging.info(f"Start import from: {path_}")
                objs = csv_import.run(path_)
                logging.info(f"Imported {len(objs)} {model._meta.verbose_name}")
            except Exception as err:
                if settings.DEBUG:
                    import traceback

                    traceback.print_exc()

                logging.error(f"An error occured while importing from {path_}: {err}")
        logging.info("Done!")
