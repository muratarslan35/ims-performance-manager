from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]


def test_import_progress_reserves_time_for_representative_snapshots():
    queue = (ROOT / "app/services/ims_import_queue.py").read_text(encoding="utf-8")
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert '"commit_upload": (39, 40' in queue
    assert "value = 46 + round(48 * done / max(total, 1))" in worker
    assert "recent_seconds = deque(maxlen=12)" in worker


def test_representative_roster_comes_from_exact_ims_upload():
    source = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")
    assert "IMSRawData.upload_id == upload_id" in source
    assert "Target.year == int(year)" not in source
    assert "for offset in range(0, len(build_ids), batch_size)" in source
    assert "db.session.execute(representative_snapshots.insert(), [" in source


def test_publication_is_atomic_and_notice_is_per_user():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    layout = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    publish = worker[worker.index("def _prepare_and_publish"):]
    assert publish.index("dashboard_result = _warm_dashboard_snapshot") < publish.index("region_result = _warm_region_snapshots")
    assert publish.index("region_result = _warm_region_snapshots") < publish.index("representative_result = _warm_representative_snapshots(")
    assert 'summary["publication_ready"] = True' in worker
    assert 'completed = db.session.get(IMSImportJob, job_id)' in worker
    assert 'summary["publication_ready_upload_id"]' in worker
    assert 'stage="snapshot_retry"' in worker
    assert '"ims_publication_receipts"' in service
    assert "upload = cls.latest_visible_upload()" in service
    assert '"commit_upload", "final_checks", "read_models"' in service
    assert 'pending_progress.get("stage") in committed_unlinked_stages' in service
    assert "checkPublishedIMSNotice();" in layout
    assert "window.setInterval(checkPublishedIMSNotice, 15000);" in layout
    assert "ims-published-notice-layer" in layout
    assert "Yeni IMS başarıyla yüklendi" in layout
    assert "aria-modal" in layout


def test_notice_selects_current_visible_upload_not_historical_ready_job():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    notice_block = service[service.index("def notice_for_user"):service.index("def dismiss", service.index("def notice_for_user"))]
    assert "upload = cls.latest_visible_upload()" in notice_block
    assert "latest_ready_job" not in notice_block
    assert "db.session.get(IMSUpload" not in notice_block


def test_publication_receipt_does_not_hide_a_recycled_upload_id():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    assert "def _has_current_receipt" in service
    assert "ims_publication_receipts.c.dismissed_at" in service
    assert "dismissed_at.replace(microsecond=0)" in service
    assert "upload_ready_at.replace(microsecond=0)" in service
    assert "dismissed_second >= upload_ready_second" in service
    assert "ims_publication_receipts.delete().where(" in service
    assert "if cls._has_current_receipt(user_id, upload):" in service
    assert "upload is None or cls._has_current_receipt(user_id, upload)" in service

def test_all_user_facing_snapshot_layers_stay_on_previous_generation_until_publish():
    dashboard = (ROOT / "app/services/persistent_dashboard_snapshot_service.py").read_text(encoding="utf-8")
    regions = (ROOT / "app/services/persistent_region_snapshot_service.py").read_text(encoding="utf-8")
    representatives = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")

    assert "IMSPublicationService.pending_job(year, month) is not None" in dashboard
    assert "IMSPublicationService.latest_visible_upload(year, month)" in dashboard
    assert "return int(previous) if previous else None" in regions
    assert "return int(previous) if previous else None" in representatives
    assert "get_generation_for_source" in worker

    publish = worker[worker.index("def _prepare_and_publish"):]
    ready_index = publish.index("ready = (")
    publication_index = publish.index('summary["publication_ready"] = True')
    complete_index = publish.index('percent=100, stage="completed"')
    assert ready_index < publication_index < complete_index

def test_region_enrichment_uses_exact_hidden_snapshot_generations():
    regions = (ROOT / "app/services/persistent_region_snapshot_service.py").read_text(encoding="utf-8")
    representatives = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")

    enrich = regions[regions.index("def enrich_for_period"):regions.index("def build_for_period", regions.index("def enrich_for_period"))]
    assert "cls._existing_set(year, month, ims_id, production_id)" in enrich
    assert "get_exact_active_many" in enrich
    assert "get_generation_for_source" in enrich
    assert "get_stable(year, month)" not in enrich
    assert "def get_exact_active_many" in representatives


def test_progress_reaches_100_only_after_all_snapshot_layers_and_enrichment():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    publish = worker[worker.index("def _prepare_and_publish"):]
    representative = publish.index("representative_result = _warm_representative_snapshots")
    enrichment = publish.index("PersistentRegionSnapshotService.enrich_for_period")
    ready = publish.index("ready = (")
    complete = publish.index('percent=100, stage="completed"')
    assert representative < enrichment < ready < complete

def test_release_transition_finalizer_repairs_only_fully_published_exact_generation():
    script = (ROOT / "scripts/finalize_latest_snapshot_publication.py").read_text(
        encoding="utf-8"
    )
    assert 'progress.get("stage") == "completed"' in script
    assert 'int(progress.get("percent") or 0) == 100' in script
    assert 'summary["publication_ready"] = True' in script
    assert '"verified_atomic_snapshot_finalizer"' in script
    assert "PersistentDashboardSnapshotService.generation_ready" in script
    assert "PersistentRegionSnapshotService._existing_set" in script
    assert "PersistentRepresentativeSnapshotService._latest_exact_active" in script
    assert "PersistentRegionSnapshotService.enrich_for_period" in script
    assert "LATEST_SNAPSHOT_FINALIZE|PASS" in script
    assert "Path(__file__).resolve().parents[1]" in script
    assert "sys.path.insert(0, str(ROOT))" in script
    compile(script, "scripts/finalize_latest_snapshot_publication.py", "exec")

def test_completed_progress_without_db_publication_marker_stays_pending():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(
        encoding="utf-8"
    )
    pending = service[
        service.index("def pending_job"):
        service.index("def latest_visible_upload")
    ]
    assert "stored = IMSProgressStore.read(job.id)" in pending
    assert 'stored.get("stage") == "completed"' in pending
    assert 'int(stored.get("percent") or 0) == 100' in pending
    assert 'summary.get("publication_ready") is not True' in pending
    assert "return job" in pending


def test_worker_reattaches_completed_job_before_atomic_publication():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    publish = worker[worker.index("def _prepare_and_publish"):]
    reattach = publish.index("completed = db.session.get(IMSImportJob, job_id)")
    marker = publish.index('summary["publication_ready"] = True')
    commit = publish.index("db.session.commit()", marker)
    complete = publish.index('percent=100, stage="completed"')
    assert reattach < marker < commit < complete

def test_only_newest_job_can_hold_publication_gate():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(
        encoding="utf-8"
    )
    pending = service[
        service.index("def pending_job"):
        service.index("def latest_visible_upload")
    ]
    assert ".order_by(" in pending
    assert ".first()" in pending
    assert ".limit(5)" not in pending
    assert "Older interrupted" in pending
    assert "job = query.order_by" in pending

