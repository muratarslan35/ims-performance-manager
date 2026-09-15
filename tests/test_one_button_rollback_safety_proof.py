from pathlib import Path
import json
import tempfile

from app import create_app
from app.extensions import db
from app.models import (
    IMSFact,
    IMSImportJob,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Product,
    ProductAlias,
    Representative,
    RepresentativeAlias,
    RepresentativeBrickAssignment,
    Target,
)
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.persistent_region_snapshot_service import (
    region_snapshot_sets,
    region_snapshots,
)
from app.services.persistent_representative_snapshot_service import (
    representative_snapshot_sets,
    representative_snapshots,
)


class RollbackProofConfig:
    TESTING = True
    SECRET_KEY = "rollback-proof"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "ims-rollback-proof-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "ims-rollback-proof-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "ims-rollback-proof-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "ims-rollback-proof-logs"


def _rows(table):
    rows = db.session.execute(table.select().order_by(*table.primary_key.columns)).mappings().all()
    normalized = []
    for row in rows:
        normalized.append({
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in row.items()
        })
    return normalized


def _business_state():
    """Tables whose exact equality matters for a zero-risk rollback claim."""
    tables = (
        Representative.__table__,
        RepresentativeAlias.__table__,
        Product.__table__,
        ProductAlias.__table__,
        Target.__table__,
        IMSSummary.__table__,
        RepresentativeBrickAssignment.__table__,
        region_snapshot_sets,
        region_snapshots,
        representative_snapshot_sets,
        representative_snapshots,
    )
    return {table.name: _rows(table) for table in tables}


def _state_diff(before, after):
    result = {}
    for name in sorted(before):
        if before[name] == after[name]:
            continue
        before_rows = before[name]
        after_rows = after[name]
        result[name] = {
            "before_count": len(before_rows),
            "after_count": len(after_rows),
            "before": before_rows,
            "after": after_rows,
        }
    return result


