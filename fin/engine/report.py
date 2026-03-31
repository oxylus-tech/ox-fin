from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fin.models import Book, Line
from fin.models.report import ReportTemplate, ReportSectionTemplate, Report, ReportSection

from fin.utils.eval import get_interpreter, Interpreter


__all__ = ("BuilderContext", "ReportBuilder")


@dataclass
class BuilderContext:
    lines: list[Line]
    """ Book lines to use for the report. """
    previous: Report | None = None
    """ Previous report (as some values may be referring to it). """
    previous_sections: dict[str, ReportSection] = field(default_factory=dict)
    """ Relevant sections of the previous section's. """
    interpreter: Interpreter | None = None
    """ Formula interpreter """
    cache: dict[int, Decimal] = field(default_factory=dict)
    """ Result cache by section template pk. """


# TODO: Few rules here:
# - Avoid cyclic dependencies
class ReportBuilder:
    def __init__(self, template: ReportTemplate, book: Book):
        self.template = template
        self.sections = template.sections.all()
        self.sections_by_code = {s.code: s for s in self.sections}
        self.book = book

    def build(
        self, lines: list[Line], period: tuple[date, date], previous: Report | None = None
    ) -> tuple[Report, dict[int, ReportSection]]:
        """
        Create a new report for the provided lines.

        This is the entry point to generate and compute all the sections.

        :param lines: the lines to scan (must be in the provided period)
        :param period: start-end of the period
        :param previous: previous report if any

        :return: a tuple of Report and dict of ReportSection (by section id).
        """
        start_date, end_date = period
        out_of_range = [line for line in lines if line.move.date < start_date or line.move.date > end_date]
        if out_of_range:
            items = "\n".join(f"- {line}" for line in out_of_range)
            raise ValueError(f"Multiple lines are not in the period:\n{items}")

        # compute them all
        context = self.get_context(lines, previous=previous)
        for section in self.sections:
            self.compute_section(context, section)

        report = Report(
            template=self.template,
            book=self.book,
            previous=previous,
            start_date=period[0],
            end_date=period[1],
        )

        # create results
        results = {}
        for section in self.sections:
            results[section.id] = ReportSection(report=report, template=section, value=context.cache.get(section.code))

        # second pass: parenting
        for result in results.values():
            if parent_id := result.template.parent_id:
                result.parent = results.get(parent_id)

        return report, results

    def get_context(self, lines, previous=None, **kwargs) -> BuilderContext:
        """Return the builder's context for the provided lines."""
        context = BuilderContext(lines=lines, previous=previous, **kwargs)
        context.interpreter = self.get_interpreter(context)

        if previous:
            p_sections_templates = self.template.sections.filter(previous__isnull=False)
            context.previous_sections = dict(
                previous.sections.filter(template__in=p_sections_templates).values_list("pk", "value")
            )
        return context

    def get_interpreter(self, context: BuilderContext, **eval_context) -> Interpreter:
        """Initialize formula interpreter."""
        return get_interpreter(
            {
                **eval_context,
                "get_value": lambda code: self._eval_get_value(context, code),
            }
        )

    def compute_section(self, context: BuilderContext, section: ReportSectionTemplate):
        """Compute a section's value."""
        if section.code in context.cache:
            return context.cache[section.code]

        if not section.code:
            return None

        value = Decimal("0")
        context.cache[section.code] = value  # avoid recursion

        # Case 0 --- previous report section value
        if section.previous_id:
            value = context.previous_sections.get(section.previous_id) or Decimal("0.")
        # Case 1 --- Formula
        if section.formula:
            value = context.interpreter.eval(section.formula_code)
        else:
            # Case 2 --- Children sections
            children = section.children.all()
            if children.exists():
                for child in children:
                    child_value = self.compute_section(context, child)
                    value += child_value * child.weight
            # Case 3 --- From transaction lines
            else:
                value = self.compute_lines(context.lines, section.code)

        if value is None:
            # FIXME set value to 0.0 or raise?
            return None
        context.cache[section.code] = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return value

    def _eval_get_value(self, context: BuilderContext, code):
        """Get value for the provided code (used by formula evaluation)."""
        try:
            if not code.startswith("#"):
                if value := context.cache.get(code):
                    return value
                elif ref := self.sections_by_code.get(code):
                    # ReportSection
                    return self.compute_section(context, ref)
            else:
                code = code[1:]
            # Account
            return self.compute_lines(context.lines, code)
        except Exception:
            import traceback

            traceback.print_exc()
            raise

    def compute_lines(self, lines: list[Line], prefix):
        """Sum lines for the provided section prefix."""
        codes = parse_code_pattern(prefix)
        if not codes:
            return Decimal("0")

        code_len = len(next(iter(codes)))
        return sum(line.norm_amount for line in lines if line.account.code[:code_len] in codes)


def parse_code_pattern(pattern) -> set[str]:
    """From code pattern return a set of codes."""
    if "/" not in pattern:
        return {pattern}

    start, end = pattern.split("/")
    prefix = start[: -len(end)]
    istart = int(start[-len(end) :])
    iend = int(end)
    return {f"{prefix}{i}" for i in range(istart, iend + 1)}
