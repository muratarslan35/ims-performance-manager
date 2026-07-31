"""Workbook import service implementing IMSRawData -> IMSFact -> IMSSummary."""

import json
import logging
import math
import os
import re
import time
from datetime import datetime

import pandas as pd
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload, ImportAuditLog, ManualMatchQueue, Target
from app.services.alias_service import AliasService


# Regex to extract week number from typical IMS file names.
# Examples: "Tayfun-1 24.Hafta Haziran Brick Analizi_.xlsx"
#           "25.Hafta Mayıs IMS.xlsx"
_WEEK_REGEX = re.compile(r"(\d{1,2})\s*\.?\s*hafta", re.IGNORECASE)
logger = logging.getLogger(__name__)


class IMSImportService:
    """Import a workbook in three explicit, auditable ETL stages.

    Raw data is never used by reporting logic.  It is first staged exactly as
    read from the workbook, then transformed into matched facts, and finally
    aggregated into period summaries.
    """

    REPORT_SHEETS = {
        "BRICK SATIS": "brick_sales",
        "BRICK REA": "brick_realization",
        "BAKIYE": "balance",
        "HAFTALIK": "weekly_sales",
        "REKABET TL": "competition_tl",
        "REKABET KUTU": "competition_box",
        "REKABET PP": "competition_pp",
    }
    REPRESENTATIVE_HEADERS = {
        "TEMSILCI",
        "REPRESENTATIVE",
        "MUMESSIL",
        "REP",
        "ADI SOYADI",
        "SATIS TEMSILCISI",
    }
    REGION_HEADERS = {"BOLGE", "REGION"}
    PROVINCE_HEADERS = {"IL", "SEHIR", "CITY", "PROVINCE"}
    PRODUCT_GROUP_HEADERS = {"URUN GRUBU", "PRODUCT GROUP", "MARKA", "URUN", "PRODUCT"}
    NORMALIZED_SHEET_TYPES = {
        "TL": "competition_tl",
        "CIRO": "competition_tl",
        "TUTAR": "competition_tl",
        "KUTU": "competition_box",
        "BOX": "competition_box",
        "ADET": "competition_box",
        "MARKET": "competition_pp",
        "PAZAR": "competition_pp",
        "PAY": "competition_pp",
        "PP": "competition_pp",
    }
    TOTAL_LABELS = {"NATIONAL", "TOPLAM", "GRAND TOTAL", "TOTAL", "GENEL TOPLAM"}

    def __init__(self, file_path, uploaded_by=None):
        self.file_path = str(file_path)
        self.uploaded_by = uploaded_by
        self.started = time.monotonic()
        self.upload = None
        self.workbook = None
        self.errors = []
        self.warnings = []
        self.unknown_products = []
        self.unknown_columns = []
        self.statistics = {
            "sheet_count": 0,
            "processed_sheets": 0,
            "processed_rows": 0,
            "raw_records": 0,
            "fact_records": 0,
            "facts_inserted": 0,
            "facts_updated": 0,
            "summary_records": 0,
            "matched_products": 0,
            "matched_representatives": 0,
            "unmatched_representatives": 0,
            "queued_for_manual": 0,
            "skipped_records": 0,
        }
        self.skipped_logs = []

    @staticmethod
    def extract_week_number(file_name):
        """Extract week number from an IMS file name (e.g. '24.Hafta' -> 24)."""
        match = _WEEK_REGEX.search(os.path.basename(file_name))
        if match:
            week = int(match.group(1))
            if 1 <= week <= 53:
                return week
        return None

    @staticmethod
    def quarter_for(month):
        if month < 1 or month > 12:
            raise ValueError("Ay değeri 1 ile 12 arasında olmalıdır.")
        return f"Q{((month - 1) // 3) + 1}"

    @staticmethod
    def safe_float(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0.0
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip().replace("\u00a0", "")
        if not text or text.upper() in {"NAN", "NONE", "-"}:
            return 0.0
        text = re.sub(r"[^0-9,.-]", "", text)
        if text.count(",") and text.count("."):
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif text.count(","):
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _json_dump(value):
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)

    @staticmethod
    def _value_for_json(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def clean_text(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        text = str(value).strip()
        return "" if AliasService.normalize(text) in {"", "NAN", "NONE"} else text

    def create_upload(self, year, month, week_number=None):
        self.upload = IMSUpload(
            file_name=os.path.basename(self.file_path),
            year=year,
            month=month,
            week_number=week_number,
            quarter=self.quarter_for(month),
            uploaded_by=self.uploaded_by,
            status="PROCESSING",
        )
        db.session.add(self.upload)
        db.session.flush()
        return self.upload

    def load_workbook(self):
        self.workbook = pd.read_excel(self.file_path, sheet_name=None, header=None)
        self.statistics["sheet_count"] = len(self.workbook)
        return self.workbook

    def find_header_row(self, dataframe):
        max_rows = min(30, len(dataframe))
        best_index = None
        best_score = -1
        for index in range(max_rows):
            values = [AliasService.normalize(value) for value in dataframe.iloc[index].tolist()]
            row_text = " ".join(values)
            score = 0
            if any(candidate in row_text for candidate in self.REPRESENTATIVE_HEADERS):
                score += 3
            if any(candidate in row_text for candidate in self.PRODUCT_GROUP_HEADERS):
                score += 2
            if any(candidate in row_text for candidate in self.REGION_HEADERS | self.PROVINCE_HEADERS):
                score += 1
            if any(candidate in row_text for candidate in self.NORMALIZED_SHEET_TYPES):
                score += 1
            if score > best_score:
                best_index = index
                best_score = score
        if best_score >= 3:
            return best_index
        return None

    def normalize_header(self, value):
        return AliasService.normalize(value)

    def build_headers(self, dataframe, header_row):
        headers = []
        used_headers = {}
        header_rows = [header_row]
        if header_row > 0:
            header_rows.insert(0, header_row - 1)

        for column_index in range(dataframe.shape[1]):
            parts = []
            for row_index in header_rows:
                token = self.normalize_header(dataframe.iloc[row_index, column_index])
                if token and token not in parts:
                    parts.append(token)

            header = " ".join(parts) or f"COLUMN_{column_index + 1}"
            duplicate_count = used_headers.get(header, 0)
            used_headers[header] = duplicate_count + 1
            headers.append(header if duplicate_count == 0 else f"{header}_{duplicate_count + 1}")

        result = dataframe.iloc[header_row + 1 :].copy()
        result.columns = headers
        result.reset_index(drop=True, inplace=True)
        return result

    def detect_sheet_type(self, sheet_name):
        normalized_name = AliasService.normalize(sheet_name)
        for sheet_label, sheet_type in self.REPORT_SHEETS.items():
            if AliasService.normalize(sheet_label) in normalized_name:
                return sheet_type
        for token, sheet_type in self.NORMALIZED_SHEET_TYPES.items():
            if token in normalized_name:
                return sheet_type
        return "unknown"

    def detect_dimension_columns(self, dataframe):
        dimensions = {
            "representative": None,
            "region": None,
            "province": None,
            "product_group": None,
        }
        for column in dataframe.columns:
            normalized = AliasService.normalize(column)
            if dimensions["representative"] is None and (
                normalized in self.REPRESENTATIVE_HEADERS
                or any(candidate in normalized for candidate in self.REPRESENTATIVE_HEADERS if len(candidate) > 3)
            ):
                dimensions["representative"] = column
                continue
            if dimensions["region"] is None and any(token in normalized for token in self.REGION_HEADERS):
                dimensions["region"] = column
                continue
            if dimensions["province"] is None and any(token in normalized for token in self.PROVINCE_HEADERS):
                dimensions["province"] = column
                continue
            if dimensions["product_group"] is None and any(
                token in normalized for token in self.PRODUCT_GROUP_HEADERS
            ):
                dimensions["product_group"] = column
        return dimensions

    def detect_metric_kind(self, sheet_name, dataframe):
        normalized_name = AliasService.normalize(sheet_name)
        for token, sheet_type in self.NORMALIZED_SHEET_TYPES.items():
            if token in normalized_name:
                if sheet_type == "competition_tl":
                    return "tl"
                if sheet_type == "competition_box":
                    return "unit"
                if sheet_type == "competition_pp":
                    return "market_share"

        headers = " ".join(AliasService.normalize(column) for column in dataframe.columns)
        if any(token in headers for token in ("TL", "CIRO", "TUTAR", "VALUE")):
            return "tl"
        if any(token in headers for token in ("KUTU", "BOX", "ADET", "UNIT")):
            return "unit"
        return "market_share"

    def detect_metric_column(self, dataframe, dimensions, metric_kind):
        dimension_columns = {column for column in dimensions.values() if column}
        metric_tokens = {
            "tl": ("TL", "CIRO", "TUTAR", "VALUE"),
            "unit": ("KUTU", "BOX", "ADET", "UNIT"),
            "market_share": ("PAZAR", "PAY", "MARKET", "SHARE", "PP"),
        }
        candidates = [column for column in dataframe.columns if column not in dimension_columns]
        for column in candidates:
            normalized = AliasService.normalize(column)
            if any(token in normalized for token in metric_tokens[metric_kind]):
                return column

        scored = []
        for column in candidates:
            sample = dataframe[column].head(20)
            numeric_count = sum(1 for value in sample if self.safe_float(value) != 0.0)
            if numeric_count:
                scored.append((numeric_count, column))
        if scored:
            scored.sort(reverse=True)
            return scored[0][1]
        return None

    def _log_skipped_row(self, reason, sheet_name, source_row, **context):
        payload = {"reason": reason, "sheet_name": sheet_name, "source_row": source_row, **context}
        self.skipped_logs.append(payload)
        logger.warning("ims_import_skipped_row %s", self._json_dump(payload))

    def analyze_sheet(self, sheet_name, dataframe):
        header_row = self.find_header_row(dataframe)
        if header_row is None:
            self.warnings.append(f"{sheet_name}: temsilci başlığı bulunamadı; sayfa atlandı.")
            return None

        return {
            "sheet_name": str(sheet_name),
            "sheet_type": self.detect_sheet_type(sheet_name),
            "header_row": header_row,
            "dataframe": self.build_headers(dataframe, header_row),
        }

    def analyze_workbook(self):
        return [
            analysis
            for sheet_name, dataframe in self.workbook.items()
            if (analysis := self.analyze_sheet(sheet_name, dataframe)) is not None
        ]

    def detect_representative_column(self, dataframe):
        for column in dataframe.columns:
            normalized = AliasService.normalize(column)
            if normalized in self.REPRESENTATIVE_HEADERS:
                return column
            if any(candidate in normalized for candidate in self.REPRESENTATIVE_HEADERS if len(candidate) > 3):
                return column
        return None

    @staticmethod
    def metric_for_column(header):
        normalized = AliasService.normalize(header)
        if "VALUE SHARE" in normalized or "DEGER PAY" in normalized:
            return "value_share"
        if "TL" in normalized or "CIRO" in normalized or "VALUE" in normalized:
            return "tl"
        if "KUTU" in normalized or "BOX" in normalized or "UNIT" in normalized or "ADET" in normalized:
            return "unit"
        if "PAY" in normalized or "SHARE" in normalized or normalized.endswith(" PP"):
            return "market_share"
        if "GROWTH" in normalized or "BUYUME" in normalized:
            return "growth"
        return "unit"

    def detect_product_columns(self, dataframe, representative_column):
        products = {}
        for column_index, header in enumerate(dataframe.columns):
            if header == representative_column:
                continue
            match = AliasService.find_product(header)
            if not match["matched"]:
                continue

            product = match["object"]
            product_info = products.setdefault(
                product.id,
                {"product": product, "columns": []},
            )
            product_info["columns"].append(
                {
                    "index": column_index,
                    "header": str(header),
                    "metric": self.metric_for_column(header),
                }
            )
            self.statistics["matched_products"] += 1
        return products

    def clean_dataframe(self, dataframe, representative_column):
        result = dataframe.copy()
        representative_values = result[representative_column].fillna("").astype(str).str.strip()
        result = result[representative_values != ""]
        result = result[
            ~representative_values.str.upper().map(AliasService.normalize).isin(self.TOTAL_LABELS)
        ]
        result.reset_index(drop=True, inplace=True)
        return result

    def prepare_sheet(self, sheet):
        dataframe = sheet["dataframe"]
        dimensions = self.detect_dimension_columns(dataframe)
        representative_column = dimensions["representative"] or self.detect_representative_column(dataframe)
        if representative_column is None:
            self.warnings.append(f"{sheet['sheet_name']}: temsilci kolonu bulunamadı; sayfa atlandı.")
            return None

        if dimensions["product_group"] is not None:
            metric_kind = self.detect_metric_kind(sheet["sheet_name"], dataframe)
            metric_column = self.detect_metric_column(dataframe, dimensions, metric_kind)
            if metric_column is None:
                self.warnings.append(f"{sheet['sheet_name']}: metrik kolonu bulunamadı; sayfa atlandı.")
                return None
            return {
                **sheet,
                "mode": "normalized",
                "dataframe": self.clean_dataframe(dataframe, representative_column),
                "representative_column": representative_column,
                "region_column": dimensions["region"],
                "province_column": dimensions["province"],
                "product_group_column": dimensions["product_group"],
                "metric_kind": metric_kind,
                "metric_column": metric_column,
            }

        products = self.detect_product_columns(dataframe, representative_column)
        if not products:
            self.warnings.append(f"{sheet['sheet_name']}: eşleşen ürün kolonu bulunamadı; sayfa atlandı.")
            return None

        return {
            **sheet,
            "mode": "wide",
            "dataframe": self.clean_dataframe(dataframe, representative_column),
            "representative_column": representative_column,
            "products": products,
        }

    def merge_normalized_sheets(self, normalized_sheets):
        merged = {}
        for sheet in normalized_sheets:
            dataframe = sheet["dataframe"]
            representative_column = sheet["representative_column"]
            product_group_column = sheet["product_group_column"]
            for dataframe_index, (_, row) in enumerate(dataframe.iterrows()):
                representative_name = self.clean_text(row[representative_column])
                product_group_name = self.clean_text(row[product_group_column])
                source_row = dataframe_index + sheet["header_row"] + 2
                if not representative_name:
                    self.statistics["skipped_records"] += 1
                    self._log_skipped_row(
                        reason="missing_representative",
                        sheet_name=sheet["sheet_name"],
                        source_row=source_row,
                    )
                    continue
                if not product_group_name:
                    self.statistics["skipped_records"] += 1
                    self._log_skipped_row(
                        reason="missing_product_group",
                        sheet_name=sheet["sheet_name"],
                        source_row=source_row,
                        representative=representative_name,
                    )
                    continue

                key = (
                    AliasService.normalize(representative_name),
                    AliasService.normalize(product_group_name),
                )
                merged_row = merged.setdefault(
                    key,
                    {
                        "representative_name": representative_name,
                        "product_group": product_group_name,
                        "region": self.clean_text(row[sheet["region_column"]]) if sheet["region_column"] else None,
                        "province": self.clean_text(row[sheet["province_column"]]) if sheet["province_column"] else None,
                        "source_rows": [],
                        "sheet_names": set(),
                        "metrics": {"unit": 0.0, "tl": 0.0, "market_share": 0.0, "value_share": 0.0, "growth": 0.0},
                        "source_values": {},
                    },
                )
                merged_row["source_rows"].append(source_row)
                merged_row["sheet_names"].add(sheet["sheet_name"])
                metric_value = row[sheet["metric_column"]]
                merged_row["metrics"][sheet["metric_kind"]] += self.safe_float(metric_value)
                merged_row["source_values"][f"{sheet['sheet_name']}::{sheet['metric_column']}"] = self._value_for_json(
                    metric_value
                )
        return list(merged.values())

    def stage_normalized_raw_data(self, normalized_rows, year, month, week_number=None):
        for item in normalized_rows:
            representative_name = item["representative_name"]
            representative_match = AliasService.find_representative(representative_name)
            representative_id = None
            if representative_match["matched"]:
                representative_id = representative_match["object"].id
                self.statistics["matched_representatives"] += 1
            else:
                self.statistics["unmatched_representatives"] += 1
                self.statistics["queued_for_manual"] += 1
                self._log_skipped_row(
                    reason="unmatched_representative",
                    sheet_name=" | ".join(sorted(item["sheet_names"])),
                    source_row=min(item["source_rows"]),
                    representative=representative_name,
                )
                best = representative_match.get("object")
                AliasService.enqueue_unmatched_representative(
                    ims_name=representative_name,
                    upload_id=self.upload.id,
                    best_candidate=best.rep_name if best else None,
                    best_score=representative_match.get("score", 0.0),
                )

            product_group_name = item["product_group"]
            product_match = AliasService.find_product(product_group_name)
            if not product_match["matched"]:
                self.statistics["skipped_records"] += 1
                self.unknown_products.append(product_group_name)
                self._log_skipped_row(
                    reason="unmatched_product_group",
                    sheet_name=" | ".join(sorted(item["sheet_names"])),
                    source_row=min(item["source_rows"]),
                    representative=representative_name,
                    product_group=product_group_name,
                )
                best = product_match.get("object")
                AliasService.enqueue_unmatched_product(
                    ims_name=product_group_name,
                    upload_id=self.upload.id,
                    best_candidate=best.product_name if best else None,
                    best_score=product_match.get("score", 0.0),
                )
                continue

            self.statistics["matched_products"] += 1
            metrics = item["metrics"]
            if not any(metrics.values()):
                self.statistics["skipped_records"] += 1
                self._log_skipped_row(
                    reason="empty_metrics",
                    sheet_name=" | ".join(sorted(item["sheet_names"])),
                    source_row=min(item["source_rows"]),
                    representative=representative_name,
                    product_group=product_group_name,
                )
                continue

            source_values = {
                **item["source_values"],
                "region": item["region"],
                "province": item["province"],
                "product_group": product_group_name,
                "sheet_names": sorted(item["sheet_names"]),
            }

            self.create_raw_record(
                year=year,
                month=month,
                week_number=week_number,
                sheet_name=" | ".join(sorted(item["sheet_names"])),
                sheet_type="brick_normalized",
                source_row=min(item["source_rows"]),
                representative_name=representative_name,
                representative_id=representative_id,
                product=product_match["object"],
                metrics=metrics,
                source_values=source_values,
            )
            self.statistics["processed_rows"] += 1

    def create_raw_record(
        self,
        *,
        year,
        month,
        week_number=None,
        sheet_name,
        sheet_type,
        source_row,
        representative_name,
        representative_id,
        product,
        metrics,
        source_values,
    ):
        raw = IMSRawData(
            upload_id=self.upload.id,
            year=year,
            month=month,
            week_number=week_number,
            quarter=self.quarter_for(month),
            sheet_name=sheet_name,
            sheet_type=sheet_type,
            source_row=source_row,
            representative_id=representative_id,
            product_id=product.id,
            representative=representative_name,
            product=product.product_name,
            unit=metrics["unit"],
            tl=metrics["tl"],
            market_share=metrics["market_share"],
            value_share=metrics["value_share"],
            growth=metrics["growth"],
            raw_json=self._json_dump(
                {
                    "representative": representative_name,
                    "product": product.product_name,
                    "metrics": metrics,
                    "source_values": source_values,
                }
            ),
        )
        db.session.add(raw)
        self.statistics["raw_records"] += 1
        return raw

    def stage_raw_data(self, prepared_sheets, year, month, week_number=None):
        for sheet in prepared_sheets:
            if sheet.get("mode") == "normalized":
                continue
            dataframe = sheet["dataframe"]
            representative_column = sheet["representative_column"]

            for dataframe_index, (_, row) in enumerate(dataframe.iterrows()):
                representative_name = str(row[representative_column]).strip()
                representative_match = AliasService.find_representative(representative_name)
                representative_id = None
                if representative_match["matched"]:
                    representative_id = representative_match["object"].id
                    self.statistics["matched_representatives"] += 1
                else:
                    self.statistics["unmatched_representatives"] += 1
                    self.warnings.append(
                        f"{sheet['sheet_name']} satır {dataframe_index + sheet['header_row'] + 2}: "
                        f"temsilci eşleşmedi ({representative_name})."
                    )
                    self._log_skipped_row(
                        reason="unmatched_representative",
                        sheet_name=sheet["sheet_name"],
                        source_row=dataframe_index + sheet["header_row"] + 2,
                        representative=representative_name,
                    )
                    # Queue for manual resolution
                    best = representative_match.get("object")
                    AliasService.enqueue_unmatched_representative(
                        ims_name=representative_name,
                        upload_id=self.upload.id,
                        best_candidate=best.rep_name if best else None,
                        best_score=representative_match.get("score", 0.0),
                    )
                    self.statistics["queued_for_manual"] += 1

                for product_info in sheet["products"].values():
                    metrics = {"unit": 0.0, "tl": 0.0, "market_share": 0.0, "value_share": 0.0, "growth": 0.0}
                    source_values = {}
                    for column in product_info["columns"]:
                        value = row.iloc[column["index"]]
                        metrics[column["metric"]] += self.safe_float(value)
                        source_values[column["header"]] = self._value_for_json(value)

                    if not any(metrics.values()):
                        self.statistics["skipped_records"] += 1
                        self._log_skipped_row(
                            reason="empty_metrics",
                            sheet_name=sheet["sheet_name"],
                            source_row=dataframe_index + sheet["header_row"] + 2,
                            representative=representative_name,
                            product=product_info["product"].product_name,
                        )
                        continue

                    self.create_raw_record(
                        year=year,
                        month=month,
                        week_number=week_number,
                        sheet_name=sheet["sheet_name"],
                        sheet_type=sheet["sheet_type"],
                        source_row=dataframe_index + sheet["header_row"] + 2,
                        representative_name=representative_name,
                        representative_id=representative_id,
                        product=product_info["product"],
                        metrics=metrics,
                        source_values=source_values,
                    )
                self.statistics["processed_rows"] += 1
            self.statistics["processed_sheets"] += 1

        db.session.flush()

    def transform_raw_to_facts(self, year, month, week_number=None):
        """UPSERT IMS facts: update existing rows for the same week/period, insert new ones."""
        raw_records = IMSRawData.query.filter_by(upload_id=self.upload.id, year=year, month=month).all()
        for raw in raw_records:
            if raw.representative_id is None or raw.product_id is None:
                self.statistics["skipped_records"] += 1
                continue

            # Attempt to find an existing fact for this (year, week, rep, product, report_type)
            existing = None
            if week_number is not None:
                existing = IMSFact.query.filter_by(
                    year=year,
                    week_number=week_number,
                    representative_id=raw.representative_id,
                    product_id=raw.product_id,
                    report_type=raw.sheet_type,
                ).first()

            if existing:
                existing.upload_id = self.upload.id
                existing.raw_data_id = raw.id
                existing.unit = raw.unit
                existing.tl = raw.tl
                existing.market_share = raw.market_share
                existing.value_share = raw.value_share
                existing.growth = raw.growth
                existing.metrics_json = raw.raw_json
                self.statistics["facts_updated"] += 1
            else:
                fact = IMSFact(
                    upload_id=self.upload.id,
                    raw_data_id=raw.id,
                    representative_id=raw.representative_id,
                    product_id=raw.product_id,
                    year=raw.year,
                    month=raw.month,
                    week_number=week_number,
                    quarter=raw.quarter,
                    report_type=raw.sheet_type,
                    unit=raw.unit,
                    tl=raw.tl,
                    market_share=raw.market_share,
                    value_share=raw.value_share,
                    growth=raw.growth,
                    metrics_json=raw.raw_json,
                )
                db.session.add(fact)
                self.statistics["facts_inserted"] += 1

            self.statistics["fact_records"] += 1
        db.session.flush()

    def rebuild_summary(self, year, month):
        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)

        rows = (
            db.session.query(
                IMSFact.representative_id,
                IMSFact.product_id,
                func.sum(IMSFact.unit).label("unit"),
                func.sum(IMSFact.tl).label("tl"),
                func.avg(IMSFact.market_share).label("market_share"),
                func.avg(IMSFact.value_share).label("value_share"),
                func.avg(IMSFact.growth).label("growth"),
            )
            .filter(IMSFact.year == year, IMSFact.month == month)
            .group_by(IMSFact.representative_id, IMSFact.product_id)
            .all()
        )

        quarter = self.quarter_for(month)
        for row in rows:
            target = Target.query.filter_by(
                representative_id=row.representative_id,
                product_id=row.product_id,
                year=year,
                month=month,
            ).first()
            target_unit = target.unit_target if target else 0.0
            target_tl = target.tl_target if target else 0.0
            realization_base = target_tl or target_unit
            realization_actual = row.tl if target_tl else row.unit
            realization_percent = (
                round(realization_actual * 100 / realization_base, 2) if realization_base else 0.0
            )
            db.session.add(
                IMSSummary(
                    upload_id=self.upload.id,
                    representative_id=row.representative_id,
                    product_id=row.product_id,
                    year=year,
                    month=month,
                    quarter=quarter,
                    unit=row.unit or 0.0,
                    tl=row.tl or 0.0,
                    market_share=row.market_share or 0.0,
                    value_share=row.value_share or 0.0,
                    growth=row.growth or 0.0,
                    target_unit=target_unit,
                    target_tl=target_tl,
                    realization_percent=realization_percent,
                )
            )
        self.statistics["summary_records"] = len(rows)
        db.session.flush()

    def clear_week(self, year, week_number):
        """Remove all IMS data for a specific week (used only as a fallback)."""
        IMSFact.query.filter_by(year=year, week_number=week_number).delete(synchronize_session=False)
        IMSRawData.query.filter_by(year=year, week_number=week_number).delete(synchronize_session=False)
        db.session.flush()

    def clear_month(self, year, month):
        """Remove all IMS data for a calendar month (destructive; kept for backward compat)."""
        IMSFact.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSRawData.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        db.session.flush()

    def process_workbook(self, year, month, week_number=None):
        sheets = self.analyze_workbook()
        prepared_sheets = [sheet for sheet in (self.prepare_sheet(item) for item in sheets) if sheet]
        normalized_sheets = [sheet for sheet in prepared_sheets if sheet.get("mode") == "normalized"]
        wide_sheets = [sheet for sheet in prepared_sheets if sheet.get("mode") != "normalized"]
        if normalized_sheets:
            self.statistics["processed_sheets"] += len(normalized_sheets)
            normalized_rows = self.merge_normalized_sheets(normalized_sheets)
            self.stage_normalized_raw_data(normalized_rows, year, month, week_number=week_number)
        self.stage_raw_data(wide_sheets, year, month, week_number=week_number)
        self.transform_raw_to_facts(year, month, week_number=week_number)
        self.rebuild_summary(year, month)

    def write_audit_log(self, year, month, week_number, success):
        """Write an ImportAuditLog record for this import run."""
        log = ImportAuditLog(
            upload_id=self.upload.id,
            year=year,
            month=month,
            week_number=week_number,
            uploaded_by=self.uploaded_by,
            rows_inserted=self.statistics.get("facts_inserted", 0),
            rows_updated=self.statistics.get("facts_updated", 0),
            rows_skipped=self.statistics.get("skipped_records", 0),
            rows_unmatched=self.statistics.get("unmatched_representatives", 0),
            rows_error=len(self.errors),
            queued_for_manual=self.statistics.get("queued_for_manual", 0),
            processing_time=round(time.monotonic() - self.started, 2),
            status="COMPLETED" if success else "FAILED",
            notes=("\n".join(self.warnings) or None),
        )
        db.session.add(log)

    def finish(self, success=True, year=None, month=None, week_number=None):
        self.upload.processing_time = round(time.monotonic() - self.started, 2)
        self.upload.sheet_count = self.statistics["sheet_count"]
        self.upload.raw_record_count = self.statistics["raw_records"]
        self.upload.fact_record_count = self.statistics["fact_records"]
        self.upload.summary_record_count = self.statistics["summary_records"]
        self.upload.warning_message = "\n".join(self.warnings) or None
        self.upload.error_message = "\n".join(self.errors) or None
        self.upload.status = "COMPLETED" if success else "FAILED"
        self.upload.completed_at = datetime.utcnow()
        if year and month:
            self.write_audit_log(year, month, week_number, success)

    def report(self):
        return {
            "success": not self.errors,
            "upload_id": self.upload.id if self.upload else None,
            "statistics": self.statistics,
            "warnings": self.warnings,
            "errors": self.errors,
            "unknown_products": sorted(set(self.unknown_products)),
            "unknown_columns": sorted(set(self.unknown_columns)),
            "skipped_logs": self.skipped_logs,
            "processing_time": round(time.monotonic() - self.started, 2),
        }

    def validate(self):
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"IMS dosyası bulunamadı: {self.file_path}")
        if not self.file_path.lower().endswith((".xlsx", ".xls")):
            raise ValueError("Yalnızca .xlsx ve .xls dosyaları içe aktarılabilir.")
        return True

    def _persist_failure(self, year, month, week_number=None):
        failure_upload = IMSUpload(
            file_name=os.path.basename(self.file_path),
            year=year,
            month=month,
            week_number=week_number,
            quarter=self.quarter_for(month),
            uploaded_by=self.uploaded_by,
            status="FAILED",
            processing_time=round(time.monotonic() - self.started, 2),
            error_message="\n".join(self.errors),
            warning_message="\n".join(self.warnings) or None,
            completed_at=datetime.utcnow(),
        )
        db.session.add(failure_upload)
        db.session.commit()
        self.upload = failure_upload

    def run(self, year, month, clear_before_import=False, week_number=None):
        """Run the full ETL pipeline.

        week_number is extracted from the file name when not provided explicitly.
        When a week_number is available the pipeline performs an idempotent UPSERT
        instead of a destructive clear+insert.  clear_before_import is retained for
        backward compatibility but defaults to False.
        """
        if week_number is None:
            week_number = self.extract_week_number(self.file_path)

        try:
            self.validate()
            AliasService.warmup()
            self.create_upload(year, month, week_number=week_number)
            self.load_workbook()
            if clear_before_import and week_number is None:
                self.clear_month(year, month)
            self.process_workbook(year, month, week_number=week_number)
            self.finish(success=True, year=year, month=month, week_number=week_number)
            db.session.commit()
        except (OSError, ValueError, SQLAlchemyError, Exception) as exc:
            db.session.rollback()
            self.errors.append(str(exc))
            try:
                self._persist_failure(year, month, week_number=week_number)
            except SQLAlchemyError as persistence_error:
                db.session.rollback()
                self.errors.append(f"Hata kaydı yazılamadı: {persistence_error}")
        return self.report()

    def import_file(self, year, month):
        """Backward-compatible alias for callers of the previous service."""
        return self.run(year, month, clear_before_import=False)

    @classmethod
    def health(cls):
        return {"service": "IMSImportService", "version": "2.1.0", "status": "READY"}

    @classmethod
    def supported_reports(cls):
        return list(cls.REPORT_SHEETS.values())
