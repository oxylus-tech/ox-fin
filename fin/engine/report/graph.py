from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from graphlib import TopologicalSorter
import re
from typing import Generator


from fin.models import ReportTemplate
from .selector import Selector, SelectorFormatError, SelectorParser


@dataclass(frozen=True)
class Formula:
    """A formula compiled from a report section."""

    expression: str
    """ The compiled python expression to evaluate. """
    selectors: dict[str, Selector]
    """ The list of extracted selectors. """

    _selector_re = re.compile(r"`([^`]+)`")
    _selector_func = "get_value"

    @classmethod
    def compile(cls, parser: SelectorParser, parent: Selector, expr: str) -> Formula:
        """
        Compile a formula and extract relevant data returning a new instance of Formula.

        This ensures to provide a python expression that will fetch the relevant data.

        :param parser: selector expression parser
        :param parent: parent section selector
        :param expr: the formula to compile.
        :raises SelectorFormatError: one or more selectors are wrong.
        """
        selectors = {}
        wrongs = []

        def replace(mat):
            raw = mat.group(1)
            try:
                token = parser.parse(raw)
            except SelectorFormatError:
                wrongs.append(raw)

            key = token.key
            selectors[key] = token
            return f"{cls._selector_func}({parent.key}, {key})"

        new_expr = cls._selector_re.sub(replace, expr)
        if wrongs:
            raise SelectorFormatError(f"Multiple selectors are not correct: {(', ').join(wrongs)}")

        return Formula(
            expression=new_expr,
            selectors=selectors,
        )


class NodeMethod(Enum):
    NONE = 0x00
    LINES = 0x01
    FORMULA = 0x02
    DEPENDENCIES = 0x03
    PREVIOUS = 0x04


@dataclass(frozen=True)
class Node:
    token: Selector
    method: NodeMethod

    section_id: int | None = None
    parent_id: int | None = None

    previous_id: int | None = None
    weight: Decimal = Decimal("1.")
    formula: Formula | None = None
    dependencies: set[Selector] = field(default_factory=set)

    @classmethod
    def from_section(cls, section, *args, **kwargs):
        """New node for the provided section."""
        return cls(*args, section_id=section.id, parent_id=section.parent_id, weight=section.weight, **kwargs)

    @property
    def key(self) -> int:
        """Token hash key."""
        if self.token.code.value is None:
            return hash(("section_id", self.section_id))
        return self.token.key

    @property
    def code(self) -> str:
        """Node code string."""
        code = self.token.code.value
        if isinstance(code, str) and code.startswith("#"):
            return code[1:]
        return code


class ReportGraph:
    """
    Dependency and execution graph based on provided sections.

    .. important::

        Only sections with a code will be added to the graph.
    """

    items: dict[int, Node] = field(default_factory=dict)

    def __init__(self, selector_parser):
        self.selector_parser = selector_parser

    def build(self, template: ReportTemplate):
        """Initialize the graph."""
        items = {}

        # run over all sections of a report
        for section in template.sections.all().order_by("order"):
            if node := self.get_section_node(section):
                items[node.key] = node

        self.items = items
        return items

    def iter(self) -> Generator[Node, None]:
        """Iter over graph in topological order."""
        sorter = TopologicalSorter()

        for node in self.items.values():
            sorter.add(node.token, *node.dependencies)

        for token in sorter.static_order():
            if token.is_section:
                try:
                    yield self.items[token.key]
                except KeyError:
                    breakpoint()

    def get_section_node(self, section):
        token = Selector.from_section(section.code)

        kw = {}
        if section.previous_id:
            method = NodeMethod.PREVIOUS
            kw["previous_id"] = section.previous_id
        elif section.formula:
            method = NodeMethod.FORMULA
            formula = Formula.compile(self.selector_parser, token, section.formula)
            deps = set(token for token in formula.selectors.values() if token.is_section)
            kw.update({"formula": formula, "dependencies": deps})
        elif children := section.children.all().values_list("code", flat=True):
            method = NodeMethod.DEPENDENCIES
            kw["dependencies"] = set(Selector.from_section(code) for code in children)
        elif isinstance(token.code.value, str):
            method = NodeMethod.LINES
        else:
            method = NodeMethod.NONE

        return Node.from_section(section, token=token, method=method, **kw)

    def __getitem__(self, key: int | Selector):
        """Return node for the provided key."""
        if isinstance(key, Selector):
            key = key.key
        return self.items[key]
