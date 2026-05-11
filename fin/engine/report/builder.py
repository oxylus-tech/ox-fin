from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fin.models.book import LineQuerySet, Book
from fin.models.report import ReportTemplate, Report, ReportSection

from fin.utils.eval import get_interpreter, Interpreter

from ..ledger import LedgerStateView, LedgerFlowView
from .selector import Selector, LineQuery, SelectorParser
from .graph import Formula, Node, ReportGraph, NodeMethod


__all__ = ("BuilderContext", "ReportBuilder")


@dataclass
class BuilderContext:
    period: tuple[date, date]
    """ Report start and end date. """
    flow_view: LedgerFlowView
    """ """
    state_view: LedgerStateView

    previous: Report | None = None
    """ Previous report (as some values may be referring to it). """
    previous_sections: dict[str, ReportSection] = field(default_factory=dict)
    """ Relevant sections of the previous section's. """
    interpreter: Interpreter | None = None
    """ Formula interpreter """
    cache: dict[int, Decimal] = field(default_factory=dict)
    """ Result cache by section template pk. """
    lines_cache: dict[int, Decimal] = field(default_factory=dict)
    """ Result cache by section template pk. """


class ReportBuilder:
    selector_parser: SelectorParser
    nodes: ReportGraph

    def __init__(self, template: ReportTemplate, book: Book):
        self.template = template
        self.book = book
        self.selector_parser = SelectorParser(
            single_filters=LineQuery.single_filters,
            operators=LineQuery.operators,
        )
        self.nodes = ReportGraph(self.selector_parser)
        self.nodes.build(template)

    def build(
        self, lines: LineQuerySet, period: tuple[date, date], previous: Report | None = None
    ) -> tuple[Report, dict[int, ReportSection]]:
        out_of_range = lines.exclude(move__date__gte=period[0], move__date__lte=period[1])
        if out_of_range.exists():
            items = "\n".join(f"- {line}" for line in out_of_range)
            raise ValueError(f"Multiple lines are not in the period:\n{items}")

        report = Report(
            template=self.template,
            book=self.book,
            previous=previous,
            start_date=period[0],
            end_date=period[1],
        )

        self.line_query = LineQuery(lines)
        context = self.get_context(period, previous=previous)
        sections = {}
        for node in self.nodes.iter():
            result = self.compute_node(context, node)
            section = ReportSection(report=report, template_id=node.section_id, value=result)
            section._node = node
            sections[node.section_id] = section

        for node in self.nodes.iter():
            section = sections[node.section_id]
            if parent_id := node.parent_id:
                # FIXME here
                section.parent = sections.get(parent_id)

        return report, sections

    def get_context(self, period, previous=None, **kwargs) -> BuilderContext:
        """Return the builder's context for the provided lines."""
        context = BuilderContext(
            period=period,
            previous=previous,
            flow_view=LedgerFlowView(self.book, start_date=period[0], end_date=period[1]),
            state_view=LedgerFlowView(self.book, start_date=period[0], end_date=period[1]),
            **kwargs,
        )
        context.interpreter = self.get_interpreter(context)
        context.flow_query = LineQuery(context.flow_view.get_lines_queryset())
        context.state_query = LineQuery(context.state_view.get_lines_queryset())

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
                Formula._selector_func: lambda *args: self._eval_get_value(context, *args),
            }
        )

    def _eval_get_value(self, context: BuilderContext, node_key: int, key: int):
        """The method being called on back-bracket expression of a formula."""
        try:
            if key in context.cache:
                return context.cache[key]

            node = self.nodes[node_key]
            token = node.formula.selectors[key]
            if token.is_section:
                node = self.nodes[token]
                return self.compute_node(context, node)
            else:
                return self.compute_lines(context, token)
        except Exception:
            import traceback

            traceback.print_exc()
            raise

    def compute_node(self, context: BuilderContext, node: Node):
        """Compute a node value, fetching from or updating the cache."""
        if node.key in context.cache:
            return context.cache[node.key]

        match node.method:
            case NodeMethod.PREVIOUS:
                result = context.previous_sections.get(node.previous_id) or Decimal("0.")
            case NodeMethod.FORMULA:
                result = context.interpreter.eval(node.formula.expression)
                if context.interpreter.error:
                    section = self.nodes[node.key]
                    raise RuntimeError(
                        f"An error occured while evaluating: {section.expression}\n{context.interpreter.error}"
                    )
            case NodeMethod.LINES:
                token = self.selector_parser.parse("@" + node.code)
                result = self.compute_lines(context, token)
            case NodeMethod.DEPENDENCIES:
                try:
                    result = sum(context.cache[token.key] * self.nodes[token.key].weight for token in node.dependencies)
                except KeyError:
                    breakpoint()
            case _:
                result = Decimal("0.")

        context.cache[node.key] = Decimal(result).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return result

    def compute_lines(self, context: BuilderContext, token: Selector):
        """Compute lines for the provided token."""
        if token.key in context.lines_cache:
            return context.lines_cache[token.key]

        if token.scope == token.Scope.STATE:
            ledger_view = context.state_view
        else:
            ledger_view = context.flow_view

        line_query = LineQuery(ledger_view.qs)
        result = line_query.get_queryset(context, token)["total"] or Decimal("0.00")
        context.lines_cache[token.key] = result
        return result
