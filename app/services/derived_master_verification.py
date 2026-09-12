"""Semantic derived/master verification gate.

Business identity is semantic; sheet/cell coordinates are audit metadata only.
Independent pivots remain explicit masters when no upstream equivalent exists.
Once a high-confidence relationship is discovered, any value mismatch or small
missing-cell gap fails closed before publication.
"""
# Production acceptance trigger after Week 32 publication: 2026-09-12.
import time

from app.services.compiled_import_semantic_reconciliation import (
    CompiledWorkbookSemanticReconciler,
)


def apply_derived_verification_gate(importer):
    return CompiledWorkbookSemanticReconciler(importer).reconcile()


def _seed_adaptive_official_aggregates(importer, year, month):
    """Seed source-authoritative KPI aggregates before the legacy reconcile gate.

    The temporary KPI workbook places the region subtotal marker outside the
    legacy brick column. The adaptive reader already resolves those rows by
    semantic identity (region == representative). Persist that exact source
    view before the existing official reconciliation runs; legacy workbooks are
    untouched because _pair_views returns None for them.
    """
    from app.services.adaptive_kpi_target_authority import _pair_views
    from app.services import official_aggregate_service as official

    views = _pair_views(importer)
    if views is None:
        return

    product_map = {}
    for product_name in views["products"]:
        match = importer.resolve_product_match(product_name)
        if not match.get("matched"):
            raise ValueError(f"Adaptive IMS: aggregate ürün eşleşmedi: {product_name}")
        product_map[product_name] = int(match["object"].id)

    target_written = actual_written = 0
    for identity, tl_values in views["tl_aggregates"].items():
        territory, representative = identity
        unit_values = views["unit_aggregates"][identity]
        for product_name, product_id in product_map.items():
            official._upsert(
                importer, year, month, views["tl_name"], official.TARGET_TYPE,
                territory, representative, product_id,
                unit_values[product_name]["target"], tl_values[product_name]["target"],
                {"source": "adaptive paired IMS matrix", "metric": "target"},
            )
            official._upsert(
                importer, year, month, views["tl_name"], official.ACTUAL_TYPE,
                territory, representative, product_id,
                unit_values[product_name]["actual"], tl_values[product_name]["actual"],
                {"source": "adaptive paired IMS matrix", "metric": "actual"},
            )
            target_written += 1
            actual_written += 1

    importer.statistics["adaptive_pre_reconcile_target_records"] = target_written
    importer.statistics["adaptive_pre_reconcile_actual_records"] = actual_written
    official.db.session.flush()


def install_derived_verification_gate():
    """Run semantic reconciliation after parsers and before transaction commit."""
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_derived_verification_gate_installed", False):
        return
    original_process = IMSImportService.process_workbook
    original_report = IMSImportService.report
    original_dashboard = IMSImportService.persist_national_dashboard_metrics

    def persist_dashboard_with_adaptive_seed(self, year, month):
        _seed_adaptive_official_aggregates(self, year, month)
        return original_dashboard(self, year, month)

    def process_with_derived_gate(self, year, month, week_number=None):
        result = original_process(self, year, month, week_number=week_number)
        started = time.monotonic()
        try:
            self.semantic_reconciliation = apply_derived_verification_gate(self)
        finally:
            self.statistics["semantic_reconciliation_seconds"] = round(time.monotonic() - started, 4)
        return result

    def report_with_semantic_reconciliation(self):
        report = original_report(self)
        report["semantic_reconciliation"] = getattr(self, "semantic_reconciliation", None)
        report["semantic_relationships"] = getattr(self, "semantic_relationships", [])
        return report

    IMSImportService.persist_national_dashboard_metrics = persist_dashboard_with_adaptive_seed
    IMSImportService.process_workbook = process_with_derived_gate
    IMSImportService.report = report_with_semantic_reconciliation
    IMSImportService._derived_verification_gate_installed = True
