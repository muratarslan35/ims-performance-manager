from pathlib import Path


def test_worker_clears_alias_cache_before_and_after_import_service():
    source = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    start = source.index("def process(cls, job):")
    end = source.index("staging_path.unlink", start)
    block = source[start:end]
    assert block.count("AliasService.clear_cache()") >= 2
    assert block.index("AliasService.clear_cache()") < block.index("service = IMSImportService")
