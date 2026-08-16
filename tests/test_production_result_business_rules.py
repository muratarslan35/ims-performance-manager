from decimal import Decimal

from app.services.actual_sales_resolution_service import ActualSalesResolutionService, ActualSource, RealizationValue


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
