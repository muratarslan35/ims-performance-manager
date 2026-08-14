#!/usr/bin/env python
"""One-time, idempotent repair for competition data missing from the latest upload."""

from __future__ import annotations

import json
from pathlib import Path

from flask import current_app
from sqlalchemy import desc

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSUpload
from app.services.competition_import_service import CompetitionImportService


def backfill_latest_competition(upload_folder: Path | None = None) -> dict:
    upload = (
        IMSUpload.query.filter_by(status="COMPLETED")
        .order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id))
        .first()
    )
    if upload is None:
        raise RuntimeError("Tamamlanmış IMS yüklemesi bulunamadı.")

    before_count = CompetitionData.query.filter_by(upload_id=upload.id).count()
    nonzero_tl_before = CompetitionData.query.filter(
        CompetitionData.upload_id == upload.id,
        CompetitionData.metric_type == "TL",
        CompetitionData.metric_value != 0,
    ).count()
    if nonzero_tl_before:
        return {
            "status": "already_complete",
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "records_before": before_count,
            "records_after": before_count,
            "nonzero_tl_records": nonzero_tl_before,
        }

    source_path = Path(upload_folder or current_app.config["UPLOAD_FOLDER"]) / upload.file_name
    if not source_path.is_file():
        raise RuntimeError(f"Kaynak IMS dosyası bulunamadı: {source_path}")

    service = CompetitionImportService(
        file_path=str(source_path),
        upload_id=upload.id,
        year=upload.year,
        month=upload.month,
        week_number=upload.week_number,
    )
    result = service.run()
    summary = result.get("summary", {})
    db.session.flush()

    after_count = CompetitionData.query.filter_by(upload_id=upload.id).count()
    nonzero_tl = CompetitionData.query.filter(
        CompetitionData.upload_id == upload.id,
        CompetitionData.metric_type == "TL",
        CompetitionData.metric_value != 0,
    ).count()
    if after_count < before_count or nonzero_tl <= 0:
        db.session.rollback()
        raise RuntimeError(
            "Rekabet verisi geri dolum doğrulaması başarısız: "
            f"before={before_count}, after={after_count}, nonzero_tl={nonzero_tl}"
        )

    db.session.commit()
    return {
        "status": "backfilled",
        "upload_id": upload.id,
        "file_name": upload.file_name,
        "year": upload.year,
        "month": upload.month,
        "records_before": before_count,
        "records_after": after_count,
        "records_inserted": summary.get("total_inserted", 0),
        "source_numeric_cells": summary.get("numeric_cells", 0),
        "nonzero_tl_records": nonzero_tl,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        try:
            report = backfill_latest_competition()
        except Exception as exc:
            db.session.rollback()
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
