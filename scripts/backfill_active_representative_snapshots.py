"""Build/reuse durable representative snapshots for the latest IMS period."""
from __future__ import annotations

import argparse
import fcntl
from pathlib import Path

from sqlalchemy import desc

from app import create_app
from app.models import IMSUpload
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Build a fresh generation even when the current IMS identity already has an ACTIVE set.",
    )
    args = parser.parse_args(argv)

    app = create_app()
    lock_path = Path(app.instance_path) / "representative_snapshot_warmup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("REPRESENTATIVE_SNAPSHOT_BACKFILL|status=SKIPPED|reason=ALREADY_RUNNING", flush=True)
            return 0

        with app.app_context():
            latest = IMSUpload.query.filter_by(status="COMPLETED").order_by(
                desc(IMSUpload.year),
                desc(IMSUpload.month),
                desc(IMSUpload.week_number),
                desc(IMSUpload.completed_at),
                desc(IMSUpload.id),
            ).first()
            if latest is None:
                print("REPRESENTATIVE_SNAPSHOT_BACKFILL|status=SKIPPED|reason=NO_COMPLETED_IMS", flush=True)
                return 0

            def progress(done, total, name):
                print(
                    f"REPRESENTATIVE_SNAPSHOT_BACKFILL_PROGRESS|{done}/{total}|{name}",
                    flush=True,
                )

            result = PersistentRepresentativeSnapshotService.build_for_period(
                latest.year,
                latest.month,
                force=args.force,
                progress=progress,
            )
            print(
                "REPRESENTATIVE_SNAPSHOT_BACKFILL|"
                f"status={result.get('status')}|year={latest.year}|month={latest.month}|"
                f"upload_id={latest.id}|representatives={result.get('representatives', 0)}|"
                f"set_id={result.get('set_id', 0)}|force={int(args.force)}",
                flush=True,
            )
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
