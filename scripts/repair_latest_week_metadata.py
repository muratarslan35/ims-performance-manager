"""Repair a completed latest upload whose filename week was previously missed."""
from __future__ import annotations

import argparse
import json

import sqlalchemy as sa

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSFact, IMSImportJob, IMSRawData, IMSUpload, ImportAuditLog
from app.services.ims_import_service import IMSImportService
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    app = create_app(Config)
    with app.app_context():
        upload = IMSUpload.query.order_by(IMSUpload.id.desc()).first()
        if upload is None or (upload.year, upload.month) != (args.year, args.month):
            raise SystemExit("WEEK_METADATA_REFUSED|reason=latest_period_mismatch")
        if upload.status != IMSUpload.STATUS_COMPLETED:
            raise SystemExit("WEEK_METADATA_REFUSED|reason=latest_upload_not_completed")
        detected = IMSImportService.extract_week_number(upload.file_name)
        if detected != args.week:
            raise SystemExit(
                f"WEEK_METADATA_REFUSED|reason=filename_week_mismatch|detected={detected}|requested={args.week}"
            )
        if upload.week_number not in (None, args.week):
            raise SystemExit("WEEK_METADATA_REFUSED|reason=stored_week_conflict")

        job = IMSImportJob.query.filter_by(ims_upload_id=upload.id).order_by(IMSImportJob.id.desc()).first()
        if job is None or job.status != IMSImportJob.STATUS_COMPLETED:
            raise SystemExit("WEEK_METADATA_REFUSED|reason=completed_job_missing")
        if upload.week_number == args.week:
            print(f"WEEK_METADATA|UNCHANGED|upload={upload.id}|week={args.week}")
            return 0

        db.session.rollback()
        db.session.execute(sa.text("BEGIN IMMEDIATE"))
        upload = db.session.get(IMSUpload, upload.id)
        upload.week_number = args.week
        for model in (IMSRawData, IMSFact, CompetitionData, ImportAuditLog):
            model.query.filter_by(upload_id=upload.id).update(
                {model.week_number: args.week}, synchronize_session=False
            )
        try:
            summary = json.loads(job.result_summary or "{}")
        except (TypeError, ValueError):
            summary = {}
        summary["detected_week_number"] = args.week
        job.result_summary = json.dumps(summary, ensure_ascii=False, default=str)
        db.session.commit()
        print(f"WEEK_METADATA|REPAIRED|upload={upload.id}|week={args.week}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
