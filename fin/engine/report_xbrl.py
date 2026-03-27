from typing import Iterable

from django.template.loader import render_to_string

from ..models import Report, ReportSection, ReportTemplate
from ..schemas.xbrl import XBRLFact, XBRLContext, XBRLUnit, XBRLInstance


class XBRLReportBuilder:
    """
    Build an XBRL document instance based on the provided report.

    On the method going over the provided sections, we don't recurse in their
    inner children. Instead we assume that all sections are provided as
    input.
    """

    template_name = "ox/fin/xbrl/base.xbrl"

    def __init__(self, entity: str):
        self.entity = entity

    def render(self, instance: XBRLInstance, **kwargs) -> str:
        """Render XBRLInstance using django template into string."""
        kwargs["instance"] = instance
        return render_to_string(self.template_name, kwargs)

    def get_instance(self, report: Report, sections: Iterable[ReportSection] | None = None) -> XBRLInstance:
        """Return XBRLInstance from provided report."""
        schema = report.template.xbrl
        if schema is None:
            raise ValueError("This report can't be exported to an XBRL.")

        sections = sections or report.sections.all()
        facts = self.get_facts(sections)
        return XBRLInstance(
            schema_ref=schema.schema_ref,
            namespaces=schema.namespaces,
            entity_scheme=schema.entity_scheme,
            facts=facts,
            contexts=self.get_contexts(report, schema.contexts, facts),
            units=self.get_units(report.template, facts),
        )

    def get_facts(self, report: Report, sections: Iterable[ReportSection]) -> list[XBRLFact]:
        """Yield XBRLFact for all sections."""
        return [self.get_fact(section) for section in sections]

    def get_fact(self, report: Report, section: ReportSection) -> XBRLFact | None:
        """Return XBRLFact for the provided section."""
        if xbrl := section.template.xbrl:
            if section.template.previous_id:
                period_report, offset = report.previous, -1
            else:
                period_report, offset = report, 0

            if period_report is None:
                return

            if xbrl.period_type == "instant":
                kw = {"date": report.end_date}
            elif xbrl.period_type == "duration":
                kw = {"start_date": report.start_date, "end_date": report.end_date}

            return XBRLFact(
                concept=xbrl.concept,
                value=section.value,
                unit=xbrl.unit,
                period_type=xbrl.period_type,
                period_offset=offset,
                dimensions=xbrl.dimensions or {} ** kw,
            )

    def get_contexts(self, report: Report, contexts: list[XBRLContext], facts: Iterable[XBRLFact]) -> list[XBRLContext]:
        """
        Return only XBRLContext used for this report and mutate inplace their period according report's info.

        :yield ValueError: some facts are referencing a context that is not provided using ``contexts``.
        """
        contexts = {c.id for c in contexts}
        missings = [fact.concept for fact in facts if fact.context_id not in contexts]
        if missings:
            raise ValueError(f"Some fact are referencing non-declared context: {', '. join(missings)}.")

        c_report, c_offset, reports = report, 0, {}
        while c_report:
            key = (c_report.id, c_offset)
            reports[key] = c_report

            c_report = c_report.previous
            c_offset -= 1

        results = []
        for context in contexts.values():
            if context.period.type == "instant":
                context.period.instant = report.end_date
            else:
                context.period.start_date = report.start_date
                context.period.end_date = report.end_date
            results.append(context)
        return results

    def get_units(self, template: ReportTemplate, facts: Iterable[XBRLFact]) -> list[XBRLUnit]:
        """Return XBRLUnit from report template and check facts units.

        :yield ValueError: fact unit has not been declared in template's XBRL schema.
        """
        units = {u.id: u for u in template.xbrl.units}

        for fact in facts:
            if fact.unit not in units:
                raise ValueError(f"Fact unit {fact.unit} not declared in report template")
        return template.xbrl.units
