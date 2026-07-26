"""Workbook import service implementing IMSRawData -> IMSFact -> IMSSummary."""

import json
import math
import os
import re
import time
from datetime import datetime

import pandas as pd
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload, Target
from app.services.alias_service import AliasService


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
            "summary_records": 0,
            "matched_products": 0,
            "matched_representatives": 0,
            "unmatched_representatives": 0,
            "skipped_records": 0,
        }

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

    def create_upload(self, year, month):
        self.upload = IMSUpload(
            file_name=os.path.basename(self.file_path),
            year=year,
            month=month,
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
        for index in range(min(20, len(dataframe))):
            values = [AliasService.normalize(value) for value in dataframe.iloc[index].tolist()]
            if any(
                candidate in " ".join(values)
                for candidate in self.REPRESENTATIVE_HEADERS
            ):
                return index
        return None

    def normalize_header(self, value):
        return AliasService.normalize(value)

    def build_headers(self, dataframe, header_row):
        headers = []
        used_headers = {}
        for column_index, value in enumerate(dataframe.iloc[header_row].tolist(), start=1):
            header = self.normalize_header(value) or f"COLUMN_{column_index}"
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
        return "unknown"

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
        representative_column = self.detect_representative_column(dataframe)
        if representative_column is None:
            self.warnings.append(f"{sheet['sheet_name']}: temsilci kolonu bulunamadı; sayfa atlandı.")
            return None

        products = self.detect_product_columns(dataframe, representative_column)
        if not products:
            self.warnings.append(f"{sheet['sheet_name']}: eşleşen ürün kolonu bulunamadı; sayfa atlandı.")
            return None

        return {
            **sheet,
            "dataframe": self.clean_dataframe(dataframe, representative_column),
            "representative_column": representative_column,
            "products": products,
        }

    def create_raw_record(
        self,
        *,
        year,
        month,
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

    def stage_raw_data(self, prepared_sheets, year, month):
        for sheet in prepared_sheets:
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

                for product_info in sheet["products"].values():
                    metrics = {"unit": 0.0, "tl": 0.0, "market_share": 0.0, "value_share": 0.0, "growth": 0.0}
                    source_values = {}
                    for column in product_info["columns"]:
                        value = row.iloc[column["index"]]
                        metrics[column["metric"]] += self.safe_float(value)
                        source_values[column["header"]] = self._value_for_json(value)

                    if not any(metrics.values()):
                        self.statistics["skipped_records"] += 1
                        continue

                    self.create_raw_record(
                        year=year,
                        month=month,
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

    def transform_raw_to_facts(self, year, month):
        raw_records = IMSRawData.query.filter_by(upload_id=self.upload.id, year=year, month=month).all()
        for raw in raw_records:
            if raw.representative_id is None or raw.product_id is None:
                self.statistics["skipped_records"] += 1
                continue
            fact = IMSFact(
                upload_id=self.upload.id,
                raw_data_id=raw.id,
                representative_id=raw.representative_id,
                product_id=raw.product_id,
                year=raw.year,
                month=raw.month,
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

    def clear_month(self, year, month):
        IMSFact.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSRawData.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        db.session.flush()

    def process_workbook(self, year, month):
        sheets = self.analyze_workbook()
        prepared_sheets = [sheet for sheet in (self.prepare_sheet(item) for item in sheets) if sheet]
        self.stage_raw_data(prepared_sheets, year, month)
        self.transform_raw_to_facts(year, month)
        self.rebuild_summary(year, month)

    def finish(self, success=True):
        self.upload.processing_time = round(time.monotonic() - self.started, 2)
        self.upload.sheet_count = self.statistics["sheet_count"]
        self.upload.raw_record_count = self.statistics["raw_records"]
        self.upload.fact_record_count = self.statistics["fact_records"]
        self.upload.summary_record_count = self.statistics["summary_records"]
        self.upload.warning_message = "\n".join(self.warnings) or None
        self.upload.error_message = "\n".join(self.errors) or None
        self.upload.status = "COMPLETED" if success else "FAILED"
        self.upload.completed_at = datetime.utcnow()

    def report(self):
        return {
            "success": not self.errors,
            "upload_id": self.upload.id if self.upload else None,
            "statistics": self.statistics,
            "warnings": self.warnings,
            "errors": self.errors,
            "unknown_products": sorted(set(self.unknown_products)),
            "unknown_columns": sorted(set(self.unknown_columns)),
            "processing_time": round(time.monotonic() - self.started, 2),
        }

    def validate(self):
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"IMS dosyası bulunamadı: {self.file_path}")
        if not self.file_path.lower().endswith((".xlsx", ".xls")):
            raise ValueError("Yalnızca .xlsx ve .xls dosyaları içe aktarılabilir.")
        return True

    def _persist_failure(self, year, month):
        failure_upload = IMSUpload(
            file_name=os.path.basename(self.file_path),
            year=year,
            month=month,
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

    def run(self, year, month, clear_before_import=True):
        try:
            self.validate()
            AliasService.warmup()
            self.create_upload(year, month)
            self.load_workbook()
            if clear_before_import:
                self.clear_month(year, month)
            self.process_workbook(year, month)
            self.finish(success=True)
            db.session.commit()
        except (OSError, ValueError, SQLAlchemyError, Exception) as exc:
            db.session.rollback()
            self.errors.append(str(exc))
            try:
                self._persist_failure(year, month)
            except SQLAlchemyError as persistence_error:
                db.session.rollback()
                self.errors.append(f"Hata kaydı yazılamadı: {persistence_error}")
        return self.report()

    def import_file(self, year, month):
        """Backward-compatible alias for callers of the previous service."""
        return self.run(year, month, clear_before_import=True)

    @classmethod
    def health(cls):
        return {"service": "IMSImportService", "version": "2.0.0", "status": "READY"}

    @classmethod
    def supported_reports(cls):
        return list(cls.REPORT_SHEETS.values())
