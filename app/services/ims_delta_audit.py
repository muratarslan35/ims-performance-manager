"""Install previous-IMS delta as a non-blocking, pre-publish audit stage.

The delta is deliberately informational: workbook changes are not failures. The
wrapper captures the existing same-period target state before parsers mutate it,
then calculates the complete previous-IMS delta after all validation succeeds but
before the outer IMSImportService.run transaction commits.
"""
import time

from app.services.ims_delta_service import build_previous_ims_delta, target_snapshot


def install_previous_ims_delta_audit():
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_previous_ims_delta_audit_installed", False):
        return

    original_process = IMSImportService.process_workbook
    original_report = IMSImportService.report

    def process_with_delta(self, year, month, week_number=None):
        # Target is intentionally period-scoped in the existing schema. Keep a
        # preimage so same-month weekly reimports can still report target changes
        # without adding a second target data model or altering prime/dashboard reads.
        self.pre_import_target_snapshot = target_snapshot(year, month)
        result = original_process(self, year, month, week_number=week_number)
        started = time.monotonic()
        try:
            build_previous_ims_delta(self)
        finally:
            self.statistics["previous_ims_delta_seconds"] = round(time.monotonic() - started, 4)
        return result

    def report_with_delta(self):
        report = original_report(self)
        report["previous_ims_delta"] = getattr(self, "previous_ims_delta", None)
        return report

    IMSImportService.process_workbook = process_with_delta
    IMSImportService.report = report_with_delta
    IMSImportService._previous_ims_delta_audit_installed = True
