"""Small acceptance probe for the guarded Week 33 retry."""
from __future__ import annotations

import argparse
import json

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSRawData, IMSUpload, Product
from app.services.official_brick_spread_service import OfficialBrickSpreadService
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    app = create_app(Config)
    with app.app_context():
        if args.status:
            job = IMSImportJob.query.order_by(IMSImportJob.id.desc()).first()
            print("MISSING" if job is None else job.status)
            return 0

        upload = IMSUpload.query.filter_by(
            year=2026, month=8, week_number=33, status="COMPLETED"
        ).order_by(IMSUpload.id.desc()).first()
        assert upload and upload.id == 46, getattr(upload, "id", None)
        job = IMSImportJob.query.filter_by(ims_upload_id=upload.id).order_by(
            IMSImportJob.id.desc()
        ).first()
        assert job and job.status == IMSImportJob.STATUS_COMPLETED, getattr(job, "status", None)
        fentivag = Product.query.filter(db.func.upper(Product.product_name) == "FENTIVAG").first()
        assert fentivag
        rows = IMSRawData.query.filter_by(
            upload_id=upload.id,
            sheet_type=OfficialBrickSpreadService.SHEET_TYPE,
            product="Fentivag",
        ).all()
        assert rows and all(float(row.unit or 0) == 0 for row in rows), len(rows)
        payloads = [json.loads(row.raw_json or "{}") for row in rows]
        assert all(item.get("intentional_product_absence") is True for item in payloads)
        print(
            f"WEEK33_INTENTIONAL_ABSENCE|PASS|upload={upload.id}|"
            f"product=Fentivag|zero_rows={len(rows)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
