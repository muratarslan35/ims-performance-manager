"""Persist/read and reconcile workbook-provided NATIONAL / region aggregates."""
import json
import re
from collections import defaultdict

from sqlalchemy import desc

from app.extensions import db
from app.models import IMSRawData, IMSUpload, Product
from app.services.alias_service import AliasService

TARGET_TYPE = "official_target_aggregate"
ACTUAL_TYPE = "official_actual_aggregate"


def _norm(value):
    return AliasService.normalize(value)


def _region_code(value):
    match = re.match(r"^(\d{3})\b", _norm(value))
    return match.group(1) if match else None


def _aggregate_key(location, representative):
    rep = _norm(representative)
    loc = _norm(location)
    if rep == "NATIONAL":
        return "NATIONAL"
    code = _region_code(location)
    if code and rep == loc:
        return code
    # Compact pivot exports may leave column A blank while column B contains
    # a deterministic region subtotal label such as ``901 DIYARBAKIR``.
    rep_code = _region_code(representative)
    return rep_code if not loc and rep_code else None


def _upsert(
    importer,
    year,
    month,
    sheet_name,
    sheet_type,
    territory,
    representative,
    product_id,
    unit,
    tl,
    metadata,
):
    record = IMSRawData.query.filter_by(
        upload_id=importer.upload.id,
        sheet_type=sheet_type,
        product_id=product_id,
        territory=territory,
    ).first()
    values = dict(
        year=year,
        month=month,
        quarter=importer.quarter_for(month),
        week_number=importer.upload.week_number,
        sheet_name=sheet_name,
        sheet_type=sheet_type,
        source_row=0,
        product_id=product_id,
        representative=representative,
        territory=territory,
        unit=float(unit or 0),
        tl=float(tl or 0),
        raw_json=json.dumps(metadata, ensure_ascii=False),
    )
    if record is None:
        db.session.add(IMSRawData(upload_id=importer.upload.id, **values))
    else:
        for key, value in values.items():
            setattr(record, key, value)


def _balance_columns(importer, frame, header_row):
    current = ""
    columns = defaultdict(dict)
    for column in range(frame.shape[1]):
        label = _norm(importer.clean_text(frame.iloc[header_row, column]))
        if "HEDEF" in label and "TL" in label:
            current = "target_tl"
            continue
        if "CIKIS" in label and "TL" in label:
            current = "actual_tl"
            continue
        if "BAKIYE" in label and ("KUTU" in label or "UNIT" in label):
            current = "balance_unit"
            continue
        if "BAKIYE" in label and "TL" in label:
            current = "balance_tl"
            continue
        match = importer.resolve_product_match(importer.clean_text(frame.iloc[header_row, column]))
        if match["matched"] and current:
            columns[match["object"].id][current] = column
    return columns


def _previous_official_units(year, month, sheet_type):
    upload_id = OfficialAggregateService.latest_upload_id(year, month, sheet_type)
    if not upload_id:
        return {}
    return {
        (str(row.territory), int(row.product_id)): float(row.unit or 0)
        for row in IMSRawData.query.filter_by(upload_id=upload_id, sheet_type=sheet_type).all()
    }


def _compact_tts_layout(importer):
    """Return the compact TTS target/actual layout, if present.

    This is deliberately a fallback contract. Normal wide IMS workbooks keep
    using BAKIYE / HAFTALIK semantic sources unchanged. The compact contract
    requires a TTS sheet with explicit HEDEF and CIKIS blocks on row 1 and
    managed product headers on row 2.
    """
    for sheet_name, frame in (importer.workbook or {}).items():
        if "TTS" not in _norm(sheet_name) or len(frame.index) < 3 or frame.shape[1] < 3:
            continue
        section_row = " ".join(_norm(value) for value in frame.iloc[0].values)
        if "HEDEF" not in section_row or "CIKIS" not in section_row:
            continue

        sections = {}
        current = ""
        product_columns = defaultdict(dict)
        matched_products = set()
        for column in range(frame.shape[1]):
            label = _norm(importer.clean_text(frame.iloc[0, column]))
            if label:
                if "HEDEF" in label or "TARGET" in label:
                    current = "target_tl"
                elif "CIKIS" in label:
                    current = "actual_tl"
                elif "REAL" in label or "%" in label:
                    current = ""
            sections[column] = current

            if current not in {"target_tl", "actual_tl"}:
                continue
            product_name = importer.clean_text(frame.iloc[1, column])
            if not product_name or _norm(product_name) in {"TOPLAM", "TOTAL"}:
                continue
            match = importer.resolve_product_match(product_name)
            if match["matched"]:
                product_id = int(match["object"].id)
                product_columns[product_id][current] = column
                matched_products.add(product_id)

        if matched_products and any("target_tl" in values for values in product_columns.values()):
            return sheet_name, frame, product_columns
    return None


