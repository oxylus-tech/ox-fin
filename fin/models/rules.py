from __future__ import annotations
from decimal import Decimal

from asteval import Interpreter
from django.db import models
from django.utils.translation import gettext_lazy as _

from .utils import Described, Named
from .template import BookTemplate, Journal, Account
from .book import Line, Move


__all__ = ("MoveRule", "LineRule")


class MoveRule(Described):
    """
    This model provide a set of rules to apply in order to generate
    a :py:class:`~.book.Move` and the related :py:class:`~.book.Line`.

    Each :py:class:`LineRule` has a formula to apply based on input values to produce an output amount. Each LineRule is related to a single
    account, which allows to create output values.
    """

    template = models.ForeignKey(BookTemplate, models.CASCADE, related_name="move_rules")
    journal = models.ForeignKey(Journal, models.CASCADE, related_name="move_rules")
    code = models.CharField(_("Code"), max_length=32)

    class Meta:
        verbose_name = _("Move Rule")
        verbose_name_plural = _("Move Rules")

    def get_lines(self, move: Move, values: dict[str, Decimal]) -> list[Line]:
        result = self.compute(values)
        return [Line(move=move, account=rule.account, amount=amount) for rule, amount in result.items() if amount]

    def compute(self, values) -> dict[LineRule, Decimal | None]:
        rules = self.line_rules.all().order_by("order", "pk")
        ae = self.get_interpreter(
            {
                **{r.code: 0 for r in rules},
                **values,
            }
        )

        for rule in rules:
            if rule.code and rule.code not in values:
                ae.symtable[rule.code] = rule.compute(ae)
        return {rule: ae.symtable[rule.code] for rule in rules}

    def get_interpreter(self, context) -> Interpreter:
        """Return asteval Interpreter with symtable fullfilled with values."""
        ae = Interpreter()
        ae.symtable.update(context)
        return ae


class LineRule(Named):
    move_rule = models.ForeignKey(MoveRule, models.CASCADE, related_name="line_rules")
    account = models.ForeignKey(Account, models.CASCADE, related_name="+")
    code = models.CharField(_("Code"), max_length=10)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    formula = models.CharField(_("Formula"), blank=True, default="", max_length=100)

    class Meta:
        verbose_name = _("Line Rule")
        verbose_name_plural = _("Line Rules")

    def compute(self, interpreter):
        return interpreter(self.formula)
