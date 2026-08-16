from decimal import Decimal
import pytest

from app.services.actual_sales_resolution_service import (
    ActualSalesResolutionService,
    ActualSalesValue,
    ActualSource,
)


def row(source, amount):
    return ActualSalesValue(source=source, amount_tl=Decimal(amount))


def test_ims_is_used_before_any_production_arrives():
    assert ActualSalesResolutionService.choose_period_source([ActualSource.IMS]) == ActualSource.IMS


def test_first_production_immediately_replaces_ims_without_waiting_for_second():
    assert ActualSalesResolutionService.choose_period_source(
        [ActualSource.IMS, ActualSource.PRODUCTION_1]
    ) == ActualSource.PRODUCTION_1


def test_second_production_replaces_first_when_it_exists():
    assert ActualSalesResolutionService.choose_period_source(
        [ActualSource.IMS, ActualSource.PRODUCTION_1, ActualSource.PRODUCTION_2]
    ) == ActualSource.PRODUCTION_2


def test_second_production_can_be_final_even_if_first_never_arrived():
    assert ActualSalesResolutionService.choose_period_source(
        [ActualSource.IMS, ActualSource.PRODUCTION_2]
    ) == ActualSource.PRODUCTION_2


def test_no_source_is_an_error_not_a_zero_sale():
    with pytest.raises(ValueError):
        ActualSalesResolutionService.choose_period_source([])


def test_nationwide_snapshot_never_mixes_sources():
    selected, rows = ActualSalesResolutionService.resolve_nationwide_snapshot({
        ActualSource.IMS: [row(ActualSource.IMS, "100")],
        ActualSource.PRODUCTION_1: [row(ActualSource.PRODUCTION_1, "90")],
    })
    assert selected == ActualSource.PRODUCTION_1
    assert [x.amount_tl for x in rows] == [Decimal("90")]
    assert all(x.source == ActualSource.PRODUCTION_1 for x in rows)


def test_resolution_uses_decimal_without_float_conversion():
    result = ActualSalesResolutionService.resolve([
        row(ActualSource.IMS, "100.01"),
        row(ActualSource.PRODUCTION_1, "99.99"),
    ])
    assert result.source == ActualSource.PRODUCTION_1
    assert result.amount_tl == Decimal("99.99")
