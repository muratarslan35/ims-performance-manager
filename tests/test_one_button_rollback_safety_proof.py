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


def test_current_delete_is_not_exact_whole_state_rollback_when_import_creates_master_rows_and_snapshots():
    """Characterization proof; no production behavior is changed by this test.

    A real wrong workbook may create master identities/aliases and durable read
    model generations in addition to upload-owned raw/fact rows.  The existing
    delete path correctly restores period current-state rows, but it does not
    claim to reverse every such side effect.  Therefore it must not be promoted
    as a 100% one-button rollback mechanism without a stronger isolation design.
    """
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
        db.session.add_all([
            Target(
                year=2035, month=4, quarter="Q2", representative_id=rep17.id,
                product_id=product17.id, unit_target=100, tl_target=1000,
                unit_realization=70, tl_realization=700,
            ),
            IMSSummary(
                upload_id=week17.id, year=2035, month=4, quarter="Q2",
                representative_id=rep17.id, product_id=product17.id,
                unit=70, tl=700, target_unit=100, target_tl=1000,
            ),
            RepresentativeBrickAssignment(
                representative_id=rep17.id, year=2035, month=4, quarter="Q2",
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
        IMSUploadLifecycleService.capture_period_snapshot(job_id=job.id, year=2035, month=4)

        # Simulate importer side effects that are not upload-owned children.
        bad_rep = Representative(rep_code="BAD18", rep_name="BAD WEEK18 REP", region="901", active=True)
        bad_product = Product(product_code="BAD18P", product_name="BAD WEEK18 PRODUCT", is_active=True)
        db.session.add_all([bad_rep, bad_product])
        db.session.flush()
        db.session.add_all([
            RepresentativeAlias(representative_id=bad_rep.id, alias_name="BAD18 ALIAS"),
            ProductAlias(product_id=bad_product.id, alias_name="BAD18 PRODUCT ALIAS"),
        ])

        week18 = IMSUpload(
            file_name="18.Hafta-YANLIS.xlsx", year=2035, month=4, quarter="Q2", week_number=18,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(week18)
        db.session.flush()

        target = Target.query.filter_by(year=2035, month=4, representative_id=rep17.id, product_id=product17.id).one()
        summary = IMSSummary.query.filter_by(year=2035, month=4, representative_id=rep17.id, product_id=product17.id).one()
        target.unit_realization = 88
        target.tl_realization = 880
        summary.upload_id = week18.id
        summary.unit = 88
        summary.tl = 880

        raw = IMSRawData(
            upload_id=week18.id, year=2035, month=4, quarter="Q2", week_number=18,
            sheet_name="TEST", sheet_type="weekly", representative_id=bad_rep.id,
            product_id=bad_product.id, representative=bad_rep.rep_name,
            product=bad_product.product_name, unit=1, tl=10, raw_json="{}",
        )
        db.session.add(raw)
        db.session.flush()
        db.session.add(IMSFact(
            upload_id=week18.id, raw_data_id=raw.id, representative_id=bad_rep.id,
            product_id=bad_product.id, year=2035, month=4, quarter="Q2", week_number=18,
            report_type="weekly_sales", unit=1, tl=10, metrics_json="{}",
        ))

        region_set_id = db.session.execute(region_snapshot_sets.insert().values(
            year=2035, month=4, source_upload_id=week18.id, production_upload_id=0,
            status="ACTIVE", region_count=1,
        )).inserted_primary_key[0]
        db.session.execute(region_snapshots.insert().values(
            set_id=region_set_id, region_key="901", payload_json=json.dumps({"bad18": True}),
        ))
        rep_set_id = db.session.execute(representative_snapshot_sets.insert().values(
            year=2035, month=4, source_upload_id=week18.id, production_upload_id=0,
            status="ACTIVE", representative_count=1,
        )).inserted_primary_key[0]
        db.session.execute(representative_snapshots.insert().values(
            set_id=rep_set_id, representative_id=bad_rep.id, payload_json=json.dumps({"bad18": True}),
        ))

        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = week18.id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=week18.id)

        result = IMSUploadLifecycleService.delete_upload(week18.id)
        assert result["restored_previous_period_state"] is True

        # Existing lifecycle does restore the authoritative period rows.
        restored_target = Target.query.filter_by(
            year=2035, month=4, representative_id=rep17.id, product_id=product17.id
        ).one()
        restored_summary = IMSSummary.query.filter_by(
            year=2035, month=4, representative_id=rep17.id, product_id=product17.id
        ).one()
        assert restored_target.unit_realization == 70
        assert restored_target.tl_realization == 700
        assert restored_summary.upload_id == week17.id
        assert restored_summary.unit == 70
        assert IMSRawData.query.filter_by(upload_id=week18.id).count() == 0
        assert IMSFact.query.filter_by(upload_id=week18.id).count() == 0

        after = _business_state()
        mismatched = sorted(name for name in baseline if baseline[name] != after[name])

        # This is the decisive safety result: an exact whole-state rollback is
        # NOT true today.  The test passes only when that unsafe assumption is
        # exposed rather than hidden.
        assert "representatives" in mismatched
        assert "products" in mismatched
        assert "representative_aliases" in mismatched
        assert "product_aliases" in mismatched
        assert "manager_region_snapshot_sets" in mismatched
        assert "representative_snapshot_sets" in mismatched
        print("ROLLBACK_PROOF|CURRENT_ONE_BUTTON_ROLLBACK_SAFE|NO")
        print("ROLLBACK_PROOF|EXACT_STATE_MISMATCH_TABLES|" + ",".join(mismatched))
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()
