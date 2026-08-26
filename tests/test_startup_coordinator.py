from pathlib import Path
import os

import pytest

from app.services.startup_coordinator import StartupCoordinator


def test_startup_coordinator_releases_reusable_lock(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX advisory lock contract is exercised on Linux CI/production.")
    class App:
        instance_path = str(tmp_path)

    with StartupCoordinator.acquire(App()):
        lock_path = Path(tmp_path) / "locks" / "application-startup.lock"
        assert lock_path.exists()

    with StartupCoordinator.acquire(App()):
        assert lock_path.exists()
