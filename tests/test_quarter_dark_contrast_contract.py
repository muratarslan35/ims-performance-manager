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

def test_quarter_ui_shows_remaining_tl_kpi_and_hides_actual_unit_column():
    template = (ROOT / "app/templates/quarter.html").read_text(encoding="utf-8")
    assert "Q Kalan ₺ Açığı" in template
    assert "report.summary.remaining_tl" in template
    assert "Hedefe kalan TL" in template
    assert "row-cols-xl-5" in template
    assert "Gerçekleşen kutu" not in template
    assert "row.actual_unit" not in template

    target_pos = template.index("Q Toplam TL Hedefi")
    actual_pos = template.index("Q Gerçekleşen TL")
    remaining_pos = template.index("Q Kalan ₺ Açığı")
    realization_pos = template.index("Q TL Realizasyonu")
    gross_pos = template.index("Q Toplam Brüt Hakkediş")
    assert target_pos < actual_pos < remaining_pos < realization_pos < gross_pos

