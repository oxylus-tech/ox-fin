from __future__ import annotations
from decimal import Decimal
from functools import cached_property
import re

from django.db import models
from django.utils.translation import gettext_lazy as _


from .book import Book
from .utils import Described, Titled, LongNamed


__all__ = ("ReportTemplate", "ReportSection", "Report", "ReportSectionResult")


class ReportTemplate(Titled, Described):
    """
    Template of a Report.

    It contains the whole sections tree, and is used to generate reports.
    The sections are associated to a code and can have a formula.
    """

    class Meta:
        verbose_name = _("Report Template")
        verbose_name_plural = _("Report Templates")

    def __str__(self):
        return f"Report Template: {self.label}"


class ReportSection(LongNamed):
    """
    A section of the report template.

    Sections can be nested, and have a code. At report generation, we
    evaluate the section based on its parameters:

    - when a :py:attr:`formula` is provided, it will evaluate it.
    - else, it will use the :py:attr:`code` and nested children to get the balance.

    Code and formula
    ----------------

    The code of a section targets (by priority) another section or account(s).
    The `/` is used to specify a range of codes as ``512/43 == range(512, 543)``.

    Formula are limited python expression with syntax sugar for designating the value
    of one or more section/accounts. You can use backtits to specify them, as:

    .. code-block:: python

        `512/3` + `62` * 0.2

    """

    template = models.ForeignKey(
        ReportTemplate, models.CASCADE, related_name="sections", verbose_name=_("Report Template")
    )
    parent = models.ForeignKey(
        "self", models.CASCADE, verbose_name=_("Parent"), null=True, blank=True, related_name="children"
    )
    order = models.PositiveIntegerField(_("Order"))
    code = models.CharField(_("Code"), max_length=16, blank=True, null=True)
    weight = models.DecimalField(_("Weight"), default=Decimal("1"), decimal_places=2, max_digits=3)
    formula = models.CharField(_("Formula"), max_length=128, blank=True, null=True)
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

    def __str__(self):
        if self.code:
            return f"{self.code} {self.label}"
        return self.label


class Report(models.Model):
    """A Report generated for a book and template."""

    template = models.ForeignKey(ReportTemplate, models.PROTECT, verbose_name=_("Template"))
    book = models.ForeignKey(Book, models.PROTECT, verbose_name=_("Ledger Book"))
    year = models.PositiveIntegerField(_("Year"))

    def __str__(self):
        return f"Report {self.book.name} - {self.year}"


class ReportSectionResult(models.Model):
    """A Report section result."""

    report = models.ForeignKey(Report, models.CASCADE, verbose_name=_("Report"))
    section = models.ForeignKey(ReportSection, models.PROTECT, verbose_name=_("Section"))
    parent = models.ForeignKey("self", models.CASCADE, null=True, blank=True)
    value = models.DecimalField(_("Value"), max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Report Section {self.section}={self.value}"
