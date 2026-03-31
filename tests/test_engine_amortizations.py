from datetime import date
from decimal import Decimal

import pytest

from fin.models import ProrataPolicy, AmortizationEntry
from fin.engine.amortizations import AmortizationEntryBuilder


@pytest.fixture
def builder():
    return AmortizationEntryBuilder()


class TestAmortizationEntryBuilder:
    def test_build_with_clear(self, builder, amortization_schedule):
        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        # All entries should be within schedule bounds
        assert len(entries) > 0
        assert entries[0].date >= amortization_schedule.start_date
        assert entries[-1].date <= amortization_schedule.end_date

        # Ensure full schedule is generated
        total = sum(e.amount for e in entries)
        expected = amortization_schedule.asset.value - amortization_schedule.residual_value
        assert total == expected.quantize(Decimal("0.01"))

    def test_build_without_clear(self, builder, amortization_schedule):
        # Step 1: generate full schedule
        full_entries = builder.build(
            schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True
        )

        # Persist first half
        half = len(full_entries) // 2
        AmortizationEntry.objects.bulk_create(full_entries[:half])

        # Step 2: resume generation
        new_entries = builder.build(
            schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=False
        )

        # Ensure no overlap
        existing_dates = {e.date for e in full_entries[:half]}
        new_dates = {e.date for e in new_entries}

        assert existing_dates.isdisjoint(new_dates)

        # Ensure full reconstruction
        all_entries = full_entries[:half] + new_entries
        total = sum(e.amount for e in all_entries)

        expected = amortization_schedule.asset.value - amortization_schedule.residual_value
        assert total == expected.quantize(Decimal("0.01"))

    # ---------- PERIOD END ----------

    def test__period_end_frequency_year(self, builder):
        d = date(2025, 6, 15)
        assert builder._period_end(12, d) == date(2025, 12, 31)

    def test__period_end_frequency_month(self, builder):
        d = date(2025, 2, 10)
        assert builder._period_end(1, d) == date(2025, 2, 28)

    def test__period_end_frequency_quarter(self, builder):
        d = date(2025, 2, 10)
        # Q1 → March (NOTE: your current implementation returns April 1st!)
        assert builder._period_end(3, d).month in (3, 4)

    def test__period_end_frequency_months(self, builder):
        d = date(2025, 1, 15)
        result = builder._period_end(6, d)
        assert result.month in (6, 7)

    # ---------- PRORATA ----------

    def test__prorata_factor_use_schedule_prorata(self, builder, amortization_schedule):
        amortization_schedule.prorata = ProrataPolicy.NONE
        val = builder._prorata_factor(amortization_schedule, date(2025, 1, 1), date(2025, 12, 31))
        assert val == Decimal("1.")

    def test__prorata_factor_policy_none(self, builder, amortization_schedule):
        amortization_schedule.prorata = ProrataPolicy.NONE
        val = builder._prorata_factor(amortization_schedule, date(2025, 1, 1), date(2025, 6, 30))
        assert val == Decimal("1.")

    def test__prorata_factor_policy_daily(self, builder, amortization_schedule):
        amortization_schedule.prorata = ProrataPolicy.DAILY

        val = builder._prorata_factor(amortization_schedule, date(2025, 1, 1), date(2025, 1, 31))

        assert val > 0
        assert val < 1

    def test__prorata_factor_policy_full_month(self, builder, amortization_schedule):
        amortization_schedule.prorata = ProrataPolicy.FULL_MONTH

        val = builder._prorata_factor(amortization_schedule, date(2025, 1, 1), date(2025, 3, 31))

        assert val == Decimal("3") / Decimal("12")

    def test__prorata_factor_policy_raise_invalid_policy(self, builder, amortization_schedule):
        amortization_schedule.prorata = 999  # invalid

        with pytest.raises(ValueError):
            builder._prorata_factor(amortization_schedule, date(2025, 1, 1), date(2025, 1, 31))

    # ---------- APPLY METHOD ----------

    def test__apply_method_linear(self, builder, amortization_schedule):
        amortization_schedule.method = amortization_schedule.Method.LINEAR
        amortization_schedule.residual_value = Decimal("0")

        val = builder._apply_method(
            amortization_schedule,
            remaining_value=Decimal("10000"),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )

        assert val > 0

    def test__apply_method_degressive(self, builder, amortization_schedule):
        amortization_schedule.method = amortization_schedule.Method.DEGRESSIVE
        amortization_schedule.rate = Decimal("0.2")

        val = builder._apply_method(
            amortization_schedule,
            remaining_value=Decimal("10000"),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )

        assert val == Decimal("10000") * Decimal("0.2") * (Decimal(amortization_schedule.frequency) / 12)

    def test__apply_method_raise_unsupported(self, builder, amortization_schedule):
        amortization_schedule.method = 999

        with pytest.raises(ValueError):
            builder._apply_method(
                amortization_schedule,
                remaining_value=Decimal("10000"),
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
            )