def _persist_compact_tts(importer, year, month, metric):
    layout = _compact_tts_layout(importer)
    if layout is None:
        return 0
    sheet_name, frame, product_columns = layout
    sheet_type = TARGET_TYPE if metric == "target_tl" else ACTUAL_TYPE
    previous_units = _previous_official_units(year, month, sheet_type)
    written = 0

    for row_index in range(2, len(frame.index)):
        row = frame.iloc[row_index]
        territory = _aggregate_key(
            row.iloc[0] if len(row) else None,
            row.iloc[1] if len(row) > 1 else None,
        )
        if not territory:
            continue
        representative = "NATIONAL" if territory == "NATIONAL" else importer.clean_text(row.iloc[1])
        for product_id, columns in product_columns.items():
            column = columns.get(metric)
            if column is None:
                continue
            tl_value = importer.safe_float(row.iloc[column])
            unit_value = previous_units.get((str(territory), int(product_id)), 0.0)
            _upsert(
                importer,
                year,
                month,
                sheet_name,
                sheet_type,
                territory,
                representative,
                product_id,
                unit_value,
                tl_value,
                {
                    metric: tl_value,
                    "preserved_unit": unit_value,
                    "source": "compact TTS aggregate row",
                    "source_row": row_index + 1,
                },
            )
            written += 1
    return written


def _persist_targets(importer, year, month):
    sheet = next((name for name in importer.workbook if "BAKIYE" in _norm(name)), None)
    if not sheet:
        return _persist_compact_tts(importer, year, month, "target_tl")

    frame = importer.workbook[sheet]
    header = next(
        (
            index
            for index in range(min(12, len(frame)))
            if "HEDEF" in " ".join(_norm(value) for value in frame.iloc[index])
            and "BAKIYE" in " ".join(_norm(value) for value in frame.iloc[index])
        ),
        None,
    )
    if header is None:
        return 0
    columns = _balance_columns(importer, frame, header)
    written = 0
    for row_index in range(header + 1, len(frame)):
        row = frame.iloc[row_index]
        territory = _aggregate_key(
            row.iloc[0] if len(row) else None,
            row.iloc[1] if len(row) > 1 else None,
        )
        if not territory:
            continue
        representative = "NATIONAL" if territory == "NATIONAL" else importer.clean_text(row.iloc[1])
        for product_id, metrics in columns.items():
            if "target_tl" not in metrics:
                continue
            target_tl = importer.safe_float(row.iloc[metrics["target_tl"]])
            balance_tl = (
                importer.safe_float(row.iloc[metrics["balance_tl"]])
                if "balance_tl" in metrics
                else 0.0
            )
            balance_unit = (
                importer.safe_float(row.iloc[metrics["balance_unit"]])
                if "balance_unit" in metrics
                else 0.0
            )
            target_unit = (
                target_tl / (balance_tl / balance_unit)
                if balance_tl and balance_unit and balance_tl / balance_unit > 0
                else 0.0
            )
            _upsert(
                importer,
                year,
                month,
                sheet,
                TARGET_TYPE,
                territory,
                representative,
                product_id,
                target_unit,
                target_tl,
                {
                    "target_tl": target_tl,
                    "target_unit": target_unit,
                    "balance_tl": balance_tl,
                    "balance_unit": balance_unit,
                    "source": "BAKIYE aggregate row",
                },
            )
            written += 1
    return written


def _weekly_columns(importer, frame, header):
    sections = {}
    current = ""
    selected = set()
    for column in range(frame.shape[1]):
        label = _norm(importer.clean_text(frame.iloc[header - 1, column]))
        if "TL" in label and "CIKIS" in label:
            current = "tl" if "tl" not in selected else ""
            selected.add("tl")
        elif ("KUTU" in label or "UNIT" in label) and "CIKIS" in label:
            current = "unit" if "unit" not in selected else ""
            selected.add("unit")
        sections[column] = current
    columns = defaultdict(dict)
    for column in range(frame.shape[1]):
        metric = sections.get(column)
        if metric not in {"tl", "unit"}:
            continue
        match = importer.resolve_product_match(importer.clean_text(frame.iloc[header, column]))
        if match["matched"]:
            columns[match["object"].id][metric] = column
    return columns


def _persist_actuals(importer, year, month):
    sheet = next(
        (
            name
            for name in importer.workbook
            if "HAFTALIK" in _norm(name) and "CIKIS" in _norm(name)
        ),
        None,
    )
    if not sheet:
        return _persist_compact_tts(importer, year, month, "actual_tl")

    frame = importer.workbook[sheet]
    header = next(
        (
            index
            for index in range(1, min(12, len(frame)))
            if "TRAVAZOL" in " ".join(_norm(value) for value in frame.iloc[index])
        ),
        None,
    )
    if header is None:
        return 0
    columns = _weekly_columns(importer, frame, header)
    written = 0
    for row_index in range(header + 1, len(frame)):
        row = frame.iloc[row_index]
        territory = _aggregate_key(
            row.iloc[0] if len(row) else None,
            row.iloc[1] if len(row) > 1 else None,
        )
        if not territory:
            continue
        representative = "NATIONAL" if territory == "NATIONAL" else importer.clean_text(row.iloc[1])
        for product_id, metrics in columns.items():
            tl = importer.safe_float(row.iloc[metrics["tl"]]) if "tl" in metrics else 0.0
            unit = importer.safe_float(row.iloc[metrics["unit"]]) if "unit" in metrics else 0.0
            _upsert(
                importer,
                year,
                month,
                sheet,
                ACTUAL_TYPE,
                territory,
                representative,
                product_id,
                unit,
                tl,
                {
                    "actual_tl": tl,
                    "actual_unit": unit,
                    "source": "TTS HAFTALIK CIKISLARI cumulative aggregate row",
                },
            )
            written += 1
    return written


