import pytest

from django.db.models import Q

from fin.models import Line
from fin.engine.report.selector import CodeToken, FilterToken, Selector, SelectorParser, LineQueryBuilder

from .conftest import QuerySetSpy


@pytest.fixture
def sel_parser():
    return SelectorParser(single_filters=LineQueryBuilder.single_filters, operators=LineQueryBuilder.operators.keys())


@pytest.fixture
def line_query():
    qs = QuerySetSpy(Line)
    return LineQueryBuilder(qs)


class TestSelectorParser:
    def test___init__(self, sel_parser):
        assert isinstance(sel_parser.single_filters, set)
        assert sel_parser.operators == ["!:", "!=", ":", "="]

    def test_parse(self, sel_parser):
        assert sel_parser.parse("max:@123|credit") == Selector(
            aggr="max",
            scope=Selector.Scope.LINES,
            code=CodeToken(kind="single", value="123"),
            filters=(FilterToken(tag="credit"),),
        )
        assert sel_parser.parse("@123|credit") == Selector(
            aggr="sum",
            scope=Selector.Scope.LINES,
            code=CodeToken(kind="single", value="123"),
            filters=(FilterToken(tag="credit"),),
        )
        assert len(sel_parser.cache) == 2

    def test_parse_uses_cache(self, sel_parser):
        raw = "@123|credit"
        result = sel_parser.parse(raw)
        assert len(sel_parser.cache) == 1
        assert sel_parser.parse(raw) is result
        assert len(sel_parser.cache) == 1

    def test_parse_with_section_scope(self, sel_parser):
        assert sel_parser.parse("#123") == Selector(
            scope=Selector.Scope.SECTION, code=CodeToken(kind="single", value="123")
        )
        assert sel_parser.parse("#12,23") == Selector(
            scope=Selector.Scope.SECTION, code=CodeToken(kind="single", value="12,23")
        )

    def test_parse_with_lines_scope(self, sel_parser):
        assert sel_parser.parse("@123") == Selector(
            aggr="sum",
            scope=Selector.Scope.LINES,
            code=CodeToken(kind="single", value="123"),
            filters=tuple(),
        )
        assert sel_parser.parse("@12,23") == Selector(
            aggr="sum", scope=Selector.Scope.LINES, code=CodeToken(kind="list", value=["12", "23"]), filters=tuple()
        )
        assert sel_parser.parse("@12/23") == Selector(
            aggr="sum", scope=Selector.Scope.LINES, code=CodeToken(kind="range", value=("12", "23")), filters=tuple()
        )

    def test_parse_raise_wrong_expr(self, sel_parser):
        with pytest.raises(ValueError):
            sel_parser.parse("#123|credit")

        with pytest.raises(ValueError):
            sel_parser.parse("123|credit")

        with pytest.raises(ValueError):
            sel_parser.parse("@123:credit")

    def test_parse_code_is_section(self, sel_parser):
        assert sel_parser.parse_code("123", True) == CodeToken(kind="single", value="123")
        assert sel_parser.parse_code("12,23", True) == CodeToken(kind="single", value="12,23")
        assert sel_parser.parse_code("12/23", True) == CodeToken(kind="single", value="12/23")

    def test_parse_code_is_not_section(self, sel_parser):
        assert sel_parser.parse_code("123") == CodeToken(kind="single", value="123")
        assert sel_parser.parse_code("12,23") == CodeToken(kind="list", value=["12", "23"])
        assert sel_parser.parse_code("12/23") == CodeToken(kind="range", value=("12", "23"))

    def test_parse_filters(self, sel_parser):
        raw = "credit|counterpart:21"
        assert sel_parser.parse_filters(raw) == (
            FilterToken(tag="credit"),
            FilterToken(tag="counterpart", op=":", value="21"),
        )

    def test_parse_filters_raises_invalid_filter(self, sel_parser):
        with pytest.raises(ValueError):
            sel_parser.parse_filters("credit|somefilter < 123")

    def test_detect_op(self, sel_parser):
        assert sel_parser.detect_op("'some value' != [a,b,c]") == "!="
        assert sel_parser.detect_op("'some value' !: [a,b,c]") == "!:"
        assert sel_parser.detect_op("'some value' : [a,b,c]") == ":"
        assert sel_parser.detect_op("'some value' = [a,b,c]") == "="
        assert sel_parser.detect_op("mlkkl") is None


class TestLineQueryBuilder:
    def test_get_queryset(self, line_query, sel_parser, all_lines):
        token = sel_parser.parse("@1/2|debit")
        line_query.qs = Line.objects.all()

        qs = line_query.get_queryset(token, False)
        for item in qs:
            account = item.account
            assert account.code.startswith("1") or account.code.startswith("2")
            assert item.is_debit

    def test_get_queryset_with_counterpart(self, line_query, sel_parser, all_lines):
        token = sel_parser.parse("@2,3|counterpart:1")
        line_query.qs = Line.objects.all()

        qs = line_query.get_queryset(token, False)
        assert qs.exists() and len(qs) < len(line_query.qs)

        for item in qs:
            account = item.account
            assert account.code.startswith("2") or account.code.startswith("3")
            assert item.move.lines.filter(account__code__startswith="1").exists()

    def test_apply_aggregate(self, line_query, sel_parser):
        sel = sel_parser.parse("@102|credit")
        line_query.get_queryset(sel)
        # TODO: test value

    def test_apply_code_with_single(self, line_query):
        qs = line_query.apply_code(CodeToken(kind="single", value="123"), line_query.qs)
        assert qs.called_with("filter", account__code__startswith="123")

    def test_apply_code_with_list(self, line_query):
        qs = line_query.apply_code(CodeToken(kind="list", value=["123", "234"]), line_query.qs)
        assert qs.called_with("filter", Q(account__code__startswith="123") | Q(account__code__startswith="234"))

    def test_apply_code_with_range(self, line_query):
        qs = line_query.apply_code(CodeToken(kind="range", value=("123", "234")), line_query.qs)
        assert qs.called_with("filter", account__code__gte="123", account__code__lte="234")

    def test_apply_filters(self, line_query):
        filters = [FilterToken("credit"), FilterToken("debit")]
        qs = line_query.apply_filters(filters, line_query.qs)
        assert qs.called_with("filter", is_debit=True)
        assert qs.called_with("filter", is_credit=True)

    def test_apply_filters_with_no_filters(self, line_query):
        n = len(line_query.qs.calls)
        line_query.apply_filters([], line_query.qs)
        assert n == len(line_query.qs.calls)

    def test_apply_debit_filter(self, line_query):
        token = FilterToken("debit")
        qs = line_query.apply_debit_filter(token, line_query.qs)
        assert qs.called_with("filter", is_debit=True)

    def test_apply_credit_filter(self, line_query):
        token = FilterToken("credit")
        qs = line_query.apply_credit_filter(token, line_query.qs)
        assert qs.called_with("filter", is_credit=True)

    def test_apply_operator(self, line_query):
        qs = line_query.apply_operator(line_query.qs, ":", "123")
        assert qs.called_with("filter", account__code__startswith="123")

        qs = line_query.apply_operator(line_query.qs, "!:", "123")
        assert qs.called_with("exclude", account__code__startswith="123")

        qs = line_query.apply_operator(line_query.qs, "!:", "123", no_exclude=True)
        assert qs.called_with("filter", account__code__startswith="123")

        with pytest.raises(ValueError):
            line_query.apply_operator(line_query.qs, "<:", "123")
