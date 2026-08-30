"""Fail-closed reconciliation gate for production result imports.

A production workbook is never allowed to remain APPLIED merely because parsing
and INSERT statements completed.  The staged source report is compared back to
all persisted production-result layers inside the same transaction.  Only an
exact semantic match (with tiny float round-trip tolerance) is finalized green.
"""

import re
from datetime import datetime

from app.extensions import db
from app.models import (
    ProductionNationalProductResult,
    ProductionNationalTotal,
    ProductionRegionProductResult,
    ProductionRegionTotal,
    ProductionRepresentativeTotal,
    ProductionResult,
)
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


_FLOAT_TOLERANCE = 1e-9
_INSTALLED = False
_ORIGINAL_APPLY = ProductionResultImportService.apply
_ORIGINAL_INIT = ProductionResultImportService.__init__


def _equal_number(left, right):
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= _FLOAT_TOLERANCE


def _assert_value(context, field, expected, actual):
    if isinstance(expected, (int, float)) or isinstance(actual, (int, float)):
        if not _equal_number(expected, actual):
            raise ProductionWorkbookValidationError(
                f"Üretim finalizasyon eşleşmesi başarısız: {context}.{field} "
                f"kaynak={expected!r} db={actual!r}."
            )
    elif expected != actual:
        raise ProductionWorkbookValidationError(
            f"Üretim finalizasyon eşleşmesi başarısız: {context}.{field} "
            f"kaynak={expected!r} db={actual!r}."
        )


def _assert_collection(name, expected_rows, actual_rows, key_fields, value_fields):
    expected = {tuple(row[field] for field in key_fields): row for row in expected_rows}
    actual = {tuple(getattr(row, field) for field in key_fields): row for row in actual_rows}
    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))[:5]
        extra = sorted(set(actual) - set(expected))[:5]
        raise ProductionWorkbookValidationError(
            f"Üretim finalizasyon eşleşmesi başarısız: {name} anahtar kapsamı farklı "
            f"(eksik={missing}, fazlalık={extra})."
        )
    for key, source in expected.items():
        stored = actual[key]
        for field in value_fields:
            _assert_value(f"{name}{key}", field, source.get(field), getattr(stored, field))


def _reconcile(upload, report):
    """Compare parsed source semantics against every DB layer before APPLIED."""
    db.session.flush()

    _assert_collection(
        "temsilci_urun",
        report.product_results,
        ProductionResult.query.filter_by(upload_id=upload.id).all(),
        ("representative_id", "product_id"),
        (
            "target_tl", "target_unit", "actual_tl", "actual_unit",
            "realization_percent", "unit_realization_percent", "source_sheet", "source_row",
        ),
    )
    _assert_collection(
        "temsilci_toplam",
        report.representative_totals,
        ProductionRepresentativeTotal.query.filter_by(upload_id=upload.id).all(),
        ("representative_id",),
        (
            "target_tl", "target_unit", "actual_tl", "actual_unit",
            "realization_percent", "unit_realization_percent", "source_sheet", "source_row",
        ),
    )
    _assert_collection(
        "bolge_urun",
        report.region_product_results,
        ProductionRegionProductResult.query.filter_by(upload_id=upload.id).all(),
        ("region_code", "product_id"),
        (
            "target_tl", "target_unit", "actual_tl", "actual_unit",
            "realization_percent", "unit_realization_percent", "source_sheet", "source_row",
        ),
    )
    _assert_collection(
        "bolge_toplam",
        report.region_totals,
        ProductionRegionTotal.query.filter_by(upload_id=upload.id).all(),
        ("region_code",),
        (
            "target_tl", "target_unit", "actual_tl", "actual_unit",
            "realization_percent", "unit_realization_percent", "source_sheet", "source_row",
        ),
    )
    _assert_collection(
        "national_urun",
        report.national_product_results,
        ProductionNationalProductResult.query.filter_by(upload_id=upload.id).all(),
        ("product_id",),
        (
            "actual_tl", "actual_unit", "realization_percent",
            "unit_realization_percent", "source_sheet", "source_row",
        ),
    )

    national = ProductionNationalTotal.query.filter_by(upload_id=upload.id).one_or_none()
    if national is None or report.national_total is None:
        raise ProductionWorkbookValidationError(
            "Üretim finalizasyon eşleşmesi başarısız: NATIONAL toplam kaydı eksik."
        )
    for field in (
        "target_tl", "target_unit", "actual_tl", "actual_unit",
        "realization_percent", "unit_realization_percent", "source_sheet", "source_row",
    ):
        _assert_value("national_toplam", field, report.national_total.get(field), getattr(national, field))

    if int(upload.row_count or 0) != int(report.rows_seen):
        raise ProductionWorkbookValidationError(
            f"Üretim finalizasyon eşleşmesi başarısız: temsilci satır sayısı "
            f"kaynak={report.rows_seen} db={upload.row_count}."
        )
    if int(upload.matched_row_count or 0) != int(report.matched_result_count):
        raise ProductionWorkbookValidationError(
            f"Üretim finalizasyon eşleşmesi başarısız: ürün satır sayısı "
            f"kaynak={report.matched_result_count} db={upload.matched_row_count}."
        )


def _gated_apply(upload, report):
    # Preserve all existing insertion semantics, but revoke APPLIED until every
    # inserted layer is read back and compared to the parsed source report.
    _ORIGINAL_APPLY(upload, report)
    upload.status = upload.STATUS_VALIDATED
    upload.applied_at = None
    db.session.flush()
    _reconcile(upload, report)
    upload.status = upload.STATUS_APPLIED
    upload.applied_at = datetime.utcnow()
    upload.warning_message = (upload.warning_message or "") + " Kaynak Excel ↔ DB final eşleşmesi %100 doğrulandı."


def _stage_aware_init(self, file_path, year, month, production_stage=None):
    # Legacy upload route may omit production_stage.  The protected staged file
    # name contains -u1- / -u2-, so recover it deterministically rather than
    # guessing between 1. and 2. production columns.
    if production_stage is None:
        match = re.search(r"-u([12])-", str(file_path))
        if match:
            production_stage = int(match.group(1))
    _ORIGINAL_INIT(self, file_path, year, month, production_stage=production_stage)


def install_production_result_reconciliation_gate():
    global _INSTALLED
    if _INSTALLED:
        return
    ProductionResultImportService.__init__ = _stage_aware_init
    ProductionResultImportService.apply = staticmethod(_gated_apply)
    _INSTALLED = True
