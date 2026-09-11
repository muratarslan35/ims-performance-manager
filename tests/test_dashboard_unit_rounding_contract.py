from pathlib import Path


def test_national_unit_realization_is_rounded_to_nearest_integer():
    template = Path("app/templates/dashboard.html").read_text(encoding="utf-8")

    assert '\"{:.0f}\".format(national.unit_realization_percent' in template
