from __future__ import annotations
from decimal import Decimal
from functools import cached_property
import re

from django.db import models
from django.utils.translation import gettext_lazy as _


from .book import Book
from .utils import Described


__all__ = ("ReportTemplate", "ReportSection", "Report", "ReportSectionResult")


class ReportTemplate(Described):
    label = models.CharField(_("Label"), max_length=64)

    class Meta:
        verbose_name = _("Report Template")
        verbose_name_plural = _("Report Templates")


class ReportSection(models.Model):
    template = models.ForeignKey(
        ReportTemplate, models.CASCADE, related_name="sections", verbose_name=_("Report Template")
    )
    parent = models.ForeignKey(
        "self", models.CASCADE, verbose_name=_("Parent"), null=True, blank=True, related_name="children"
    )
    order = models.PositiveIntegerField(_("Order"))
    label = models.CharField(_("Label"), max_length=256)
    code = models.CharField(_("Code"), max_length=16, blank=True, null=True)
    weight = models.DecimalField(_("Weight"), default=Decimal("1"), decimal_places=2, max_digits=3)
    formula = models.CharField(_("Formula"), max_length=128)
    annexe = models.CharField(_("Annex"), max_length=16, blank=True, null=True)

    class Meta:
        verbose_name = _("Report Section")
        verbose_name_plural = _("Report Sections")

    _formula_re = re.compile("`([^`]+)`")
    _formula_sub = r"get_value('\1')"

    @cached_property
    def formula_code(self) -> str:
        """Parsed formula"""
        return self._formula_re.sub(self._formula_sub, self.formula)


class Report(models.Model):
    """Annual Report generated for a book"""

    template = models.ForeignKey(ReportTemplate, models.PROTECT, verbose_name=_("Template"))
    book = models.ForeignKey(Book, models.PROTECT, verbose_name=_("Ledger Book"))
    year = models.PositiveIntegerField(_("Year"))


class ReportSectionResult(models.Model):
    """Annual report section result."""

    report = models.ForeignKey(Report, models.CASCADE, verbose_name=_("Report"))
    section = models.ForeignKey(ReportSection, models.CASCADE, verbose_name=_("Section"))
    parent = models.ForeignKey("self", models.CASCADE, null=True, blank=True)
    value = models.DecimalField(_("Value"), max_digits=12, decimal_places=2)
