#!/usr/bin/env python3
"""Restore one month's lost IMS box targets from an archived target-capable week.

Dry-run is the default.  The write mode changes only Target.unit_target and the
matching current-upload IMSSummary.target_unit values; TL targets, actuals,
roster, production results and every other period are fingerprint guarded.
"""

from __future__ import annotations

import argparse
import hashlib
import json

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSSummary, IMSUpload, Target
from app.services.ims_import_service import IMSImportService
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.target_import_service import TargetImportService


def _target_guard(year, month):
    return {
        (row.id, row.representative_id, row.product_id): (
            float(row.tl_target or 0),
            float(row.tl_realization or 0),
            float(row.unit_realization or 0),
            float(row.realization_percent or 0),
        )
        for row in Target.query.filter_by(year=year, month=month).all()
    }


def _extract_source_targets(source_upload, source_path, year, month, allowed_keys):
    savepoint = db.session.begin_nested()
    try:
        importer = IMSImportService(str(source_path), uploaded_by="monthly-unit-target-repair")
        importer.upload = source_upload
        importer.load_workbook()
        report = TargetImportService(
            file_path=str(source_path), upload_id=source_upload.id, workbook=importer.workbook
        ).run(year=year, month=month)
        if report.get("targets_errors"):
            raise RuntimeError(f"Target parser errors: {report}")
        importer.apply_balance_summary(year, month)
        db.session.flush()
        values = {
            (row.representative_id, row.product_id): float(row.unit_target or 0)
            for row in Target.query.filter_by(year=year, month=month).all()
            if (row.representative_id, row.product_id) in allowed_keys
        }
    finally:
        savepoint.rollback()
        db.session.expire_all()
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--source-week", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        processing = IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_PROCESSING).count()
        if processing:
            raise RuntimeError(f"IMS worker busy: processing={processing}")

        source_upload = (
            IMSUpload.query.filter_by(
                year=args.year, month=args.month, week_number=args.source_week, status="COMPLETED"
            ).order_by(IMSUpload.id.desc()).first()
        )
        if source_upload is None:
            raise RuntimeError("Target-capable source upload not found")
        source_path = IMSUploadLifecycleService.archived_source_for_upload(source_upload.id)
        if source_path is None:
            raise RuntimeError(f"Archived source missing for upload={source_upload.id}")

        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        job = IMSImportJob.query.filter_by(ims_upload_id=source_upload.id).first()
        if job is not None and job.source_hash and source_hash != job.source_hash:
            raise RuntimeError("Archived source SHA-256 does not match import job")

        current = Target.query.filter_by(year=args.year, month=args.month).all()
        current_map = {(row.representative_id, row.product_id): row for row in current}
        before_guard = _target_guard(args.year, args.month)
        source_values = _extract_source_targets(
            source_upload, source_path, args.year, args.month, set(current_map)
        )
        missing = sorted(key for key in current_map if float(source_values.get(key, 0)) == 0)
        if missing:
            raise RuntimeError(f"Source has {len(missing)} unresolved/zero unit targets")

        conflicts = [
            key for key, row in current_map.items()
            if float(row.unit_target or 0) not in (0.0, float(source_values[key]))
        ]
        if conflicts:
            raise RuntimeError(f"Refusing to overwrite {len(conflicts)} nonzero conflicting targets")

        changed = 0
        for key, row in current_map.items():
            value = source_values[key]
            if float(row.unit_target or 0) != value:
                row.unit_target = value
                changed += 1

        latest_upload_id = (
            db.session.query(db.func.max(IMSUpload.id))
            .filter_by(year=args.year, month=args.month, status="COMPLETED")
            .scalar()
        )
        summary_changed = 0
        for row in IMSSummary.query.filter_by(
            upload_id=latest_upload_id, year=args.year, month=args.month
        ).all():
            key = (row.representative_id, row.product_id)
            if key in source_values and float(row.target_unit or 0) != source_values[key]:
                row.target_unit = source_values[key]
                summary_changed += 1

        if _target_guard(args.year, args.month) != before_guard:
            # Guard intentionally excludes unit_target; all other target fields
            # must remain byte-for-byte equivalent at the scalar value level.
            raise RuntimeError("Non-unit target fields changed during repair")

        result = {
            "mode": "APPLY" if args.apply else "DRY_RUN",
            "year": args.year,
            "month": args.month,
            "source_week": args.source_week,
            "source_upload_id": source_upload.id,
            "source_sha256": source_hash,
            "target_rows": len(current_map),
            "changed_targets": changed,
            "changed_summaries": summary_changed,
        }
        if args.apply:
            db.session.commit()
        else:
            db.session.rollback()
        print("MONTHLY_UNIT_TARGET_REPAIR|PASS|" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

