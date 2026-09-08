"""Exercise instant rollback and cleanup against an isolated production DB copy."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import (
    CompetitionData,
    IMSFact,
    IMSImportJob,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Product,
    Representative,
    RepresentativeBrickAssignment,
    Target,
)
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def _rows(model, year: int, month: int):
    values = []
    for row in model.query.filter_by(year=year, month=month).all():
        values.append({column.name: getattr(row, column.name) for column in row.__table__.columns})
    return sorted(values, key=lambda row: json.dumps(row, sort_keys=True, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--upload-root", required=True)
    args = parser.parse_args()
    database = Path(args.database).resolve()
    upload_root = Path(args.upload_root).resolve()

    class ProofConfig:
        TESTING = True
        SECRET_KEY = "isolated-rollback-proof"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        STRICT_SCHEMA_VALIDATION = False
        UPLOAD_FOLDER = upload_root
        REPORT_FOLDER = upload_root / "reports"
        BACKUP_FOLDER = upload_root / "backups"
        LOG_FOLDER = upload_root / "logs"
        TEMP_FOLDER = upload_root / "temp"
        USER_VAULT_PATH = upload_root / "users-proof.db"

    app = create_app(ProofConfig)
    bad_upload_id = 0
    with app.app_context():
        previous = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
            IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
            IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
        ).first()
        assert previous is not None
        year, month = int(previous.year), int(previous.month)
        before = {
            "targets": _rows(Target, year, month),
            "summaries": _rows(IMSSummary, year, month),
            "assignments": _rows(RepresentativeBrickAssignment, year, month),
        }
        assert before["targets"] and before["summaries"] and before["assignments"]

        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name="isolated-bad-next-week.xlsx",
            stored_file_name="isolated-bad-next-week.xlsx",
            source_hash="f" * 64,
            year=year,
            month=month,
            clear_before_import=True,
            uploaded_by="SHADOW_PROOF",
        )
        db.session.add(job)
        db.session.flush()
        IMSUploadLifecycleService.capture_period_snapshot(
            job_id=job.id, year=year, month=month
        )
        readiness_started = time.monotonic()
        readiness = IMSUploadLifecycleService.prepare_previous_rollback_assets(
            year=year, month=month
        )
        readiness_seconds = time.monotonic() - readiness_started
        assert readiness["status"] == "READY", readiness
        assert readiness["source_upload_id"] == int(previous.id)

        bad = IMSUpload(
            file_name=job.file_name,
            year=year,
            month=month,
            quarter=previous.quarter,
            week_number=int(previous.week_number or 0) + 1,
            status=IMSUpload.STATUS_COMPLETED,
            reconciliation_status="PASSED",
            uploaded_by="SHADOW_PROOF",
        )
        db.session.add(bad)
        db.session.flush()
        bad_upload_id = int(bad.id)
        summary = IMSSummary.query.filter_by(year=year, month=month).first()
        target = Target.query.filter_by(year=year, month=month).first()
        representative = db.session.get(Representative, int(summary.representative_id))
        product = db.session.get(Product, int(summary.product_id))
        assert target is not None and representative is not None and product is not None
        summary.upload_id = bad_upload_id
        summary.unit = float(summary.unit or 0) + 12345.0
        target.unit_realization = float(target.unit_realization or 0) + 12345.0
        representative.active = not bool(representative.active)

        wrong_rep = Representative(
            rep_code=f"SHADOW-WRONG-{bad_upload_id}",
            rep_name="SHADOW WRONG REPRESENTATIVE",
            active=True,
        )
        wrong_product = Product(
            product_code=f"SHADOW-WRONG-{bad_upload_id}",
            product_name="SHADOW WRONG PRODUCT",
            is_active=True,
        )
        db.session.add_all((wrong_rep, wrong_product))
        db.session.flush()
        wrong_rep_id, wrong_product_id = int(wrong_rep.id), int(wrong_product.id)
        raw = IMSRawData(
            upload_id=bad_upload_id,
            year=year,
            month=month,
            quarter=previous.quarter,
            week_number=bad.week_number,
            sheet_name="SHADOW",
            sheet_type="weekly",
            representative_id=wrong_rep_id,
            product_id=wrong_product_id,
            representative=wrong_rep.rep_name,
            product=wrong_product.product_name,
            unit=1.0,
            tl=1.0,
            source_row=1,
            raw_json="{}",
        )
        db.session.add(raw)
        db.session.flush()
        db.session.add(IMSFact(
            upload_id=bad_upload_id,
            raw_data_id=raw.id,
            representative_id=wrong_rep_id,
            product_id=wrong_product_id,
            year=year,
            month=month,
            quarter=previous.quarter,
            week_number=bad.week_number,
            report_type="weekly_sales",
            unit=1.0,
            tl=1.0,
            metrics_json="{}",
        ))
        db.session.add(CompetitionData(
            upload_id=bad_upload_id,
            year=year,
            month=month,
            week_number=bad.week_number,
            sheet_name="SHADOW PP",
            period_type="weekly",
            territory="SHADOW",
            subterritory="SHADOW",
            product_group="SHADOW",
            product_name="SHADOW",
            metric_type="MARKET_SHARE",
            metric_value=99.0,
            source_row=1,
        ))
        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = bad_upload_id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=bad_upload_id)
        IMSUploadLifecycleService.seal_snapshot_master_state(upload_id=bad_upload_id)

        rollback_started = time.monotonic()
        rollback = IMSUploadLifecycleService.rollback_to_previous(
            bad_upload_id, actor="SHADOW_PROOF"
        )
        rollback_seconds = time.monotonic() - rollback_started
        assert rollback["active_upload_id"] == int(previous.id)
        assert db.session.get(IMSUpload, bad_upload_id).status == IMSUpload.STATUS_ROLLED_BACK
        assert _rows(Target, year, month) == before["targets"]
        assert _rows(IMSSummary, year, month) == before["summaries"]
        assert _rows(RepresentativeBrickAssignment, year, month) == before["assignments"]
        assert db.session.get(Representative, wrong_rep_id).active is False
        assert db.session.get(Product, wrong_product_id).is_active is False

        cleanup_started = time.monotonic()
        cleanup = IMSUploadLifecycleService.delete_upload(bad_upload_id)
        cleanup_seconds = time.monotonic() - cleanup_started
        assert cleanup["master_cleanup"]["representatives_deleted"] == 1
        assert cleanup["master_cleanup"]["products_deleted"] == 1
        assert db.session.get(IMSUpload, bad_upload_id) is None
        assert db.session.get(Representative, wrong_rep_id) is None
        assert db.session.get(Product, wrong_product_id) is None
        assert IMSRawData.query.filter_by(upload_id=bad_upload_id).count() == 0
        assert IMSFact.query.filter_by(upload_id=bad_upload_id).count() == 0
        assert CompetitionData.query.filter_by(upload_id=bad_upload_id).count() == 0
        print(
            "ROLLBACK_MODULE_PROOF|PASS|"
            f"previous_upload_id={previous.id}|synthetic_upload_id={bad_upload_id}|"
            f"targets={len(before['targets'])}|summaries={len(before['summaries'])}|"
            f"assignments={len(before['assignments'])}|"
            f"readiness_seconds={readiness_seconds:.3f}|"
            f"rollback_seconds={rollback_seconds:.3f}|cleanup_seconds={cleanup_seconds:.3f}"
        )

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()
if __name__ == "__main__":
    main()
