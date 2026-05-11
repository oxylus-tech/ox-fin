from dataclasses import dataclass
from enum import Enum
from functools import cached_property
import operator
import re
from typing import Literal, Iterable


from django.db.models import Sum, Max, Min, Q

from fin.models.book_template import Account
from fin.models.book import LineQuerySet


__all__ = ("CodeToken", "FilterToken", "Selector", "SelectorFormatError", "SelectorParser", "LineQuery")


CodeKind = Literal["range", "list", "single"]
CodeValue = str | tuple[str, str] | list[str]
FilterValue = str | None


@dataclass
class CodeToken:
    value: CodeValue
    kind: CodeKind = "single"

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

    def __str__(self):
        return self.to_string()

    def __hash__(self):
        value = tuple(self.value) if isinstance(self.value, list) else self.value
        return hash((self.kind, value))


@dataclass
class FilterToken:
    tag: str
    op: str | None = None
    value: FilterValue = None

    def __str__(self):
        if self.op:
            return self.tag + self.op + self.value
        return self.tag

    def __hash__(self):
        return hash((self.tag, self.op, self.value))


@dataclass(frozen=True)
class Selector:
    class Scope(Enum):
        SECTION = 0x00
        """ A report section. """
        STATE = 0x01
        """ Accounts state lines. """
        FLOW = 0x02
        """ Accounts lines flow. """

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
        return self.scope in (self.Scope.STATE, self.Scope.FLOW)

    def __str__(self):
        val = ""
        if self.aggr:
            val += self.aggr + ":"

        match self.scope:
            case self.Scope.STATE:
                val += "@"
            case self.Scope.FLOW:
                val += "~"

        val += str(self.code)
        if self.filters:
            val += "|".join(str(f) for f in self.filters)
        return val

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

    section_re = re.compile(r"^#?(?P<code>[0-9a-zA-Z/,_:()-]+)?$")

    # TODO: update regexp for more strict check against "*" and "/" operators
    lines_re = re.compile(
        r"^(?:(?P<aggr>[a-zA-Z]+):)? *" r"(?P<scope>[@~])(?P<code>[0-9/,]+) *" r"(?:\|(?P<filters>.+))?$"
    )

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
        match mat.group("scope"):
            case "@":
                scope = Selector.Scope.STATE
            case "~":
                scope = Selector.Scope.FLOW

        return Selector(
            aggr=mat.group("aggr") or self.default_aggr,
            scope=scope,
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


class LineQuery:
    """This class allows to transform a selector token into queryset (for lines)."""

    single_filters: set[str] = {
        "debit",
        "credit",
        "opening",
        "closing",
        # assets and related accounts
        "fixed_asset",
        "asset_dep_exp",
        "asset_acc_dep",
        "asset_gain",
        "asset_loss",
    }
    filters = "counterpart"
    operators = {
        ":",
        "!:",
        "=",
        "!=",
    }
    """ Operators and lookup. It is assumed that an operator starting with "!" means excluding instead of filter.

    Operators:

        - ``:``, ``!:``: account code starts or not with the provided value
        - ``=``, ``!=``: account code or other field is or is not the provided value.

    """
    aggregates = {"sum": Sum, "max": Max, "min": Min}
    """ Aggregation functions. """

    def __init__(self, qs: LineQuerySet):
        self.qs = qs

    def get_queryset(self, context, selector: Selector, aggregate: bool = True):
        """Return queryset constructor on the selector.

        :raises SelectorFormatError: invalid input format for a selector.
        """
        assert selector.is_lines

        qs = self.qs.distinct()
        if selector.scope == Selector.Scope.STATE:
            qs = qs.with_norm_amount()

        qs = self.apply_code(selector.code, qs)
        qs = self.apply_filters(context, selector.filters, qs)
        if aggregate:
            qs = self.apply_aggregate(selector, qs)
        return qs

    def apply_aggregate(self, selector: Selector, qs: LineQuerySet, key: str = "total"):
        """Apply aggregation function."""
        match selector.scope:
            case Selector.Scope.STATE:
                field = "norm_amount"
            case Selector.Scope.FLOW:
                field = "amount"

        if func := self.aggregates.get(selector.aggr):
            return qs.aggregate(**{key: func(field)})
        raise ValueError(f"Unknown aggregate function {selector.aggr}")

    def apply_code(self, code: CodeToken, qs: LineQuerySet):
        """Apply scope."""
        match code.kind:
            case "single":
                return qs.filter(account__code__startswith=code.value)
            case "list" | "range":
                q = self.get_code_q(code.as_list())
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
        match op:
            case ":":
                q = self.get_code_q(value)
            case "!:":
                q = self.get_code_q(value, operator.and_)
            case "=" | "!=":
                q = Q(**{prefix: value})
            case _:
                raise ValueError(f"Invalid operator `{op}`")

        if not no_exclude and op[0] == "!":
            return qs.exclude(q)
        return qs.filter(q)

    def get_code_q(self, value: str | list[str], op=operator.or_, lookup="account__code"):
        """Return Q object for code lookup, using "startswith" and "endswith" lookups."""
        q = Q()
        if isinstance(value, str):
            value = value.split(",")

        for code in value:
            # THIS wont work, example 21*9 => what about accounts like 21091
            # if "*" in code:
            #    start, end = code.split("*", 1)
            #    kw={lookup + "__startswith": start, lookup + "__endswith": end}
            # else:
            kw = {lookup + "__startswith": code}
            q = op(q, Q(**kw))
        return q

    # ---- Filters
    def apply_filters(self, context, filters: Iterable[FilterToken], qs: LineQuerySet):
        """Apply filter list."""
        if not filters:
            return qs

        for filter in filters:
            func = getattr(self, f"apply_{filter.tag}_filter")
            qs = func(context, filter, qs)
        return qs

    def apply_debit_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(is_debit=True)

    def apply_credit_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(is_credit=True)

    def apply_opening_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(date__lt=context.period[0])

    def apply_closing_filter(self, context, token: FilterToken, qs: LineQuerySet):
        return qs.filter(date__lte=context.period[1])

    # --- Assets
    def apply_fixed_asset_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Select fixed assets that can be amortized."""
        return qs.filter(
            Q(account__dep_exp_account__isnull=False, account__acc_dep_account__isnull=False)
            | Q(account__gain_account__isnull=False, account__loss_account__isnull=False),
            account__type=Account.Type.ASSET,
        )

    def apply_asset_dep_exp_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Filter accounts used for depreciation/amortization (debit)."""
        return qs.filter(account__dep_exp_for__isnull=False)

    def apply_asset_acc_dep_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Filter accounts used for accumulated amortization on asset (credit)."""
        return qs.filter(account__acc_dep_for__isnull=False)

    def apply_asset_gain_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Filter accounts used for gains on asset."""
        return qs.filter(account__gain_for__isnull=False)

    def apply_asset_loss_filter(self, context, token: FilterToken, qs: LineQuerySet):
        """Filter accounts used for losses on asset."""
        return qs.filter(account__loss_for__isnull=False)

    # --- Other filters
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
