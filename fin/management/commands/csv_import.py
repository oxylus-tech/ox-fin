from pathlib import Path
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from fin import models
from fin.utils.csv_import import ModelCSVImport


class Command(BaseCommand):
    help = _("Import ledger informations from CSV file. The CSV must have a row specifying column names.")

    models = {
        "account": models.Account,
        "journal": models.Journal,
    }

    def add_arguments(self, parser):
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

    @staticmethod
    def parse_key_value(value):
        key, value = value.split("=", 1)
        value = value.strip()
        if value.isnumeric():
            value = int(value)
        return key.strip(), value

    def handle(self, *args, model, path, map, set, **kwargs):
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
