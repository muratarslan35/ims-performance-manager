#!/usr/bin/env python
"""Validate IMS import pipeline against the real development sample workbook."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy.exc import OperationalError

from app import create_app
from app.database import initialize_database
from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService
from config import Config


REPO_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = str(REPO_ROOT / "migrations")
DEFAULT_SAMPLE = REPO_ROOT / "Tayfun-1 24.Hafta Haziran Brick Analizi_.xlsx"


class ValidationConfig(Config):
    TESTING = True


def run_validation(db_url: str, sample_path: Path = DEFAULT_SAMPLE) -> dict:
    if not sample_path.exists():
        raise FileNotFoundError(f"Sample workbook not found: {sample_path}")

    config = type("SampleImportValidationConfig", (ValidationConfig,), {"SQLALCHEMY_DATABASE_URI": db_url})
    app = create_app(config)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()
        AliasService.clear_cache()

        IMSUpload.query.delete(synchronize_session=False)
        IMSRawData.query.delete(synchronize_session=False)
        IMSFact.query.delete(synchronize_session=False)
        IMSSummary.query.delete(synchronize_session=False)
        db.session.commit()

        captured_stage_payloads: list[dict] = []
        original_log_stage_metrics = IMSImportService._log_stage_metrics

        def capture_stage_metrics(service, stage, **metrics):
            payload = {
                "stage": stage,
                "upload_id": service.upload.id if service.upload else None,
                **metrics,
            }
            captured_stage_payloads.append(payload)
            return original_log_stage_metrics(service, stage, **metrics)

        IMSImportService._log_stage_metrics = capture_stage_metrics

        try:
            result = IMSImportService(sample_path, uploaded_by="Runtime Validation").run(2026, 6)
        except OperationalError as exc:
            raise RuntimeError(f"sqlite OperationalError during import: {exc}") from exc
        finally:
            IMSImportService._log_stage_metrics = original_log_stage_metrics
            AliasService.clear_cache()

        error_blob = " | ".join(result.get("errors", []))
        if not result.get("success"):
            raise RuntimeError(f"Import failed: {error_blob or 'unknown error'}")
        if "OperationalError" in error_blob or "no such column" in error_blob or "has no column named" in error_blob:
            raise RuntimeError(f"Schema/missing-column error detected: {error_blob}")

        summary_count = db.session.query(IMSSummary).count()
        fact_count = db.session.query(IMSFact).count()
        raw_count = db.session.query(IMSRawData).count()
        if summary_count <= 0:
            raise RuntimeError("ims_summary insert failed: no rows created")
        if fact_count <= 0:
            raise RuntimeError("ims_facts insert failed: no rows created")
        if raw_count <= 0:
            raise RuntimeError("ims_raw_data insert failed: no rows created")

        summary_with_value_share = db.session.query(IMSSummary).filter(IMSSummary.value_share.is_not(None)).count()
        if summary_with_value_share <= 0:
            raise RuntimeError("value_share insert failed for ims_summary")

        stage_names = {item.get("stage") for item in captured_stage_payloads}
        expected_stages = {
            "workbook_rows_read",
            "parsed_rows",
            "detected_representatives",
            "skipped_rows",
            "staged_raw_rows",
            "created_raw_records",
            "created_facts",
            "created_summaries",
        }
        missing_stages = sorted(expected_stages - stage_names)
        if missing_stages:
            raise RuntimeError(f"Stage statistics/logging missing: {missing_stages}")

        return {
            "success": True,
            "database_url": db_url,
            "sample_workbook": str(sample_path),
            "upload_id": result.get("upload_id"),
            "counts": {
                "ims_raw_data": raw_count,
                "ims_facts": fact_count,
                "ims_summary": summary_count,
                "ims_summary_value_share_non_null": summary_with_value_share,
            },
            "stage_metrics_count": len(captured_stage_payloads),
            "statistics": result.get("statistics", {}),
        }


def main() -> int:
    temp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(temp_dir.name) / "sample-import-validation.db"
        db_url = os.getenv("DATABASE_URL", f"sqlite:///{db_path}")
        report = run_validation(db_url=db_url)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"[validate_sample_import] FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        temp_dir.cleanup()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