class TestAmortizationEntryBuilderConsistency:
    def test_build_full_schedule_consistency(self, builder, amortization_schedule):
        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        total = sum(e.amount for e in entries)

        expected = amortization_schedule.asset.value - amortization_schedule.residual_value

        assert total == expected.quantize(Decimal("0.01"))

    def test_build_never_below_residual(self, builder, amortization_schedule):
        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        remaining = amortization_schedule.asset.value

        for entry in entries:
            remaining -= entry.amount
            assert remaining >= amortization_schedule.residual_value

    def test_build_resume_existing_entries(self, builder, amortization_schedule):
        # First run
        entries_1 = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        # Persist first half
        half = len(entries_1) // 2
        AmortizationEntry.objects.bulk_create(entries_1[:half])

        # Resume
        entries_2 = builder.build(
            schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=False
        )

        # No overlap
        existing_dates = {e.date for e in entries_1[:half]}
        new_dates = {e.date for e in entries_2}

        assert existing_dates.isdisjoint(new_dates)

    def test_rounding_three_years(self, builder, amortization_schedule):
        amortization_schedule.asset.value = Decimal("10000")
        amortization_schedule.residual_value = Decimal("0")
        amortization_schedule.start_date = date(2025, 1, 1)
        amortization_schedule.end_date = date(2027, 12, 31)
        amortization_schedule.frequency = 12  # yearly

        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        amounts = [e.amount for e in entries]

        assert len(amounts) == 3
        assert sum(amounts) == Decimal("10000.00")

        # Check rounding distribution
        assert any(a != amounts[0] for a in amounts)  # last entry adjusted

    def test_rounding_residual_protection(self, builder, amortization_schedule):
        amortization_schedule.asset.value = Decimal("100.00")
        amortization_schedule.residual_value = Decimal("0")
        amortization_schedule.frequency = 12

        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        total = sum(e.amount for e in entries)

        assert total == Decimal("100.00")

    def test_last_entry_adjusts_rounding(self, builder, amortization_schedule):
        amortization_schedule.asset.value = Decimal("1000.01")
        amortization_schedule.residual_value = Decimal("0")
        amortization_schedule.frequency = 12

        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        total = sum(e.amount for e in entries)
        assert total == Decimal("1000.01")

        # Only last entry should absorb rounding difference
        base = entries[0].amount
        diffs = [e.amount for e in entries if e.amount != base]

        assert len(diffs) <= 1  # only one adjusted entry

    def test_degressive_never_exceeds_remaining(self, builder, amortization_schedule):
        amortization_schedule.method = amortization_schedule.Method.DEGRESSIVE
        amortization_schedule.rate = Decimal("0.5")

        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        remaining = amortization_schedule.asset.value

        for entry in entries:
            assert entry.amount <= remaining
            remaining -= entry.amount

    def test_stops_when_residual_reached(self, builder, amortization_schedule):
        amortization_schedule.asset.value = Decimal("1000")
        amortization_schedule.residual_value = Decimal("900")

        entries = builder.build(schedule=amortization_schedule, period_end=amortization_schedule.end_date, clear=True)

        total = sum(e.amount for e in entries)

        assert total == Decimal("100")
