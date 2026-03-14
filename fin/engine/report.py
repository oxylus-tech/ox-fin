from dataclasses import dataclass, field
from decimal import Decimal

from fin.models import Book, Line
from fin.models.report import ReportTemplate, ReportSection, Report, ReportSectionResult

from fin.utils.eval import get_interpreter, Interpreter


__all__ = ("BuilderContext", "ReportBuilder")


@dataclass
class BuilderContext:
    lines: list[Line]
    interpreter: Interpreter | None = None
    cache: dict[int, Decimal] = field(default_factory=dict)


# TODO: Few rules here:
# - Avoid cyclic dependencies
class ReportBuilder:
    def __init__(self, template: ReportTemplate, book: Book):
        self.template = template
        self.sections = template.sections.all()
        self.sections_by_code = {s.code: s for s in self.sections}
        self.book = book

    def create(self, lines: list[Line], year) -> tuple[Report, dict[int, ReportSectionResult]]:
        """
        Create a new report for the provided lines.

        This is the entry point to generate and compute all the sections.

        :return: a tuple of Report and dict of ReportSectionResult (by section id).
        """
        # compute them all
        context = self.get_context(lines)
        for section in self.sections:
            self.compute_section(context, section)

        report = Report(template=self.template, book=self.book, year=year)

        # create results
        results = {}
        for section in self.sections:
            results[section.id] = ReportSectionResult(
                report=report, section=section, value=context.cache.get(section.code)
            )

        # second pass: parenting
        for result in results.values():
            if parent_id := result.section.parent_id:
                result.parent = results.get(parent_id)

        return report, results

    def get_context(self, lines) -> BuilderContext:
        """Return the builder's context for the provided lines."""
        context = BuilderContext(lines=lines)
        context.interpreter = self.get_interpreter(context)
        return context

    def get_interpreter(self, context: BuilderContext, **eval_context) -> Interpreter:
        """Initialize formula interpreter."""
        return get_interpreter(
            {
                **eval_context,
                "get_value": lambda code: self._eval_get_value(context, code),
            }
        )

    def compute_section(self, context: BuilderContext, section: ReportSection):
        """Compute a section's value."""
        if section.code in context.cache:
            return context.cache[section.code]

        if not section.code:
            return None

        value = Decimal("0")
        context.cache[section.code] = value  # avoid recursion

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
            breakpoint()
        context.cache[section.code] = value
        return value

    def _eval_get_value(self, context: BuilderContext, code):
        """Get value for the provided code (used by formula evaluation)."""
        try:
            if value := context.cache.get(code):
                return value
            elif ref := self.sections_by_code.get(code):
                # ReportSection
                return self.compute_section(context, ref)
            # Account
            return self.compute_lines(context.lines, code)
        except Exception:
            import traceback

            traceback.print_exc()

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
