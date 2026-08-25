from production_resource_gate import evaluate


def healthy_snapshot():
    return {
        "memory_available_bytes": 512 * 1024**2,
        "disk_free_bytes": 8 * 1024**3,
        "inode_free_ratio": 0.50,
        "load1_per_cpu": 0.5,
        "acceptance_seconds": 120,
    }


def test_resource_gate_accepts_healthy_small_host():
    assert evaluate(healthy_snapshot()) == []


def test_resource_gate_reports_every_unsafe_dimension():
    data = healthy_snapshot()
    data.update({
        "memory_available_bytes": 1,
        "disk_free_bytes": 1,
        "inode_free_ratio": 0.01,
        "load1_per_cpu": 9,
        "acceptance_seconds": 1600,
    })
    assert evaluate(data) == [
        "memory_available", "disk_free", "inode_free", "cpu_load",
        "acceptance_duration",
    ]


def test_missing_duration_does_not_create_fake_failure():
    data = healthy_snapshot()
    data["acceptance_seconds"] = None
    assert evaluate(data) == []
