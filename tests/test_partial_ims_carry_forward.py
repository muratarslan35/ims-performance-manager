from app.services.partial_ims_carry_forward import combine_incremental_actuals


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
