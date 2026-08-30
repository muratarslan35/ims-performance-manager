#!/usr/bin/env python3
"""Read-only source↔DB reconciliation audit for production-result uploads."""

import argparse
import hashlib
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import ProductionResultUpload
from app.services.production_result_import_service import ProductionResultImportService
from app.services.production_result_reconciliation_gate import _reconcile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()

    app = create_app()
    failures = []
    checked = 0

    with app.app_context():
        uploads = (
            ProductionResultUpload.query
            .filter_by(year=args.year, month=args.month, production_stage=args.stage)
            .order_by(ProductionResultUpload.uploaded_at.asc(), ProductionResultUpload.id.asc())
            .all()
        )
        print(f"PRODUCTION_AUDIT_SCOPE|year={args.year}|month={args.month}|stage={args.stage}|uploads={len(uploads)}")
        if not uploads:
            print("PRODUCTION_AUDIT_RESULT|FAIL|reason=no_uploads")
            return 2

        upload_root = Path(app.config["UPLOAD_FOLDER"]) / "production_results"
        for upload in uploads:
            checked += 1
            source_path = upload_root / str(upload.stored_file_name or "")
            try:
                if upload.status != ProductionResultUpload.STATUS_APPLIED:
                    raise RuntimeError(f"status={upload.status}")
                if not upload.stored_file_name or not source_path.is_file():
                    raise RuntimeError("stored_source_missing")
                actual_hash = _sha256(source_path)
                if actual_hash != upload.source_hash:
                    raise RuntimeError(
                        f"source_hash_mismatch expected={upload.source_hash} actual={actual_hash}"
                    )

                report = ProductionResultImportService(
                    source_path,
                    upload.year,
                    upload.month,
                    production_stage=upload.production_stage,
                ).parse()
                _reconcile(upload, report)
                db.session.rollback()
                print(
                    "PRODUCTION_AUDIT_UPLOAD|PASS|"
                    f"id={upload.id}|file={upload.file_name}|stage={upload.production_stage}|"
                    f"rows={upload.row_count}|matched={upload.matched_row_count}|sha256={upload.source_hash}"
                )
            except Exception as exc:  # fail closed; audit never mutates upload state
                db.session.rollback()
                failures.append((upload.id, str(exc)))
                print(
                    "PRODUCTION_AUDIT_UPLOAD|FAIL|"
                    f"id={upload.id}|file={upload.file_name}|stage={upload.production_stage}|reason={exc}"
                )

        if failures:
            print(f"PRODUCTION_AUDIT_RESULT|FAIL|checked={checked}|failed={len(failures)}")
            return 1

        print(f"PRODUCTION_AUDIT_RESULT|PASS|checked={checked}|failed=0")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
