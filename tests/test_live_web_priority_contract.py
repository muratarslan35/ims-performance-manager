from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_service_has_high_cpu_and_io_weight():
    unit = (ROOT / "deploy/ims-performance-manager.service.in").read_text(encoding="utf-8")
    assert "CPUAccounting=true" in unit
    assert "CPUWeight=10000" in unit
    assert "IOAccounting=true" in unit
    assert "IOWeight=1000" in unit


def test_import_worker_yields_resources_to_web():
    unit = (ROOT / "deploy/ims-import-worker.service.in").read_text(encoding="utf-8")
    assert "Nice=15" in unit
    assert "CPUWeight=50" in unit
    assert "IOWeight=50" in unit
    assert "IOSchedulingClass=idle" in unit
    assert "MemoryHigh=800M" in unit
    assert "MemoryMax=900M" in unit


def test_snapshot_backfills_run_at_low_os_priority_without_changing_policy():
    script = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert "run_low_priority()" in script
    assert "nice -n 15" in script
    assert "ionice -c3" in script
    assert "backfill_active_region_snapshots.py\" --force" in script
    assert "backfill_active_representative_snapshots.py\" --force" in script
    assert "verify_dashboard_snapshot_production.py" in script
    assert "REGION_SNAPSHOT_ACTIVATION|force_rebuild_after_backend_change" in script
    assert "REPRESENTATIVE_SNAPSHOT_BOOTSTRAP|ensure_active_before_web" in script
