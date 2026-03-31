import pytest

from fin.models import AmortizationEntry


class TestFixedAsset:
    def test_get_applied_amortizations(self, fixed_asset, amortization_entries):
        assert fixed_asset.get_applied_amortizations() == fixed_asset.initial_value

        last = amortization_entries[-1]
        last.delete()
        assert fixed_asset.get_applied_amortizations() == fixed_asset.initial_value - last.amount


class TestAmortizationSchedule:
    def test_get_applied_amount(self, fixed_asset, amortization_schedule, amortization_entries):
        assert amortization_schedule.get_applied_amount() == fixed_asset.initial_value

    def test_clear_entries(self, amortization_schedule, amortization_entries):
        amortization_schedule.clear_entries()

        query = AmortizationEntry.objects.filter(pk__in=[e.pk for e in amortization_entries])
        assert not query.exists()

    def test_clear_entries_from_date(self, amortization_schedule, amortization_entries):
        last = amortization_entries[-1]
        amortization_schedule.clear_entries(last.date)

        assert not AmortizationEntry.objects.filter(pk=last.pk).exists()

    def test_clear_entries_raises_move_exists(
        self, amortization_schedule, amortization_entries, amortization_entry_moves
    ):
        with pytest.raises(RuntimeError):
            amortization_schedule.clear_entries()