def test_current_delete_is_not_exact_whole_state_rollback_when_import_creates_master_rows_and_snapshots():
    """Characterize exact rollback behavior without changing production code."""
    app = create_app(RollbackProofConfig)
    ctx = app.app_context()
    ctx.push()
    try:
        db.create_all()

        rep17 = Representative(rep_code="SAFE17", rep_name="SAFE WEEK17 REP", region="901", active=True)
        product17 = Product(product_code="SAFE17P", product_name="SAFE WEEK17 PRODUCT", is_active=True)
        week17 = IMSUpload(
            file_name="17.Hafta.xlsx", year=2035, month=4, quarter="Q2", week_number=17,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add_all([rep17, product17, week17])
        db.session.flush()
        week17_id = int(week17.id)
        rep17_id = int(rep17.id)
        product17_id = int(product17.id)
        db.session.add_all([
            Target(
                year=2035, month=4, quarter="Q2", representative_id=rep17_id,
                product_id=product17_id, unit_target=100, tl_target=1000,
                unit_realization=70, tl_realization=700,
            ),
            IMSSummary(
                upload_id=week17_id, year=2035, month=4, quarter="Q2",
                representative_id=rep17_id, product_id=product17_id,
                unit=70, tl=700, target_unit=100, target_tl=1000,
            ),
            RepresentativeBrickAssignment(
                representative_id=rep17_id, year=2035, month=4, quarter="Q2",
                brick="901 SAFE", source="IMS", active=True,
            ),
        ])
        db.session.commit()

        baseline = _business_state()

        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name="18.Hafta-YANLIS.xlsx",
            stored_file_name="bad18.xlsx",
            source_hash="1" * 64,
            year=2035,
            month=4,
            clear_before_import=False,
            uploaded_by="rollback-proof",
        )
        db.session.add(job)
        db.session.flush()
        job_id = int(job.id)
        IMSUploadLifecycleService.capture_period_snapshot(job_id=job_id, year=2035, month=4)

        bad_rep = Representative(rep_code="BAD18", rep_name="BAD WEEK18 REP", region="901", active=True)
        bad_product = Product(product_code="BAD18P", product_name="BAD WEEK18 PRODUCT", is_active=True)
        db.session.add_all([bad_rep, bad_product])
        db.session.flush()
        bad_rep_id = int(bad_rep.id)
        bad_product_id = int(bad_product.id)
        db.session.add_all([
            RepresentativeAlias(representative_id=bad_rep_id, alias_name="BAD18 ALIAS"),
            ProductAlias(product_id=bad_product_id, alias_name="BAD18 PRODUCT ALIAS"),
        ])

        week18 = IMSUpload(
            file_name="18.Hafta-YANLIS.xlsx", year=2035, month=4, quarter="Q2", week_number=18,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(week18)
        db.session.flush()
        week18_id = int(week18.id)

        target = Target.query.filter_by(
            year=2035, month=4, representative_id=rep17_id, product_id=product17_id
        ).one()
        summary = IMSSummary.query.filter_by(
            year=2035, month=4, representative_id=rep17_id, product_id=product17_id
        ).one()
        target.unit_realization = 88
        target.tl_realization = 880
        summary.upload_id = week18_id
        summary.unit = 88
        summary.tl = 880

        raw = IMSRawData(
            upload_id=week18_id, year=2035, month=4, quarter="Q2", week_number=18,
            sheet_name="TEST", sheet_type="weekly", representative_id=bad_rep_id,
            product_id=bad_product_id, representative="BAD WEEK18 REP",
            product="BAD WEEK18 PRODUCT", unit=1, tl=10, raw_json="{}",
        )
        db.session.add(raw)
        db.session.flush()
        raw_id = int(raw.id)
        db.session.add(IMSFact(
            upload_id=week18_id, raw_data_id=raw_id, representative_id=bad_rep_id,
            product_id=bad_product_id, year=2035, month=4, quarter="Q2", week_number=18,
            report_type="weekly_sales", unit=1, tl=10, metrics_json="{}",
        ))

        region_set_id = db.session.execute(region_snapshot_sets.insert().values(
            year=2035, month=4, source_upload_id=week18_id, production_upload_id=0,
            status="ACTIVE", region_count=1,
        )).inserted_primary_key[0]
        db.session.execute(region_snapshots.insert().values(
            set_id=region_set_id, region_key="901", payload_json=json.dumps({"bad18": True}),
        ))
        rep_set_id = db.session.execute(representative_snapshot_sets.insert().values(
            year=2035, month=4, source_upload_id=week18_id, production_upload_id=0,
            status="ACTIVE", representative_count=1,
        )).inserted_primary_key[0]
        db.session.execute(representative_snapshots.insert().values(
            set_id=rep_set_id, representative_id=bad_rep_id, payload_json=json.dumps({"bad18": True}),
        ))

        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = week18_id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job_id, upload_id=week18_id)

        result = IMSUploadLifecycleService.delete_upload(week18_id)
        assert result["restored_previous_period_state"] is True

        restored_target = Target.query.filter_by(
            year=2035, month=4, representative_id=rep17_id, product_id=product17_id
        ).one()
        restored_summary = IMSSummary.query.filter_by(
            year=2035, month=4, representative_id=rep17_id, product_id=product17_id
        ).one()
        assert restored_target.unit_realization == 70
        assert restored_target.tl_realization == 700
        assert restored_summary.upload_id == week17_id
        assert restored_summary.unit == 70
        assert IMSRawData.query.filter_by(upload_id=week18_id).count() == 0
        assert IMSFact.query.filter_by(upload_id=week18_id).count() == 0
        assert db.session.get(IMSUpload, week18_id) is None

        after = _business_state()
        diff = _state_diff(baseline, after)
        mismatched = sorted(diff)

        # Emit machine-readable evidence before asserting the safety verdict.
        print("ROLLBACK_PROOF|CURRENT_ONE_BUTTON_ROLLBACK_SAFE|" + ("YES" if not mismatched else "NO"))
        print("ROLLBACK_PROOF|EXACT_STATE_MISMATCH_TABLES|" + ",".join(mismatched))
        print("ROLLBACK_PROOF|EXACT_STATE_DIFF|" + json.dumps(diff, ensure_ascii=False, sort_keys=True))

        # Existing lifecycle is not an exact whole-state rollback if these
        # import-created shared/master or durable snapshot rows survive.
        expected_survivors = {
            "representatives",
            "products",
            "representative_aliases",
            "product_aliases",
            "manager_region_snapshot_sets",
            "manager_region_snapshots",
            "representative_snapshot_sets",
            "representative_snapshots",
        }
        assert expected_survivors.issubset(set(mismatched))
        assert "targets" not in mismatched
        assert "ims_summary" not in mismatched
        assert "representative_brick_assignments" not in mismatched
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()
