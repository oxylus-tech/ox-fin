from __future__ import annotations
from decimal import Decimal
from functools import cached_property
import re

from django.db import models
from django.utils.translation import gettext_lazy as _


from ..schemas.xbrl import XBRLFact, XBRLSchema
from .book import Book
from .utils import Described, Titled, Named, LongNamed, PydanticJSONField


__all__ = ("ReportTemplate", "ReportSectionTemplate", "Report", "ReportSection")


class ReportTemplate(Titled, Named, Described):
    """
    Template of a Report.

    It contains the whole sections tree, and is used to generate reports.
    The sections are associated to a code and can have a formula.
    """

    xbrl = PydanticJSONField(_("XBRL"), schema=XBRLSchema, blank=True, null=True)

    class Meta:
        verbose_name = _("Report Template")
        verbose_name_plural = _("Report Templates")

    def __str__(self):
        return f"Report Template: {self.label}"


class BaseReportSection(LongNamed):
    """Base class for a report section (template and result)."""

    parent = models.ForeignKey(
        "self", models.CASCADE, verbose_name=_("Parent"), null=True, blank=True, related_name="children"
    )
    order = models.PositiveIntegerField(_("Order"))
    code = models.CharField(_("Code"), max_length=16, blank=True, null=True)
    weight = models.DecimalField(_("Weight"), default=Decimal("1"), decimal_places=2, max_digits=3)

    class Meta:
        abstract = True

    def __str__(self):
        if self.code:
            return f"{self.code} {self.name}"
        return self.name


class ReportSectionTemplate(BaseReportSection):
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
    formula = models.CharField(_("Formula"), max_length=128, blank=True, null=True)
    annexe = models.CharField(_("Annexe"), max_length=16, blank=True, null=True)
    previous = models.ForeignKey(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Previous Section"),
        help_text=_("Get value from the section of the previous report."),
    )
    xbrl = PydanticJSONField(_("XBRL"), schema=XBRLFact, null=True, blank=True)

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
    """A Report generated for a book and template."""

    template = models.ForeignKey(ReportTemplate, models.PROTECT, verbose_name=_("Template"))
    previous = models.ForeignKey("self", models.PROTECT, null=True, blank=True, verbose_name=_("Previous Report"))
    book = models.ForeignKey(Book, models.PROTECT, verbose_name=_("Ledger Book"))
    start_date = models.DateField(_("Start Date"))
    end_date = models.DateField(_("End Date"))

    def __str__(self):
        return f"Report {self.book.name} - {self.year}"


# Note: we do a copy of the section template content to keep data consistent
# if the section template is deleted.
class ReportSection(BaseReportSection):
    """A Report section result."""

    report = models.ForeignKey(Report, models.CASCADE, related_name="sections", verbose_name=_("Report"))
    template = models.ForeignKey(ReportSectionTemplate, models.SET_NULL, null=True, verbose_name=_("Section"))
    value = models.DecimalField(_("Value"), max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Report Section {self.code}={self.value}"
