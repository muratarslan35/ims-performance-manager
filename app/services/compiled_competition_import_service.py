"""Compiled fast path for competition-sheet imports.

The semantic importer remains the source of truth for workbook discovery and
structure validation.  This specialization only compiles the already-resolved
sheet plan so the hot cell loop does not rebuild/renormalize the same Python
objects hundreds of thousands of times.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Tuple

from app.extensions import db
from app.models import CompetitionData
from app.services.competition_import_service import (
    CompetitionImportService,
    DefaultGroup,
    MetricType,
    PeriodType,
    SheetType,
    _PreparedWorksheet,
)


class CompiledCompetitionImportService(CompetitionImportService):
    """Semantically identical competition importer with a compiled hot loop.

    Discovery, source-value parsing, duplicate/conflict policy, zero-vs-blank
    behavior and the outer IMS transaction all remain unchanged. Values that
    are constant for a sheet/column/row are normalized once instead of once per
    numeric cell. Prepared pandas sheets are streamed row-by-row and are never
    expanded into a second Python tuple matrix.
    """

    def _get_cell_value(self, sheet: Any, row: int, col: int) -> Any:
        """Read prepared workbook cells without materializing a second sheet.

        The normal service caches openpyxl rows because random access on a
        ReadOnlyWorksheet restarts the XML stream. The background worker already
        owns sanitized pandas dataframes, so copying a wide competition sheet
        to ``list[tuple]`` only increases RSS and swap pressure. ``iat`` keeps
        semantic discovery O(1) while the hot data loop below uses itertuples.
        """
        if isinstance(sheet, _PreparedWorksheet):
            if row < 1 or col < 1 or row > sheet.max_row or col > sheet.max_column:
                return None
            return sheet._clean_value(sheet._frame.iat[row - 1, col - 1])
        return super()._get_cell_value(sheet, row, col)

    def _find_data_end(self, sheet: Any, start_row: int) -> int:
        """Defer prepared-sheet stop detection to the single streaming pass."""
        if isinstance(sheet, _PreparedWorksheet):
            return int(sheet.max_row or start_row)
        return super()._find_data_end(sheet, start_row)

    @staticmethod
    def _metric_type_for_sheet(sheet_type: str) -> str:
        normalized = str(sheet_type or "").strip().upper()
        if normalized == SheetType.MARKET_REFERENCE.value:
            return MetricType.MARKET_SHARE.value
        if normalized in {
            SheetType.MONTHLY_VALUE.value,
            SheetType.WEEKLY_VALUE.value,
            SheetType.MONTHLY_COMPETITION_VALUE.value,
        }:
            return MetricType.TL.value
        if normalized in {
            SheetType.MONTHLY_UNITS.value,
            SheetType.WEEKLY_UNITS.value,
            SheetType.MONTHLY_COMPETITION_UNITS.value,
        }:
            return MetricType.UNIT.value
        raise ValueError(f"Semantik metric türü çözülemedi: {sheet_type}")

    def _compiled_product_columns(self, structure_info: Dict[str, Any]) -> List[Tuple[int, str, str, bool, bool]]:
        compiled: List[Tuple[int, str, str, bool, bool]] = []
        for raw_group, products in structure_info["product_groups"].items():
            group = self._normalize_turkish_text(raw_group) or DefaultGroup.GENEL.value
            for raw_product, column in products:
                product = self._normalize_turkish_text(raw_product)
                is_grand_total = "GRAND TOTAL" in product or "GENEL TOPLAM" in product
                is_subtotal = not is_grand_total and (
                    "SUBTOTAL" in product
                    or "ARA TOPLAM" in product
                    or product.endswith(" TOPLAM")
                )
                compiled.append((int(column), group, product, is_subtotal, is_grand_total))
        return compiled

    @staticmethod
    def _parse_metric_value(value: Any) -> Tuple[bool, float | None, str | None]:
        if value is None:
            return False, None, None
        normalized = str(value).strip()
        if normalized == "" or normalized.upper() in {"-", "—", "–", "N/A", "NA", "NULL"}:
            return False, None, None
        if isinstance(value, (int, float)):
            return True, float(value), None
        try:
            if normalized.endswith("%"):
                return True, float(normalized[:-1].replace(",", ".")) / 100.0, None
            return True, float(normalized.replace(",", ".")), None
        except (ValueError, TypeError):
            return True, None, normalized

    def _prepared_row_stops_import(self, row_values: Tuple[Any, ...]) -> bool:
        """Mirror the base service's first-empty/total-row termination rule."""
        non_empty = [
            value for value in row_values
            if value is not None and str(value).strip()
        ]
        if not non_empty:
            return True
        return any(
            any(stop in str(value).strip().upper() for stop in self.STOP_KEYWORDS)
            for value in non_empty
        )

    def _source_rows(
        self,
        sheet: Any,
        structure_info: Dict[str, Any],
    ) -> Iterator[Tuple[int, Tuple[Any, ...] | None]]:
        """Yield each prepared source row once, retaining 1-based Excel indices."""
        start_row = int(structure_info["data_start_row"])
        end_row = int(structure_info["data_end_row"])
        data_rows = structure_info.get("data_rows")
        row_numbers = data_rows if data_rows is not None else range(start_row, end_row + 1)

        if not isinstance(sheet, _PreparedWorksheet):
            for source_row in row_numbers:
                yield int(source_row), None
            return

        frame = sheet._frame
        if data_rows is None:
            source_frame = frame.iloc[start_row - 1:end_row]
            for source_row, values in enumerate(
                source_frame.itertuples(index=False, name=None),
                start=start_row,
            ):
                yield source_row, tuple(sheet._clean_value(value) for value in values)
            return

        for source_row in row_numbers:
            source_row = int(source_row)
            if source_row < 1 or source_row > sheet.max_row:
                continue
            values = frame.iloc[source_row - 1].tolist()
            yield source_row, tuple(sheet._clean_value(value) for value in values)

    def _existing_sheet_values(self, norm_sheet_name: str) -> Dict[Tuple[Any, ...], Tuple[float, Any]]:
        """Load only the current sheet's exact duplicate business keys.

        upload_id and normalized sheet name are fixed by the SQL predicate, so
        they do not need to be repeated in every in-memory key.
        """
        seen: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}
        rows = db.session.query(
            CompetitionData.year,
            CompetitionData.month,
            CompetitionData.week_number,
            CompetitionData.territory,
            CompetitionData.subterritory,
            CompetitionData.product_group,
            CompetitionData.product_name,
            CompetitionData.metric_type,
            CompetitionData.metric_value,
            CompetitionData.source_row,
        ).filter_by(
            upload_id=self.upload_id,
            sheet_name=norm_sheet_name,
        ).all()
        for row in rows:
            key = (
                row.year,
                row.month,
                row.week_number,
                self._normalize_turkish_text(row.territory),
                self._normalize_turkish_text(row.subterritory),
                self._normalize_turkish_text(row.product_group) or DefaultGroup.GENEL.value,
                self._normalize_turkish_text(row.product_name),
                str(row.metric_type or "").strip().upper(),
            )
            seen[key] = (float(row.metric_value or 0.0), row.source_row)
        return seen

    def _import_compiled_sheet(self, structure_info: Dict[str, Any], sheet_name: str) -> Dict[str, Any]:
        if self.upload_id is None:
            raise ValueError("Fail Fast: upload_id is required to import competition records.")
        if not self._workbook:
            raise ValueError("Çalışma kitabı yüklenmemiş.")

        started = time.time()
        sheet = self._workbook[structure_info["sheet_name"]]
        norm_sheet_name = self._normalize_turkish_text(sheet_name)
        metric_type = self._metric_type_for_sheet(structure_info["sheet_type"])
        period_type = str(structure_info.get("period_type") or PeriodType.MONTHLY.value)
        year = int(structure_info["year"])
        month = int(structure_info["month"])
        week_number = int(self.week_number) if self.week_number is not None else None
        territory_column = int(structure_info["territory_column"])
        subterritory_column = int(structure_info["subterritory_column"])
        columns = self._compiled_product_columns(structure_info)
        seen = self._existing_sheet_values(norm_sheet_name)

        inserted = 0
        duplicates = 0
        total_input = 0
        mapping_batch: List[Dict[str, Any]] = []
        last_valid_territory = ""

        for source_row, prepared_values in self._source_rows(sheet, structure_info):
            if prepared_values is not None and self._prepared_row_stops_import(prepared_values):
                break

            def cell_value(column: int) -> Any:
                if prepared_values is not None:
                    return prepared_values[column - 1] if column <= len(prepared_values) else None
                return self._get_cell_value(sheet, source_row, column)

            territory_value = cell_value(territory_column)
            if territory_value is not None and str(territory_value).strip() != "":
                last_valid_territory = str(territory_value).strip()
            if not last_valid_territory:
                continue

            territory_upper = last_valid_territory.upper()
            if territory_upper in {"BOLGE", "BÖLGE", "NATIONAL"} or any(
                stop in territory_upper for stop in self.STOP_KEYWORDS
            ):
                continue

            subterritory_value = cell_value(subterritory_column)
            raw_subterritory = str(subterritory_value).strip() if subterritory_value is not None else ""
            subterritory_upper = raw_subterritory.upper()
            if any(stop in subterritory_upper for stop in self.STOP_KEYWORDS):
                continue

            # These dimensions are shared by every product observation in this
            # row, so normalize them exactly once.
            territory = self._normalize_turkish_text(last_valid_territory)
            subterritory = self._normalize_turkish_text(raw_subterritory)

            for column, product_group, product_name, is_subtotal, is_grand_total in columns:
                cell = cell_value(column)
                has_observation, metric_value, invalid_text = self._parse_metric_value(cell)
                if not has_observation:
                    self.parse_statistics["blank_cells"] += 1
                    continue
                if metric_value is None:
                    self.parse_statistics["invalid_cells"] += 1
                    self.invalid_cells.append({
                        "sheet_name": sheet_name,
                        "source_row": source_row,
                        "source_column": column,
                        "product_group": product_group,
                        "product_name": product_name,
                        "value": invalid_text,
                    })
                    continue

                self.parse_statistics["numeric_cells"] += 1
                total_input += 1
                key = (
                    year,
                    month,
                    week_number,
                    territory,
                    subterritory,
                    product_group,
                    product_name,
                    metric_type,
                )
                prior = seen.get(key)
                if prior is not None:
                    prior_value, prior_row = prior
                    if abs(prior_value - metric_value) > 1e-9:
                        raise ValueError(
                            "Aynı rekabet veri anahtarında çelişen değerler bulundu: "
                            f"key={(self.upload_id, norm_sheet_name, *key)}, "
                            f"first={prior_value}, second={metric_value}, "
                            f"first_source={{'row': {prior_row!r}, 'column': None}}, "
                            f"second_source={{'row': {source_row!r}, 'column': {column!r}}}"
                        )
                    duplicates += 1
                    continue

                seen[key] = (metric_value, source_row)
                mapping = {
                    "upload_id": self.upload_id,
                    "sheet_name": norm_sheet_name,
                    "period_type": period_type,
                    "year": year,
                    "month": month,
                    "week_number": week_number,
                    "territory": territory,
                    "subterritory": subterritory,
                    "product_group": product_group,
                    "product_name": product_name,
                    "metric_type": metric_type,
                    "metric_value": metric_value,
                    "is_subtotal": is_subtotal,
                    "is_grand_total": is_grand_total,
                    "source_row": int(source_row),
                }
                # Keep exact parity with the standard persistence mapping:
                # optional None values are omitted rather than passed through
                # explicitly. This protects byte-level regression equivalence.
                mapping_batch.append({key: value for key, value in mapping.items() if value is not None})
                if len(mapping_batch) >= self.BULK_CHUNK_SIZE:
                    inserted += self.bulk_insert(mapping_batch)
                    mapping_batch.clear()

        if mapping_batch:
            inserted += self.bulk_insert(mapping_batch)
            mapping_batch.clear()

        return {
            "sheet_name": sheet_name,
            "upload_id": self.upload_id,
            "total_input": total_input,
            "inserted": inserted,
            "duplicates": duplicates,
            "invalid": 0,
            "execution_time": round(time.time() - started, 4),
            "warnings": [],
        }

    def run(self) -> dict:
        """Run the standard semantic discovery with a compiled persistence loop."""
        if not self.file_path:
            raise ValueError("Dosya yolu belirtilmedi.")
        if self.upload_id is None:
            raise ValueError("Yükleme kimliği (upload_id) gerekli.")

        pipeline_started = time.time()
        try:
            self.load_workbook(self.file_path)
            self.validate_workbook()
            supported_sheets = self.get_supported_sheets()
            for sheet_name in supported_sheets:
                self.validate_sheet_structure(sheet_name)

            sheet_statistics = []
            total_inserted = 0
            total_duplicates = 0
            total_invalid = 0

            for sheet_name in supported_sheets:
                try:
                    structure = self._parse_sheet_structure(sheet_name)
                    stats = self._import_compiled_sheet(structure, sheet_name)
                    if self.invalid_cells:
                        raise ValueError(
                            "Rekabet sayfalarında geçersiz metrik hücreleri bulundu: "
                            f"count={len(self.invalid_cells)}, sample={self.invalid_cells[:10]}"
                        )
                    sheet_statistics.append(stats)
                    total_inserted += stats["inserted"]
                    total_duplicates += stats["duplicates"]
                    total_invalid += stats["invalid"]
                finally:
                    self._sheet_values.pop(sheet_name, None)

            if total_invalid or total_inserted + total_duplicates != self.parse_statistics["numeric_cells"]:
                raise ValueError(
                    "Rekabet veri mutabakatı başarısız: "
                    f"numeric={self.parse_statistics['numeric_cells']}, inserted={total_inserted}, "
                    f"duplicates={total_duplicates}, invalid={total_invalid}"
                )
            if total_inserted == 0:
                raise ValueError("Rekabet sayfalarında aktarılabilir sayısal kayıt bulunamadı.")

            return {
                "success": True,
                "service": "CompetitionImportService",
                "status": "ENTERPRISE_RECORDS_IMPORTED_SUCCESSFULLY",
                "supported_sheets": supported_sheets,
                "summary": {
                    "total_inserted": total_inserted,
                    "total_duplicates": total_duplicates,
                    "total_invalid": total_invalid,
                    **self.parse_statistics,
                    "execution_time": round(time.time() - pipeline_started, 4),
                    "compiled_fast_path": True,
                    "prepared_sheet_streaming": True,
                },
                "sheet_statistics": sheet_statistics,
                "errors": self.errors,
                "warnings": self.warnings,
            }
        finally:
            if self._workbook:
                try:
                    self._workbook.close()
                except Exception:
                    pass
