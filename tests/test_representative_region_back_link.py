from pathlib import Path


def test_manager_representative_detail_returns_to_selected_region():
    template = Path("app/templates/representative_detail.html").read_text(encoding="utf-8")

    assert "url_for('regions.detail', region_key=representative.region, year=year, month=month)" in template
    assert '<i class="bi bi-arrow-left"></i> Bölgeye Dön' in template
