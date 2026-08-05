"""Independent and isolated import service skeleton for competition extension sheets."""

import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from openpyxl import load_workbook as openpyxl_load_workbook
from app.extensions import db
from app.models import CompetitionData, IMSUpload

logger = logging.getLogger(__name__)


class CompetitionImportService:
    """Service to validate and process competition and market extension worksheets."""

    SUPPORTED_SHEETS: Dict[str, str] = {
        "HAZİRAN KUTU": "MONTHLY_UNITS",
        "HAZİRAN TL": "MONTHLY_VALUE",
        "KUTU": "WEEKLY_UNITS",
        "TL": "WEEKLY_VALUE",
        "AYLIK REKABET KUTU": "MONTHLY_COMPETITION_UNITS",
        "AYLIK REKABET TL": "MONTHLY_COMPETITION_VALUE",
        "PAZAR": "MARKET_REFERENCE",
    }

    MONTH_PATTERNS = (
        ("JAN", 1), ("JANUARY", 1), ("OCAK", 1),
        ("FEB", 2), ("FEBRUARY", 2), ("ŞUBAT", 2),
        ("MAR", 3), ("MARCH", 3), ("MART", 3),
        ("APR", 4), ("APRIL", 4), ("NİSAN", 4),
        ("MAY", 5), ("MAYIS", 5),
        ("JUN", 6), ("JUNE", 6), ("HAZİRAN", 6),
        ("JUL", 7), ("JULY", 7), ("TEMMUZ", 7),
        ("AUG", 8), ("AUGUST", 8), ("AĞUSTOS", 8),
        ("SEP", 9), ("SEPTEMBER", 9), ("EYLÜL", 9),
        ("OCT", 10), ("OCTOBER", 10), ("EKİM", 10),
        ("NOV", 11), ("NOVEMBER", 11), ("KASIM", 11),
        ("DEC", 12), ("DECEMBER", 12), ("ARALIK", 12),
    )

    YEAR_PATTERN = re.compile(r"20\d{2}")

    STOP_KEYWORDS = ("GRAND TOTAL", "GENEL TOPLAM", "TOTAL", "TOPLAM", "SUBTOTAL", "ARA TOPLAM")
    HEADER_TERRITORY_KEYWORDS = ("TERRITOR", "BOLGE")
    HEADER_SUBTERRITORY_KEYWORDS = ("SUBTERRITOR", "NATIONAL")

    def __init__(self, file_path: Optional[str] = None, upload_id: Optional[int] = None) -> None:
        self.file_path = file_path
        self.upload_id = upload_id
        self._workbook = None
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def _normalize_sheet_name(self, sheet_name: str) -> str:
        return str(sheet_name).strip().upper() if sheet_name else ""

    def load_workbook(self, file_path: str) -> None:
        self.file_path = file_path
        try:
            self._workbook = openpyxl_load_workbook(self.file_path, data_only=True, read_only=True)
            logger.info("Workbook successfully loaded from %s", self.file_path)
        except Exception as exc:
            err_msg = f"Failed to load workbook at {file_path}: {exc}"
            logger.error(err_msg)
            raise ValueError(err_msg) from exc

    def get_supported_sheets(self) -> List[str]:
        return sorted(list(self.SUPPORTED_SHEETS.keys()))

    def get_sheet_type(self, sheet_name: str) -> str:
        norm_name = self._normalize_sheet_name(sheet_name)
        norm_map = {self._normalize_sheet_name(k): v for k, v in self.SUPPORTED_SHEETS.items()}
        if norm_name not in norm_map:
            raise ValueError(f"Unknown or unsupported sheet name: '{sheet_name}'")
        return norm_map[norm_name]

    def validate_workbook(self) -> Dict[str, str]:
        if not self._workbook:
            raise ValueError("Workbook is not loaded. Call load_workbook() first.")

        actual_map = {self._normalize_sheet_name(n): n for n in self._workbook.sheetnames}
        req_norm = {self._normalize_sheet_name(r) for r in self.SUPPORTED_SHEETS}
        missing = req_norm - set(actual_map.keys())

        if missing:
            err_msg = f"Fail Fast: Missing required competition sheets: {sorted(list(missing))}"
            logger.error(err_msg)
            self.errors.append(err_msg)
            raise ValueError(err_msg)

        logger.info("Workbook validation passed for required competition sheets.")
        return actual_map

    def validate_sheet_structure(self, sheet_name: str) -> bool:
        if not self._workbook:
            raise ValueError("Workbook is not loaded. Call load_workbook() first.")

        norm_target = self._normalize_sheet_name(sheet_name)
        actual_map = {self._normalize_sheet_name(n): n for n in self._workbook.sheetnames}

        if norm_target not in actual_map:
            raise ValueError(f"Sheet '{sheet_name}' not found in workbook.")

        orig_name = actual_map[norm_target]
        sheet = self._workbook[orig_name]
        max_row, max_col = sheet.max_row or 0, sheet.max_column or 0

        if max_row < 2 or max_col < 1:
            err_msg = f"Sheet '{orig_name}' is empty or lacks structural rows."
            logger.error(err_msg)
            self.errors.append(err_msg)
            raise ValueError(err_msg)

        return True

    def _discover_metadata(self, sheet) -> Tuple[str, int, int]:
        period_type = "MONTHLY"
        year, month = None, None

        for r in range(1, 6):
            for c in range(1, (sheet.max_column or 1) + 1):
                val = sheet.cell(row=r, column=c).value
                if not val:
                    continue
                v_str = str(val).strip().upper()

                if "WEEK" in v_str or "HAFTA" in v_str:
                    period_type = "WEEKLY"
                if not year:
                    ym = self.YEAR_PATTERN.search(v_str)
                    if ym:
                        year = int(ym.group(0))
                if not month:
                    for mk, mv in self.MONTH_PATTERNS:
                        if mk in v_str:
                            month = mv
                            break

        if not year:
            raise ValueError("Fail Fast: Could not determine reporting Year from metadata.")
        if not month:
            raise ValueError("Fail Fast: Could not determine reporting Month from metadata.")

        return period_type, year, month

    def _find_header_row(self, sheet) -> int:
        for r in range(1, min(sheet.max_row or 0, 15) + 1):
            row_vals = [str(sheet.cell(row=r, column=c).value or "").strip().upper() for c in range(1, (sheet.max_column or 1) + 1)]
            if any(any(k in v for k in self.HEADER_TERRITORY_KEYWORDS) for v in row_vals) and \
               any(any(k in v for k in self.HEADER_SUBTERRITORY_KEYWORDS) for v in row_vals):
                return r
        raise ValueError("Fail Fast: Header row with TERRITORIES and SUBTERRITORIES not found.")

    def _find_data_start(self, sheet, header_row: int, territory_col: int) -> int:
        for r in range(header_row + 1, (sheet.max_row or 0) + 1):
            if str(sheet.cell(row=r, column=territory_col).value or "").strip():
                return r
        raise ValueError("Fail Fast: Data start row not found.")

    def _find_data_end(self, sheet, start_row: int) -> int:
        last_row = start_row
        for r in range(start_row, (sheet.max_row or 0) + 1):
            is_empty, has_stop = True, False
            for c in range(1, (sheet.max_column or 1) + 1):
                val = sheet.cell(row=r, column=c).value
                if val is not None and str(val).strip():
                    is_empty = False
                    if any(sk in str(val).strip().upper() for sk in self.STOP_KEYWORDS):
                        has_stop = True
                        break
            if is_empty or has_stop:
                break
            last_row = r
        return last_row

    def _is_meta_col(self, col_name: str) -> bool:
        upper = col_name.upper()
        return (any(k in upper for k in self.HEADER_TERRITORY_KEYWORDS) or
                any(k in upper for k in self.HEADER_SUBTERRITORY_KEYWORDS) or
                "REPORT" in upper or "MARKET" in upper)

    def _extract_product_groups(self, sheet, header_row: int) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        curr_grp = "GENEL"
        group_row = max(1, header_row - 1)

        for c in range(1, (sheet.max_column or 0) + 1):
            g_val = sheet.cell(row=group_row, column=c).value
            if g_val and str(g_val).strip():
                curr_grp = str(g_val).strip()

            p_val = sheet.cell(row=header_row, column=c).value
            if not p_val or self._is_meta_col(str(p_val)):
                continue

            p_name = str(p_val).strip()
            groups.setdefault(curr_grp, [])
            if p_name not in groups[curr_grp]:
                groups[curr_grp].append(p_name)

        if not groups:
            raise ValueError("Fail Fast: No product groups discovered.")
        return groups

    def _extract_product_columns(self, sheet, header_row: int) -> Dict[str, int]:
        cols: Dict[str, int] = {}
        for c in range(1, (sheet.max_column or 0) + 1):
            val = sheet.cell(row=header_row, column=c).value
            if not val or self._is_meta_col(str(val)):
                continue
            cols[str(val).strip()] = c

        if not cols:
            raise ValueError("Fail Fast: No product columns discovered.")
        return cols

    def _parse_sheet_structure(self, sheet_name: str) -> Dict[str, Any]:
        if not self._workbook:
            raise ValueError("Workbook is not loaded.")

        actual_map = {self._normalize_sheet_name(n): n for n in self._workbook.sheetnames}
        norm_target = self._normalize_sheet_name(sheet_name)
        if norm_target not in actual_map:
            raise ValueError(f"Fail Fast: Sheet '{sheet_name}' not found.")

        orig_name = actual_map[norm_target]
        sheet = self._workbook[orig_name]

        ptype, year, month = self._discover_metadata(sheet)
        h_row = self._find_header_row(sheet)

        t_col, s_col = None, None
        for c in range(1, (sheet.max_column or 0) + 1):
            val = str(sheet.cell(row=h_row, column=c).value or "").strip().upper()
            if any(k in val for k in self.HEADER_TERRITORY_KEYWORDS):
                t_col = c
            elif any(k in val for k in self.HEADER_SUBTERRITORY_KEYWORDS):
                s_col = c

        if not t_col or not s_col:
            raise ValueError("Fail Fast: Territory columns missing in header row.")

        d_start = self._find_data_start(sheet, h_row, t_col)
        d_end = self._find_data_end(sheet, d_start)

        struct = {
            "sheet_name": orig_name,
            "sheet_type": self.get_sheet_type(orig_name),
            "period_type": ptype,
            "year": year,
            "month": month,
            "header_row": h_row,
            "data_start_row": d_start,
            "data_end_row": d_end,
            "max_columns": sheet.max_column or 0,
            "territory_column": t_col,
            "subterritory_column": s_col,
            "product_columns": self._extract_product_columns(sheet, h_row),
            "product_groups": self._extract_product_groups(sheet, h_row),
        }

        for k, v in struct.items():
            if v is None or (isinstance(v, (dict, list)) and not v):
                raise ValueError(f"Fail Fast: Structure validation failed. Field '{k}' is empty.")

        logger.info(
            "Structure Discovery Completed | Sheet: %s | Period: %s (%d/%d) | Rows: %d-%d",
            orig_name, ptype, month, year, d_start, d_end
        )
        return struct

    def _parse_sheet_records(self, structure_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse raw records from worksheet data rows based on discovered structure."""
        if not self._workbook:
            raise ValueError("Workbook is not loaded.")

        sheet_name = structure_info["sheet_name"]
        sheet = self._workbook[sheet_name]

        start_row = structure_info["data_start_row"]
        end_row = structure_info["data_end_row"]
        t_col = structure_info["territory_column"]
        s_col = structure_info["subterritory_column"]
        product_cols = structure_info["product_columns"]
        product_groups = structure_info["product_groups"]

        prod_to_group_map = {}
        for group_name, prods in product_groups.items():
            for p in prods:
                prod_to_group_map[p] = group_name

        period_type = structure_info["period_type"]
        year = structure_info["year"]
        month = structure_info["month"]
        
        if period_type == "MONTHLY":
            week_number = None
        else:
            # TODO: metadata parser tamamlandığında gerçek week number okunacak
            week_number = None

        records: List[Dict[str, Any]] = []

        for r in range(start_row, end_row + 1):
            territory_val = sheet.cell(row=r, column=t_col).value
            if territory_val is None or str(territory_val).strip() == "":
                continue
            territory = str(territory_val).strip()

            subterritory_val = sheet.cell(row=r, column=s_col).value
            subterritory = str(subterritory_val).strip() if subterritory_val is not None else ""

            for prod_name, col_idx in product_cols.items():
                cell_val = sheet.cell(row=r, column=col_idx).value
                if cell_val is None or str(cell_val).strip() == "":
                    continue

                try:
                    metric_value = float(cell_val)
                except (ValueError, TypeError):
                    continue

                if prod_name not in prod_to_group_map:
                    raise ValueError(
                        f"Fail Fast: Product '{prod_name}' has no discovered product group."
                    )
                product_group = prod_to_group_map[prod_name]

                sheet_type = structure_info["sheet_type"]
                metric_type = "TL" if "VALUE" in sheet_type or "TL" in sheet_name.upper() else "UNIT"

                record = {
                    "year": year,
                    "month": month,
                    "week_number": week_number,
                    "sheet_name": sheet_name,
                    "period_type": period_type,
                    "territory": territory,
                    "subterritory": subterritory,
                    "product_group": product_group,
                    "product_name": prod_name,
                    "metric_type": metric_type,
                    "metric_value": metric_value,
                    "source_row": r,
                }
                records.append(record)

        logger.info("Parsed %d records from sheet '%s'", len(records), sheet_name)
        return records

    def _save_records(self, records: List[Dict[str, Any]]) -> int:
        """Persist parsed records into CompetitionData using bulk insert with transaction control."""
        if self.upload_id is None:
            raise ValueError("Fail Fast: upload_id is required to persist competition records.")

        if not records:
            return 0

        try:
            valid_keys = {c.name for c in CompetitionData.__table__.columns}
            mappings = []
            for rec in records:
                m = {k: v for k, v in rec.items() if k in valid_keys}
                m["upload_id"] = self.upload_id
                mappings.append(m)

            db.session.bulk_insert_mappings(CompetitionData, mappings)
            db.session.commit()
            inserted_count = len(mappings)
            logger.info("Successfully persisted %d competition records for upload_id=%d", inserted_count, self.upload_id)

            # Update IMSUpload status and metadata post-commit
            try:
                upload_record = db.session.query(IMSUpload).filter_by(id=self.upload_id).first()
                if upload_record:
                    upload_record.competition_imported = True
                    upload_record.competition_record_count = inserted_count
                    upload_record.competition_imported_at = datetime.utcnow()
                    db.session.commit()
            except Exception as update_exc:
                logger.warning("Failed to update IMSUpload status for upload_id=%d: %s", self.upload_id, update_exc)

            return inserted_count
        except Exception as exc:
            db.session.rollback()
            err_msg = f"Failed to persist competition records, rolled back: {exc}"
            logger.error(err_msg)
            raise RuntimeError(err_msg) from exc

    def run(self) -> dict:
        if not self.file_path:
            raise ValueError("File path not provided.")
        if self.upload_id is None:
            raise ValueError("Fail Fast: upload_id is required to run competition import.")

        try:
            self.load_workbook(self.file_path)
            self.validate_workbook()

            for s_name in self.SUPPORTED_SHEETS:
                self.validate_sheet_structure(s_name)

            structures = {s: self._parse_sheet_structure(s) for s in self.get_supported_sheets()}

            all_records = []
            for s_name, struct_info in structures.items():
                sheet_records = self._parse_sheet_records(struct_info)
                all_records.extend(sheet_records)

            existing_record = (
                db.session.query(CompetitionData)
                .filter_by(upload_id=self.upload_id)
                .first()
            )
            if existing_record:
                raise ValueError(
                    f"Fail Fast: Competition data already imported for upload_id={self.upload_id}"
                )

            inserted_count = self._save_records(all_records)

            return {
                "success": True,
                "service": "CompetitionImportService",
                "status": "PARSER_RECORDS_EXTRACTED_AND_SAVED",
                "supported_sheets": self.get_supported_sheets(),
                "record_count": len(all_records),
                "inserted_count": inserted_count,
                "errors": self.errors,
                "warnings": self.warnings,
            }
        finally:
            if self._workbook:
                try:
                    self._workbook.close()
                    logger.info("Workbook safely closed.")
                except Exception as close_exc:
                    logger.warning("Failed to close workbook cleanly: %s", close_exc)
