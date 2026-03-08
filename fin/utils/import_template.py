from decimal import Decimal
from pathlib import Path
from typing import Any

from django.db import transaction
from rich import print
import yaml

from .. import models


__all__ = ("BookTemplateImport", "ReportTemplateImport")


class BookTemplateImport:
    """Import a book template (update if required)."""

    @transaction.atomic
    def run(
        self, path: Path, template_id: int | None = None, clear=False
    ) -> tuple[models.BookTemplate, list[models.Account], list[models.Journal]]:
        """
        Run the import.

        :param path: path to file to import
        :param template: template id (if updating)
        :param clear: remove accounts and journals not present in the file.
        """

        with open(path) as s:
            data = yaml.load(s, Loader=yaml.SafeLoader)

        template = models.BookTemplate(
            pk=template_id,
            name=data["name"],
            description=data.get("description"),
        )
        template.save()

        # ---- accounts
        created, updated = self.get_accounts(template, data["accounts"])
        models.Account.objects.bulk_create(created)
        models.Account.objects.bulk_update(updated, ["name", "code", "type", "short"], batch_size=100)
        print(f"Accounts imported: {len(created)} created, {len(updated)} updated.")

        accounts = created + updated
        if template.pk and clear:
            ids = [o.id for o in accounts]
            q = models.Account.objects.filter(template=template).exclude(id__in=ids)
            print(f"Delete {len(q)} accounts.")
            q.delete()

        # ---- journals
        created, updated = self.get_journals(template, data["journals"])
        models.Journal.objects.bulk_create(created)
        models.Journal.objects.bulk_update(updated, ["name", "code"], batch_size=100)
        print(f"Journals imported: {len(created)} created, {len(updated)} updated.")

        journals = created + updated
        if template.pk and clear:
            ids = [o.id for o in journals]
            q = models.Journal.objects.filter(template=template).exclude(id__in=ids)
            print(f"Delete {len(q)} journals.")
            q.delete()

        return template, accounts, journals

    def get_accounts(self, template, data: list[dict[str, Any]]) -> tuple[list[models.Account], list[models.Account]]:
        """Return new and updated accounts from data (list of account kwargs)."""
        if template.pk:
            query = models.Account.objects.filter(template_id=template.pk).values_list("code", "id")
            in_db = dict(query)
        else:
            in_db = {}

        created, updated = [], []
        for dat in data:
            account = models.Account(
                pk=in_db.get(dat["code"]),
                template=template,
                name=dat["name"],
                code=dat["code"],
                type=dat["type"],
                short=dat.get("short"),
            )
            if account.pk:
                updated.append(account)
            else:
                created.append(account)
        return created, updated

    def get_journals(self, template, data: list[dict[str, Any]]) -> tuple[list[models.Journal], list[models.Journal]]:
        """Return new and updated journals from data (list of journal kwargs)."""
        if template.pk:
            query = models.Journal.objects.filter(template_id=template.pk).values_list("code", "id")
            in_db = dict(query)
        else:
            in_db = {}

        created, updated = [], []
        for dat in data["journals"]:
            journal = models.Journal(
                pk=in_db.get(dat["code"]),
                template=template,
                name=dat["name"],
                code=dat["code"],
            )
            if journal.pk:
                updated.append(journal)
            else:
                created.append(journal)
        return created, updated


class ReportTemplateImport:
    """Handle import of a report template from YAML file."""

    def run(
        self, path, template_id=None, save=False, clear=False
    ) -> tuple[models.ReportTemplate, list[models.ReportSection]]:
        with open(path) as s:
            data = yaml.load(s, Loader=yaml.SafeLoader)

        template = models.ReportTemplate(
            pk=template_id,
            name=data["name"],
            label=data["label"],
            description=data.get("description", ""),
        )
        sections, all_sections = self.get_sections(data["sections"], template)

        if save:
            template.save()
            if clear:
                template.sections.all().delete()

            for section in all_sections:
                section.save()
        return template, sections

    def get_sections(self, data, template, parent=None):
        items, flat = [], []
        for idx, dat in enumerate(data):
            section = models.ReportSection(
                template=template,
                parent=parent,
                order=idx,
                label=dat["label"],
                code=str(dat.get("code", "")),
                weight=dat.get("weight") and Decimal(dat.get("weight")) or Decimal("1"),
                formula=dat.get("formula", ""),
                annexe=dat.get("annexe"),
            )
            items.append(section)
            if sections := dat.get("sections"):
                section._sections, flat_ = self.get_sections(sections, template, section)
                flat += flat_
        return items, items + flat
