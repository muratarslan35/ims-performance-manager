from types import SimpleNamespace

from app.services.workbook_semantic_reconciliation import WorkbookSemanticReconciler
from app.services.compiled_import_semantic_reconciliation import CompiledWorkbookSemanticReconciler


def _reconciler(cls=WorkbookSemanticReconciler, frame=None):
    importer = SimpleNamespace(
        workbook={"TTS-KUTU PP": frame} if frame is not None else {},
        workbook_manifest=[],
    )
    return cls(importer)


def test_market_share_is_a_metric_header_not_a_product_name():
    reconciler = _reconciler()

    # Newer workbook exports may put the metric caption after the product
    # header. The product identity must come from the actual product label.
    assert reconciler._is_metadata_part("MARKET SHARE") is True
    assert reconciler._metric_family(["MARKET SHARE"], ["MARKET SHARE"]) == "share"
    assert reconciler._product_key(
        ["TRAVAZOL KREM", "MARKET SHARE"],
        ["TRAVAZOL KREM", "MARKET SHARE"],
    ) == "TRAVAZOL KREM"


def test_explicit_calendar_headers_get_distinct_period_scopes():
    reconciler = _reconciler()

    october = reconciler._period_scope(["OCTOBER 2026"], ["OCTOBER 2026"], None)
    september = reconciler._period_scope(["SEPTEMBER 2026"], ["SEPTEMBER 2026"], None)

    assert october == "calendar:OCTOBER 2026"
    assert september == "calendar:SEPTEMBER 2026"
    assert october != september


def test_date_range_header_is_metadata_and_scopes_the_column():
    reconciler = _reconciler()
    header = "05.10.2026 - 11.10.2026"

    assert reconciler._is_period_part(header) is True
    assert reconciler._period_scope([header], [header], None).startswith("calendar:")


def test_bare_month_headers_keep_legacy_monthly_scope():
    reconciler = _reconciler()

    assert reconciler._period_scope(["OCTOBER"], ["OCTOBER"], None) == "monthly"


def test_compiled_reconciler_inherits_expanded_header_semantics():
    reconciler = _reconciler(CompiledWorkbookSemanticReconciler)

    assert reconciler._is_metadata_part("MARKET SHARE") is True
    assert reconciler._period_scope(
        ["OCTOBER 2026"], ["OCTOBER 2026"], None
    ) == "calendar:OCTOBER 2026"
