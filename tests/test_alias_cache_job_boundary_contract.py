from pathlib import Path


def test_ims_worker_resets_alias_cache_at_each_job_boundary():
    source = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    assert "from app.services.alias_service import AliasService" in source
    process_start = source.index("def process(cls, job):")
    process_end = source.index("finally:", process_start)
    block = source[process_start:process_end]
    service_create = block.index("service = IMSImportService")
    clear_cache = block.index("AliasService.clear_cache()")
    assert clear_cache < service_create


def test_ims_worker_drops_alias_cache_after_job_finishes():
    source = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    process_start = source.index("def process(cls, job):")
    finally_start = source.index("finally:", process_start)
    block = source[finally_start:]
    assert "AliasService.clear_cache()" in block
