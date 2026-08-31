from app.services.partial_ims_import_carry_forward import (
    derive_missing_unit_delta,
    overlay_snapshot_actuals,
)


def test_partial_snapshot_replaces_previous_position_instead_of_adding_it():
    unit, tl = overlay_snapshot_actuals(1250, 480000.0, 1400, 605000.0)
    assert unit == 1400
    assert tl == 605000.0


def test_numeric_zero_is_real_in_current_snapshot():
    unit, tl = overlay_snapshot_actuals(1250, 480000.0, 0, 0)
    assert unit == 0
    assert tl == 0.0


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


def test_march_current_total_is_not_added_to_previous_units():
    unit, source = derive_missing_unit_delta(
        month=3,
        incremental_tl=174864.0,
        incremental_unit=0,
        previous_unit=1000,
        previous_tl=87432.0,
        target_unit=900,
        target_tl=115479.0,
        configured_unit_price=128.31,
    )
    assert unit == 2000
    assert source == "previous_full_march_ims"
    overlaid_unit, overlaid_tl = overlay_snapshot_actuals(1000, 87432.0, unit, 174864.0)
    assert overlaid_unit == 2000
    assert overlaid_tl == 174864.0


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
