"""Use the exact retained workbook for KPI competition source data.

The normal IMS loader intentionally hides display-filtered/hidden rows for legacy
reports. KPI aggregate rows and named rival detail are source data, however, and
must be read from the original workbook bytes exactly like the paired TL/KUTU
compatibility path. This installer changes only KPI-format imports; legacy
workbooks and all other importer stages remain unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.extensions import db
from app.models import CompetitionData


def install_kpi_competition_import_source_override() -> None:
    from app.services import kpi_market_single_source as single_source
    from app.services import kpi_workbook_compat as compat
    from app.services.ims_import_service import IMSImportService

    if getattr(single_source, "_raw_source_override_installed", False):
        return

    # KPI product tabs can contain hidden/detail-filtered rows. Those rows carry
    # named rival observations used by Region/Representative market drill-downs.
    # Replace only the KPI product-tab frames with the exact retained workbook
    # before the already-installed compatibility analyzer builds CompetitionData.
    # Legacy workbook frames remain untouched.
    original_analyze = IMSImportService.analyze_workbook

    def analyze_from_exact_kpi_source(service):
        file_path = Path(str(getattr(service, "file_path", "") or ""))
        workbook = getattr(service, "workbook", None)
        if file_path.is_file() and workbook:
            kpi_sheet_names = [name for name in workbook if compat.is_product_kpi_sheet(name)]
            if kpi_sheet_names:
                raw_kpi = pd.read_excel(file_path, sheet_name=kpi_sheet_names, header=None)
                for sheet_name in kpi_sheet_names:
                    if sheet_name in raw_kpi:
                        workbook[sheet_name] = raw_kpi[sheet_name]
        return original_analyze(service)

    IMSImportService.analyze_workbook = analyze_from_exact_kpi_source

    original_persist = single_source.persist_market_authority

    def persist_from_exact_source(service, year, month, week_number=None):
        file_path = Path(str(getattr(service, "file_path", "") or ""))
        if not file_path.is_file():
            return original_persist(service, year, month, week_number=week_number)

        raw_workbook = pd.read_excel(file_path, sheet_name=None, header=None)
        extracted = single_source.extract_market_authority(raw_workbook)
        if not extracted:
            return 0

        upload_id = int(service.upload.id)
        CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.sheet_name.like(f"{single_source.AUTHORITY_PREFIX}%"),
        ).delete(synchronize_session=False)

        mappings = []
        for product in extracted.values():
            group = str(product["product_name"])
            sheet_name = f"{single_source.AUTHORITY_PREFIX}{single_source._norm(group)}"
            for location, control in product["controls"].items():
                common = {
                    "upload_id": upload_id,
                    "sheet_name": sheet_name,
                    "period_type": "MONTHLY",
                    "year": int(year),
                    "month": int(month),
                    "week_number": int(week_number) if week_number is not None else None,
                    "territory": location,
                    "subterritory": location,
                    "product_group": group,
                    "metric_type": "UNIT",
                    "source_row": int(control["source_row"]),
                    "is_grand_total": False,
                }
                mappings.append({
                    **common,
                    "product_name": group,
                    "metric_value": float(control["company"]),
                    "is_company_product": True,
                    "is_competitor": False,
                    "is_subtotal": False,
                })
                mappings.append({
                    **common,
                    "product_name": f"{group} PAZAR",
                    "metric_value": float(control["market"]),
                    "is_company_product": False,
                    "is_competitor": False,
                    "is_subtotal": True,
                })

        if mappings:
            db.session.bulk_insert_mappings(CompetitionData, mappings)
            db.session.flush()
        service.statistics["kpi_market_authority_rows"] = len(mappings)
        service.statistics["competition_records"] = int(
            service.statistics.get("competition_records", 0) or 0
        ) + len(mappings)
        return len(mappings)

    single_source._persist_market_authority_before_raw_source_override = original_persist
    single_source.persist_market_authority = persist_from_exact_source
    single_source._raw_source_override_installed = True
