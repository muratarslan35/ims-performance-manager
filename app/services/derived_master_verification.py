"""Semantic derived/master verification gate.

Business identity is semantic; sheet/cell coordinates are audit metadata only.
Independent pivots remain explicit masters when no upstream equivalent exists.
Once a high-confidence relationship is discovered, any value mismatch or small
missing-cell gap fails closed before publication.
"""
from app.services.compiled_import_semantic_reconciliation import (
    CompiledWorkbookSemanticReconciler,
)


def apply_derived_verification_gate(importer):
    return CompiledWorkbookSemanticReconciler(importer).reconcile()


def install_derived_verification_gate():
    """Run semantic reconciliation after parsers and before transaction commit."""
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_derived_verification_gate_installed", False):
        return
    original_process = IMSImportService.process_workbook
    original_report = IMSImportService.report

    def process_with_derived_gate(self, year, month, week_number=None):
        result = original_process(self, year, month, week_number=week_number)
        self.semantic_reconciliation = apply_derived_verification_gate(self)
        return result

    def report_with_semantic_reconciliation(self):
        report = original_report(self)
        report["semantic_reconciliation"] = getattr(self, "semantic_reconciliation", None)
        report["semantic_relationships"] = getattr(self, "semantic_relationships", [])
        return report

    IMSImportService.process_workbook = process_with_derived_gate
    IMSImportService.report = report_with_semantic_reconciliation
    IMSImportService._derived_verification_gate_installed = True
