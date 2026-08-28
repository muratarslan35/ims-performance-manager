from app.services.ims_delta_service import (
    _changed_exact,
    _changed_numeric,
    _competition_delta_from_rows,
    _competition_map_from_rows,
)


def test_numeric_delta_detects_added_removed_and_changed_values():
    old = {("A", 1): (10.0, 100.0), ("B", 1): (20.0, 200.0)}
    new = {("A", 1): (10.0, 101.0), ("C", 1): (30.0, 300.0)}
    changed = set(_changed_numeric(old, new))
    assert changed == {("A", 1), ("B", 1), ("C", 1)}


def test_numeric_delta_ignores_tiny_float_noise():
    old = {("A", 1): (10.0, 100.0)}
    new = {("A", 1): (10.0 + 1e-8, 100.0 - 1e-8)}
    assert _changed_numeric(old, new) == []


def test_region_cadre_delta_compares_exact_organisational_context():
    old = {1: (("101", "DIYARBAKIR", "MUDUR A"),), 2: (("102", "MARDIN", "MUDUR B"),)}
    new = {1: (("101", "DIYARBAKIR", "MUDUR A"),), 2: (("103", "MARDIN", "MUDUR B"),)}
    assert _changed_exact(old, new) == [2]


def test_competition_delta_scalar_stream_preserves_business_grain_and_sum():
    rows = [
        ("MONTHLY", "101", "BRICK A", "TRAVAZOL", "RIVAL A", "UNIT", False, False, 10),
        ("MONTHLY", "101", "BRICK A", "TRAVAZOL", "RIVAL A", "UNIT", False, False, 2.5),
        ("MONTHLY", "101", "BRICK A", "TRAVAZOL", "RIVAL A", "UNIT", True, False, 7),
    ]

    result = _competition_map_from_rows(iter(rows))

    assert result[("MONTHLY", "101", "BRICK A", "TRAVAZOL", "RIVAL A", "UNIT", False, False)] == (12.5,)
    assert result[("MONTHLY", "101", "BRICK A", "TRAVAZOL", "RIVAL A", "UNIT", True, False)] == (7.0,)


def test_competition_single_table_delta_matches_historical_two_map_semantics():
    old_rows = [
        ("MONTHLY", "101", "A", "P", "R", "UNIT", False, False, 10),
        ("MONTHLY", "101", "A", "P", "R", "UNIT", False, False, 2.5),
        ("MONTHLY", "101", "A", "P", "R", "UNIT", True, False, 7),
        ("MONTHLY", "101", "B", "P", "R", "UNIT", False, True, 0),
    ]
    new_rows = [
        ("MONTHLY", "101", "A", "P", "R", "UNIT", False, False, 12.5),
        ("MONTHLY", "101", "A", "P", "R", "UNIT", True, False, 8),
        ("MONTHLY", "101", "C", "P", "R", "UNIT", False, True, 0),
    ]
    old_map = _competition_map_from_rows(iter(old_rows))
    new_map = _competition_map_from_rows(iter(new_rows))
    expected_changed = len(_changed_numeric(old_map, new_map))

    result = _competition_delta_from_rows(iter(old_rows), iter(new_rows))

    assert result == {
        "competition_changed": expected_changed,
        "competition_count_before": len(old_map),
        "competition_count_after": len(new_map),
        "competition_count_changed": len(old_map) != len(new_map),
    }


def test_competition_single_table_delta_preserves_zero_and_boolean_grain():
    old_rows = [
        ("WEEKLY", "R", "B", "P", "X", "TL", False, False, 0),
        ("WEEKLY", "R", "B", "P", "X", "TL", True, False, 0),
    ]
    new_rows = list(old_rows)

    result = _competition_delta_from_rows(iter(old_rows), iter(new_rows))

    assert result["competition_count_before"] == 2
    assert result["competition_count_after"] == 2
    assert result["competition_changed"] == 0
    assert result["competition_count_changed"] is False
