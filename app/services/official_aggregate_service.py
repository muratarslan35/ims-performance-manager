"""Persist and read workbook-provided NATIONAL / region aggregate metrics.

Representative rows remain authoritative for representative screens. Company and
region KPI totals use the explicit aggregate rows supplied by the workbook so a
sum of region KPIs reconciles exactly to NATIONAL.
"""

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
    return None


def _upsert(importer, year, month, sheet_name, sheet_type, territory, representative, product_id, unit, tl, metadata):
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
        product_match = importer.resolve_product_match(importer.clean_text(frame.iloc[header_row, column]))
        if product_match["matched"] and current:
            columns[product_match["object"].id][current] = column
    return columns


def _persist_targets(importer, year, month):
    sheet_name = next((name for name in importer.workbook if "BAKIYE" in _norm(name)), None)
    if not sheet_name:
        return 0
    frame = importer.workbook[sheet_name]
    header_row = next(
        (
            index for index in range(min(12, len(frame)))
            if "HEDEF" in " ".join(_norm(value) for value in frame.iloc[index])
            and "BAKIYE" in " ".join(_norm(value) for value in frame.iloc[index])
        ),
        None,
    )
    if header_row is None:
        return 0
    columns = _balance_columns(importer, frame, header_row)
    written = 0
    for row_index in range(header_row + 1, len(frame)):
        row = frame.iloc[row_index]
        territory = _aggregate_key(row.iloc[0] if len(row) else None, row.iloc[1] if len(row) > 1 else None)
        if not territory:
            continue
        representative = "NATIONAL" if territory == "NATIONAL" else importer.clean_text(row.iloc[1])
        for product_id, metrics in columns.items():
            if "target_tl" not in metrics:
                continue
            target_tl = importer.safe_float(row.iloc[metrics["target_tl"]])
            balance_tl = importer.safe_float(row.iloc[metrics["balance_tl"]]) if "balance_tl" in metrics else 0.0
            balance_unit = importer.safe_float(row.iloc[metrics["balance_unit"]]) if "balance_unit" in metrics else 0.0
            target_unit = 0.0
            if balance_tl and balance_unit:
                net_unit_factor = balance_tl / balance_unit
                if net_unit_factor > 0:
                    target_unit = target_tl / net_unit_factor
            _upsert(
                importer, year, month, sheet_name, TARGET_TYPE, territory, representative,
                product_id, target_unit, target_tl,
                {"target_tl": target_tl, "target_unit": target_unit,
                 "balance_tl": balance_tl, "balance_unit": balance_unit,
                 "source": "BAKIYE aggregate row"},
            )
            written += 1
    return written


def _weekly_columns(importer, frame, header_row):
    sections = {}
    current = ""
    selected = set()
    for column in range(frame.shape[1]):
        label = _norm(importer.clean_text(frame.iloc[header_row - 1, column]))
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
        product_match = importer.resolve_product_match(importer.clean_text(frame.iloc[header_row, column]))
        if product_match["matched"]:
            columns[product_match["object"].id][metric] = column
    return columns


def _persist_actuals(importer, year, month):
    sheet_name = next(
        (name for name in importer.workbook if "HAFTALIK" in _norm(name) and "CIKIS" in _norm(name)),
        None,
    )
    if not sheet_name:
        return 0
    frame = importer.workbook[sheet_name]
    header_row = next(
        (
            index for index in range(1, min(12, len(frame)))
            if "TRAVAZOL" in " ".join(_norm(value) for value in frame.iloc[index])
            and "MONUROL" in " ".join(_norm(value) for value in frame.iloc[index])
        ),
        None,
    )
    if header_row is None:
        return 0
    columns = _weekly_columns(importer, frame, header_row)
    written = 0
    for row_index in range(header_row + 1, len(frame)):
        row = frame.iloc[row_index]
        territory = _aggregate_key(row.iloc[0] if len(row) else None, row.iloc[1] if len(row) > 1 else None)
        if not territory:
            continue
        representative = "NATIONAL" if territory == "NATIONAL" else importer.clean_text(row.iloc[1])
        for product_id, metrics in columns.items():
            actual_tl = importer.safe_float(row.iloc[metrics["tl"]]) if "tl" in metrics else 0.0
            actual_unit = importer.safe_float(row.iloc[metrics["unit"]]) if "unit" in metrics else 0.0
            _upsert(
                importer, year, month, sheet_name, ACTUAL_TYPE, territory, representative,
                product_id, actual_unit, actual_tl,
                {"actual_tl": actual_tl, "actual_unit": actual_unit,
                 "source": "TTS HAFTALIK CIKISLARI cumulative aggregate row"},
            )
            written += 1
    return written


def persist_official_aggregates(importer, year, month):
    """Persist exact aggregate target and actual rows for one upload."""
    if not importer.upload or not importer.workbook:
        return {"targets": 0, "actuals": 0}
    targets = _persist_targets(importer, year, month)
    actuals = _persist_actuals(importer, year, month)
    db.session.flush()
    return {"targets": targets, "actuals": actuals}


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
                IMSRawData.sheet_type == sheet_type,
            )
        return query.order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()

    @staticmethod
    def rows(year, month, territory, sheet_type):
        upload_id = OfficialAggregateService.latest_upload_id(year, month, sheet_type)
        if not upload_id:
            return []
        return IMSRawData.query.filter_by(
            upload_id=upload_id,
            sheet_type=sheet_type,
            territory=str(territory),
        ).all()

    @staticmethod
    def product_totals(year, month, territory):
        target_rows = OfficialAggregateService.rows(year, month, territory, TARGET_TYPE)
        actual_rows = OfficialAggregateService.rows(year, month, territory, ACTUAL_TYPE)
        if not target_rows:
            return None
        actual_by_product = {row.product_id: row for row in actual_rows}
        products = {item.id: item for item in Product.query.filter(Product.id.in_([row.product_id for row in target_rows])).all()}
        result = []
        for target in target_rows:
            actual = actual_by_product.get(target.product_id)
            result.append({
                "product_id": target.product_id,
                "product_name": products[target.product_id].product_name if target.product_id in products else str(target.product_id),
                "target_tl": float(target.tl or 0),
                "target_unit": float(target.unit or 0),
                "actual_tl": float(actual.tl or 0) if actual else 0.0,
                "actual_unit": float(actual.unit or 0) if actual else 0.0,
            })
        return result
