from dataclasses import dataclass
from enum import Enum
from functools import reduce, cached_property
import re
from typing import Literal, Iterable


from django.db.models import Sum, Max, Min, Q

from fin.models.book import LineQuerySet


__all__ = ("CodeToken", "FilterToken", "Selector", "SelectorFormatError", "SelectorParser", "LineQueryBuilder")


CodeKind = Literal["range", "list", "single"]
CodeValue = str | tuple[str, str] | list[str]
FilterValue = str | None


@dataclass
class CodeToken:
    value: CodeValue
    kind: CodeKind = "single"

    def __hash__(self):
        value = tuple(self.value) if isinstance(self.value, list) else self.value
        return hash((self.kind, value))

    def to_string(self):
        match self.kind:
            case "single":
                return self.value
            case "range":
                return "/".join(self.value)
            case "list":
                return ",".join(self.value)

    def as_list(self) -> list[str] | set[str]:
        """From code return a list or set of codes."""
        if isinstance(self.value, str):
            return [self.value]
        if isinstance(self.value, list):
            return self.value

        start, end = self.value
        prefix = start[: -len(end)]
        istart = int(start[-len(end) :])
        iend = int(end)
        if iend < istart:
            return {start}
        return {f"{prefix}{i}" for i in range(istart, iend + 1)}


@dataclass
class FilterToken:
    tag: str
    op: str | None = None
    value: FilterValue = None

    def __hash__(self):
        return hash((self.tag, self.op, self.value))


@dataclass(frozen=True)
class Selector:
    class Scope(Enum):
        LINES = 0x00
        SECTION = 0x01

    scope: Scope
    code: CodeToken
    aggr: str | None = None
    filters: tuple[FilterToken] | None = None

    @classmethod
    def from_section(cls, code: str):
        return cls(scope=cls.Scope.SECTION, code=CodeToken(value=code))

    @cached_property
    def key(self):
        return hash((self.scope, self.code, self.aggr, self.filters))

    @property
    def is_section(self):
        return self.scope == self.Scope.SECTION

    @property
    def is_lines(self):
        return self.scope == self.Scope.LINES

    def __hash__(self):
        return self.key


class SelectorFormatError(ValueError):
    """This exception is raised when a selector have a wrong format."""

    pass


class SelectorParser:
    """
    Parse multiple selectors, caching already parsed expression.

    Example expressions:

    ..code-block::

        # Select lines for account range 230-241
        @230/41

        # Select lines for accounts 230, 240, 250
        @230,240,250

        # Select credit lines for account 240, with counterpart in 2
        @240|credit|counterpart:2

        # Select credit lines for account 240, with counterpart not in 2
        @240|credit|counterpart!:2

        # Select section '12/34P'
        #12/34P

        # Aggregate using 'max' function (account range 230/240, debit)
        max:@230/240|debit

    """

    single_filters: set[str]
    """ Filter tags not requiring operator (as ``debit``, ``credit``). """
    operators: list[str]
    """ Operators lookup for filters as an ordered list.

    .. important::

        They are detected using the python "in" operator, so if required, add
        spaces around the required operator.
    """
    default_aggr = "sum"
    """ Default aggregation function. """

    section_re = re.compile(r"^#?(?P<code>[0-9a-zA-Z/,_:-]+)?$")
    lines_re = re.compile(r"^(?:(?P<aggr>[a-zA-Z]+):)? *" r"@(?P<code>[0-9/,]+) *" r"(?:\|(?P<filters>.+))?$")

    def __init__(self, single_filters: Iterable[str], operators: list[str], default_aggr: str = "sum"):
        self.single_filters = set(single_filters)
        self.operators = sorted(operators, key=len, reverse=True)
        self.default_aggr = default_aggr or self.default_aggr
        # Cache is per instance, to keep memory low after usage.
        self.cache = {}

    def parse(self, expr: str) -> Selector | None:
        """Parse an expression into a selector"""
        expr = expr.strip()
        if not expr:
            return None

        key = hash(" ".join(expr.split()))
        if key in self.cache:
            return self.cache[key]

        if mat := self.lines_re.match(expr):
            token = self.parse_line(mat)
        elif mat := self.section_re.match(expr):
            token = self.parse_section(mat)
        else:
            raise SelectorFormatError(f"Invalid expression: {expr}")
        self.cache[key] = token
        return token

    def parse_section(self, mat):
        return Selector(
            scope=Selector.Scope.SECTION,
            code=self.parse_code(mat.group("code"), True),
        )

    def parse_line(self, mat):
        code = mat.group("code")
        filters = mat.group("filters")
        return Selector(
            aggr=mat.group("aggr") or self.default_aggr,
            scope=Selector.Scope.LINES,
            code=self.parse_code(code),
            filters=self.parse_filters(filters),
        )

    def parse_code(self, raw: str, is_section: bool = False) -> CodeToken:
        if not is_section:
            if "," in raw:
                return CodeToken(kind="list", value=[x.strip() for x in raw.split(",")])
            if "/" in raw:
                a, b = raw.split("/")
                return CodeToken(kind="range", value=(a.strip(), b.strip()))
        return CodeToken(kind="single", value=raw.strip())

    def parse_filters(self, raw: str | None) -> list[FilterToken]:
        if not raw:
            return tuple()

        parts = raw.split("|")
        filters = []

        for p in parts:
            p = p.strip()

            if p in self.single_filters:
                filter = FilterToken(tag=p)
            elif op := self.detect_op(p):
                k, v = p.split(op, 1)
                filter = FilterToken(tag=k.strip(), op=op, value=v.strip())
            else:
                raise ValueError(f"Invalid filter: {p}")

            filters.append(filter)
        return tuple(filters)

    def detect_op(self, p: str):
        """ """
        for op in self.operators:
            if op in p:
                return op
        return None


