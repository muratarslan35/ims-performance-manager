"""Install previous-IMS delta as a non-blocking, pre-publish audit stage.

The delta is deliberately informational: workbook changes are not failures. The
wrapper runs after all parsers/reconciliation have succeeded but before the
outer IMSImportService.run transaction commits, preserving atomic publication.
"""
from app.services.ims_delta_service import build_previous_ims_delta


def install_previous_ims_delta_audit():
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_previous_ims_delta_audit_installed", False):
        return

    original_process = IMSImportService.process_workbook
    original_report = IMSImportService.report

    def process_with_delta(self, year, month, week_number=None):
        result = original_process(self, year, month, week_number=week_number)
        build_previous_ims_delta(self)
        return result

    def report_with_delta(self):
        report = original_report(self)
        report["previous_ims_delta"] = getattr(self, "previous_ims_delta", None)
        return report

    IMSImportService.process_workbook = process_with_delta
    IMSImportService.report = report_with_delta
    IMSImportService._previous_ims_delta_audit_installed = True
