from app.services.ims_delta_service import _changed_exact, _changed_numeric


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