def _reconcile_type(importer, sheet_type, tolerance=0.01):
    rows = IMSRawData.query.filter_by(upload_id=importer.upload.id, sheet_type=sheet_type).all()
    national = {}
    regions = defaultdict(lambda: [0.0, 0.0])
    region_codes = set()
    for row in rows:
        if row.territory == "NATIONAL":
            national[row.product_id] = (float(row.unit or 0), float(row.tl or 0))
        else:
            regions[row.product_id][0] += float(row.unit or 0)
            regions[row.product_id][1] += float(row.tl or 0)
            region_codes.add(str(row.territory))
    conflicts = []
    for product_id, (national_unit, national_tl) in national.items():
        region_unit, region_tl = regions.get(product_id, (0.0, 0.0))
        if abs(national_unit - region_unit) > tolerance or abs(national_tl - region_tl) > tolerance:
            conflicts.append(
                {
                    "sheet_type": sheet_type,
                    "product_id": product_id,
                    "national_unit": national_unit,
                    "regions_unit": region_unit,
                    "national_tl": national_tl,
                    "regions_tl": region_tl,
                }
            )
    return {
        "region_count": len(region_codes),
        "national_products": len(national),
        "conflicts": conflicts,
    }


def reconcile_national_regions(importer):
    target = _reconcile_type(importer, TARGET_TYPE)
    actual = _reconcile_type(importer, ACTUAL_TYPE)
    conflicts = target["conflicts"] + actual["conflicts"]
    importer.statistics["national_region_conflict"] = len(conflicts)
    importer.statistics["national_region_target_regions"] = target["region_count"]
    importer.statistics["national_region_actual_regions"] = actual["region_count"]
    importer.national_region_reconciliation = {
        "targets": target,
        "actuals": actual,
        "conflicts": conflicts,
        "passed": not conflicts,
    }
    if conflicts:
        raise ValueError(
            f"NATIONAL/bölge reconciliation başarısız: {len(conflicts)} TL/KUTU uyuşmazlığı"
        )
    return importer.national_region_reconciliation


def persist_official_aggregates(importer, year, month):
    if not importer.upload or not importer.workbook:
        return {"targets": 0, "actuals": 0}
    targets = _persist_targets(importer, year, month)
    actuals = _persist_actuals(importer, year, month)
    db.session.flush()
    reconciliation = reconcile_national_regions(importer)
    return {"targets": targets, "actuals": actuals, "reconciliation": reconciliation}


class OfficialAggregateService:
    @staticmethod
    def latest_upload_id(year, month, sheet_type=None):
        query = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == year,
            IMSUpload.month == month,
            IMSUpload.status == "COMPLETED",
        )
        if sheet_type:
            query = query.join(IMSRawData, IMSRawData.upload_id == IMSUpload.id).filter(
                IMSRawData.sheet_type == sheet_type
            )
        # Weekly IMS files are cumulative snapshots. A replay of an earlier
        # week must never replace the newest business snapshot merely because
        # it was imported later.
        return (
            query.order_by(
                desc(IMSUpload.week_number),
                desc(IMSUpload.completed_at),
                desc(IMSUpload.id),
            )
            .limit(1)
            .scalar()
        )

    @staticmethod
    def rows(year, month, territory, sheet_type):
        upload_id = OfficialAggregateService.latest_upload_id(year, month, sheet_type)
        return (
            []
            if not upload_id
            else IMSRawData.query.filter_by(
                upload_id=upload_id,
                sheet_type=sheet_type,
                territory=str(territory),
            ).all()
        )

    @staticmethod
    def product_totals(year, month, territory):
        targets = OfficialAggregateService.rows(year, month, territory, TARGET_TYPE)
        actuals = OfficialAggregateService.rows(year, month, territory, ACTUAL_TYPE)
        if not targets:
            return None
        actual_by = {row.product_id: row for row in actuals}
        products = {
            product.id: product
            for product in Product.query.filter(
                Product.id.in_([row.product_id for row in targets])
            ).all()
        }
        result = []
        for target in targets:
            actual = actual_by.get(target.product_id)
            result.append(
                {
                    "product_id": target.product_id,
                    "product_name": (
                        products[target.product_id].product_name
                        if target.product_id in products
                        else str(target.product_id)
                    ),
                    "target_tl": float(target.tl or 0),
                    "target_unit": float(target.unit or 0),
                    "actual_tl": float(actual.tl or 0) if actual else 0.0,
                    "actual_unit": float(actual.unit or 0) if actual else 0.0,
                }
            )
        return result
