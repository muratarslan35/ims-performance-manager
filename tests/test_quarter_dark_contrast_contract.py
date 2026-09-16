from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quarter_dark_theme_keeps_cards_tables_and_metrics_readable():
    template = (ROOT / "app/templates/quarter.html").read_text(encoding="utf-8")
    assert '[data-theme="dark"] .quarter-card' in template
    assert '[data-bs-theme="dark"] .quarter-card' in template
    assert '[data-theme="dark"] .quarter-table td' in template
    assert '[data-theme="dark"] .quarter-value' in template
    assert '[data-theme="dark"] .submetric' in template


def test_quarter_gap_headers_explain_that_values_are_remaining():
    template = (ROOT / "app/templates/quarter.html").read_text(encoding="utf-8")
    for threshold in ("75", "90", "100"):
        assert f">%{threshold} için</span><span class=\"quarter-threshold-subtitle\">Kalan</span>" in template