class LineQueryBuilder:
    """This class allows to transform a selector token into queryset (for lines)."""

    single_filters: set[str] = {"debit", "credit", "movement", "opening", "closing", "balance"}
    filters = "counterpart"
    operators = {
        ":": "__startswith",
        "!:": "__startswith",
        "=": "",
        "!=": "",
    }
    """ Operators and lookup. It is assumed that an operator starting with "!" means excluding instead of filter. """
    aggregates = {"sum": Sum, "max": Max, "min": Min}
    """ Aggregation functions. """

    def __init__(self, qs: LineQuerySet):
        self.qs = qs.with_norm_amount()

    def get_queryset(self, context, selector: Selector, aggregate: bool = True):
        """Return queryset constructor on the selector.

        :raises SelectorFormatError: invalid input format for a selector.
        """
        assert selector.is_lines

        qs = self.apply_code(selector.code, self.qs)
        qs = self.apply_filters(context, selector.filters, qs)
        if aggregate:
            qs = self.apply_aggregate(selector.aggr, qs)
        return qs

    def apply_aggregate(self, aggr: str, qs: LineQuerySet, key: str = "total"):
        """Apply aggregation function."""
        if func := self.aggregates.get(aggr):
            return qs.aggregate(**{key: func("norm_amount")})
        raise ValueError(f"Unknown aggregate function {aggr}")

    def apply_code(self, code: CodeToken, qs: LineQuerySet):
        """Apply scope."""
        match code.kind:
            case "single":
                return qs.filter(account__code__startswith=code.value)
            case "list" | "range":
                values = code.as_list()
                print(">>>>>>", values)
                q = reduce(lambda acc, v: acc | Q(account__code__startswith=v), values, Q())
                return qs.filter(q)

    def apply_operator(
        self, qs: LineQuerySet, op: str, value: FilterValue, prefix: str = "account__code", no_exclude: bool = False
    ):
        """Apply provided operator on queryset.

        :param qs: queryset
        :param op: operator
        :param value: comparison value
        :param prefix: filter lookup prefix
        :param no_exclude: don't exclude, only filter
        """
        suffix = self.operators.get(op)
        if suffix is None:
            raise ValueError(f"Invalid operator `{op}`")

        kwargs = {prefix + suffix: value}
        if not no_exclude and op[0] == "!":
            return qs.exclude(**kwargs)
        return qs.filter(**kwargs)

    # ---- Filters
    def apply_filters(self, context, filters: Iterable[FilterToken], qs: LineQuerySet):
        """Apply filter list."""
        if not filters:
            return qs

        for filter in filters:
            func = getattr(self, f"apply_{filter.tag}_filter")
            qs = func(filter, qs)
        return qs

    def apply_debit_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(is_debit=True)

    def apply_credit_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(is_credit=True)

    def apply_movement_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(date__gte=context.period[0], date__lte=context.period[1])

    def apply_opening_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(date__lt=context.period[0])

    def apply_closing_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(date__lte=context.period[1])

    def apply_balance_filter(self, context, token: FilterToken, qs: LineQuerySet):
        # similar to closing, but introduce conceptual difference:
        # - closing: temporal calculation, does not depend on accounting plan
        return qs.filter(date__lte=context.period[1])

    def apply_counterpart_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Apply the "counterpart" filter."""

        counterpart_moves = self.qs.filter(move_id__in=qs.values_list("move_id", flat=True))
        counterpart_moves = (
            self.apply_operator(
                counterpart_moves,
                token.op,
                token.value,
                no_exclude=True,
            )
            .values_list("move_id", flat=True)
            .distinct()
        )

        if token.op[0] == "!":
            return qs.exclude(move_id__in=counterpart_moves)
        return qs.filter(move_id__in=counterpart_moves)
