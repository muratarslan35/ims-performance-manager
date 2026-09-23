from decimal import Decimal
from types import SimpleNamespace

from app.services.actual_sales_resolution_service import ActualSalesResolutionService, ActualSource, RealizationValue
from app.services.production_result_service import ProductionResultService


def test_production_does_not_wait_for_stage_two():
    assert ActualSalesResolutionService.choose_period_source([ActualSource.IMS, ActualSource.PRODUCTION_1]) == ActualSource.PRODUCTION_1


def test_stage_two_can_arrive_without_stage_one():
    assert ActualSalesResolutionService.choose_period_source([ActualSource.IMS, ActualSource.PRODUCTION_2]) == ActualSource.PRODUCTION_2


def test_production_percent_above_100_is_never_capped():
    result = ActualSalesResolutionService.resolve([
        RealizationValue(ActualSource.IMS, Decimal("100")),
        RealizationValue(ActualSource.PRODUCTION_1, Decimal("230")),
    ])
    assert result.realization_percent == Decimal("230")


def test_percent_precision_is_not_rounded():
    result = ActualSalesResolutionService.resolve([
        RealizationValue(ActualSource.PRODUCTION_2, Decimal("174.123456789")),
    ])
    assert result.realization_percent == Decimal("174.123456789")


def test_nationwide_snapshot_uses_one_source_only():
    selected, rows = ActualSalesResolutionService.resolve_nationwide_snapshot({
        ActualSource.IMS: [RealizationValue(ActualSource.IMS, Decimal("91"))],
        ActualSource.PRODUCTION_1: [RealizationValue(ActualSource.PRODUCTION_1, Decimal("101"))],
    })
    assert selected == ActualSource.PRODUCTION_1
    assert len(rows) == 1
    assert rows[0].realization_percent == Decimal("101")


def _production_row(representative_id, units, tl=None):
    return SimpleNamespace(
        representative_id=representative_id,
        actual_unit=Decimal(str(units)),
        actual_tl=Decimal(str(tl if tl is not None else units * 100)),
    )


def test_isolated_one_or_two_box_movements_are_incidental_for_quota_exit():
    rows = [_production_row(rep_id, 2) for rep_id in range(1, 21)]

    assert ProductionResultService._only_incidental_sales(rows) is True


def test_clear_nationwide_product_sales_never_become_quota_exit():
    assert ProductionResultService._only_incidental_sales([
        _production_row(rep_id, 2) for rep_id in range(1, 22)
    ]) is False
    assert ProductionResultService._only_incidental_sales([
        _production_row(1, 50), _production_row(2, 50)
    ]) is False
    assert ProductionResultService._only_incidental_sales([
        _production_row(1, 3)
    ]) is False
