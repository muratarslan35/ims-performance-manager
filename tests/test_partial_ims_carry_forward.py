from app.services.partial_ims_import_carry_forward import (
    combine_incremental_actuals,
    derive_missing_unit_delta,
)


def test_partial_tl_is_added_to_previous_position_and_units_are_preserved():
    unit, tl = combine_incremental_actuals(1250, 480000.0, 0, 125000.0)
    assert unit == 1250
    assert tl == 605000.0


def test_partial_unit_and_tl_deltas_are_both_additive_when_present():
    unit, tl = combine_incremental_actuals(1250, 480000.0, 75, 125000.0)
    assert unit == 1325
    assert tl == 605000.0


def test_numeric_zero_is_real_and_does_not_erase_previous_actuals():
    unit, tl = combine_incremental_actuals(0, 480000.0, 0, 0)
    assert unit == 0
    assert tl == 480000.0


def test_march_missing_units_use_previous_full_march_effective_price_first():
    unit, source = derive_missing_unit_delta(
        month=3,
        incremental_tl=87432.0,
        incremental_unit=0,
        previous_unit=1000,
        previous_tl=87432.0,
        target_unit=900,
        target_tl=115479.0,
        configured_unit_price=128.31,
    )
    assert unit == 1000
    assert source == "previous_full_march_ims"


def test_march_falls_back_to_target_ratio_and_not_current_list_price():
    unit, source = derive_missing_unit_delta(
        month=3,
        incremental_tl=12831.0,
        incremental_unit=0,
        previous_unit=0,
        previous_tl=0,
        target_unit=1000,
        target_tl=100000.0,
        configured_unit_price=128.31,
    )
    assert unit == 128
    assert source == "march_target_ratio"


def test_after_march_uses_configured_current_unit_price_first():
    unit, source = derive_missing_unit_delta(
        month=4,
        incremental_tl=12831.0,
        incremental_unit=0,
        previous_unit=1000,
        previous_tl=87432.0,
        target_unit=1000,
        target_tl=100000.0,
        configured_unit_price=128.31,
    )
    assert unit == 100
    assert source == "configured_current_unit_price"


def test_existing_source_units_are_never_rederived():
    unit, source = derive_missing_unit_delta(
        month=3,
        incremental_tl=999999.0,
        incremental_unit=77,
        previous_unit=1000,
        previous_tl=87432.0,
        target_unit=1000,
        target_tl=100000.0,
        configured_unit_price=128.31,
    )
    assert unit == 77
    assert source == "source"
