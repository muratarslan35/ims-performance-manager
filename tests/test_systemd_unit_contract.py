from pathlib import Path


def test_start_limit_directives_live_in_unit_section():
    text = Path("deploy/ims-performance-manager.service.in").read_text(encoding="utf-8")
    unit, service_and_rest = text.split("[Service]", 1)
    service, _ = service_and_rest.split("[Install]", 1)

    assert "StartLimitIntervalSec=60" in unit
    assert "StartLimitBurst=5" in unit
    assert "StartLimitIntervalSec" not in service
    assert "StartLimitBurst" not in service
