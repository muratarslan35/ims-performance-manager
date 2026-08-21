from pathlib import Path

from app.services.startup_coordinator import StartupCoordinator


def test_startup_coordinator_releases_reusable_lock(tmp_path):
    class App:
        instance_path = str(tmp_path)

    with StartupCoordinator.acquire(App()):
        lock_path = Path(tmp_path) / "locks" / "application-startup.lock"
        assert lock_path.exists()

    with StartupCoordinator.acquire(App()):
        assert lock_path.exists()
