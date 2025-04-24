class TestMoveRule:
    def test_get_lines(self, move, move_rule, line_rules):
        lines = move_rule.get_lines(move, {"ht": 100})
        for line, rule in zip(lines, line_rules):
            assert line.move == move
            assert line.account == rule.account
        assert [ln.amount for ln in lines] == [100, 21, 121]

    def test_compute(self, move_rule, line_rules):
        result = move_rule.compute({"ht": 100})
        assert result[line_rules[0]] == 100
        assert result[line_rules[1]] == 21
        assert result[line_rules[2]] == 121

    def test_get_interpreter(self, move_rule):
        ae = move_rule.get_interpreter({"tt": 121, "vat": 21})
        assert ae.symtable["tt"] == 121
        assert ae.symtable["vat"] == 21


class TestLineRule:
    def test_compute(self, move_rule, line_rule):
        ae = move_rule.get_interpreter({"tt": 121, "vat": 21})
        assert line_rule.compute(ae) == 100
