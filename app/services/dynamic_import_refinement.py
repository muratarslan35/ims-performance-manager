"""Refinements for the content-first IMS import contract.

These guards keep representative-level sources usable even when aggregate rows
are absent, while preferring explicit dimension headers over decorative/group
rows in competition worksheets.  No business-source priority or reconciliation
rule is relaxed.
"""
from __future__ import annotations

import re

from app.services import dynamic_import_contract as base


class FlexibleSemanticLocator(base.WorkbookSemanticLocator):
    """Locate semantic sources without requiring optional NATIONAL rows.

    NATIONAL evidence increases confidence for a candidate but is not required
    to read representative-level actual/target data. Official aggregate writers
    still persist only rows that explicitly identify NATIONAL/region totals and
    never synthesize them from person rows.
    """

    def _candidate_profile(self, sheet_name, frame, capability: str):
        if frame is None or len(frame) < 2 or frame.shape[1] < 2:
            return None
        best = None
        for header_row in range(min(self.MAX_HEADER_SCAN_ROWS, len(frame))):
            product_count = self._header_product_count(frame, header_row)
            if product_count == 0:
                continue
            product_metrics, duplicates = self._classify_product_columns(frame, header_row, capability)
            if duplicates:
                continue
            if capability == "balance":
                target_count = sum("target_tl" in metrics for metrics in product_metrics.values())
                balance_tl_count = sum("balance_tl" in metrics for metrics in product_metrics.values())
                balance_unit_count = sum("balance_unit" in metrics for metrics in product_metrics.values())
                actual_count = sum("actual_tl" in metrics for metrics in product_metrics.values())
                if not target_count or not balance_tl_count or not balance_unit_count:
                    continue
                score = 100 + min(target_count, 20) + min(balance_tl_count, 20) + min(balance_unit_count, 20)
                score += min(actual_count, 10)
            else:
                tl_count = sum("actual_tl" in metrics for metrics in product_metrics.values())
                unit_count = sum("actual_unit" in metrics for metrics in product_metrics.values())
                if not tl_count or not unit_count:
                    continue
                score = 100 + min(tl_count, 30) + min(unit_count, 30)

            metric_columns = {
                column
                for metrics in product_metrics.values()
                for column in metrics.values()
            }
            try:
                representative_column, location_column = self._dimension_columns(
                    frame, header_row, metric_columns
                )
            except ValueError:
                continue

            # A representative-level cumulative source is stronger than a
            # brick/location matrix that happens to expose the same product
            # metrics.  Score semantic evidence from the resolved master and
            # explicit representative headers; never from worksheet names or
            # physical column positions. Identical authoritative sources retain
            # identical scores and therefore still fail closed in locate().
            representative_evidence = 0
            header_context = " ".join(
                base._norm(frame.iloc[row, representative_column])
                for row in range(max(0, header_row - 2), header_row + 1)
            )
            representative_headers = getattr(self.importer, "REPRESENTATIVE_HEADERS", {
                "TEMSILCI", "REPRESENTATIVE", "TTS ISMI", "ADI SOYADI",
            })
            if any(token in header_context for token in representative_headers):
                representative_evidence += 25

            matched_representative_ids = []
            vacancy_keys = []
            for row_index in range(
                header_row + 1,
                min(len(frame), header_row + 1 + self.MAX_PROFILE_ROWS),
            ):
                value = self.importer.clean_text(frame.iloc[row_index, representative_column])
                if not value or base._norm(value) == "NATIONAL":
                    continue
                if self.importer._is_vacancy_representative(value):
                    vacancy_keys.append(base._norm(value))
                    continue
                try:
                    match = self.importer.resolve_representative_match(value)
                except Exception:
                    match = {"matched": False}
                if match.get("matched"):
                    obj = match.get("object")
                    matched_representative_ids.append(
                        getattr(obj, "id", None) or base._norm(value)
                    )

            semantic_ids = matched_representative_ids + vacancy_keys
            if semantic_ids:
                unique_count = len(set(semantic_ids))
                uniqueness_ratio = unique_count / len(semantic_ids)
                # Representative summaries are one row per semantic identity.
                # Brick matrices repeat the same representative over locations;
                # their lower uniqueness ratio is therefore weaker authority.
                representative_evidence += min(unique_count, 20)
                representative_evidence += int(round(uniqueness_ratio * 40))
                duplicate_count = len(semantic_ids) - unique_count
                representative_evidence -= min(duplicate_count, 20)
            score += representative_evidence

            # Aggregate rows are confidence evidence, not a prerequisite for
            # representative-level parsing. This preserves partial/compact IMS
            # worksheets while aggregate persistence remains explicit-only.
            national_count = sum(
                base._norm(frame.iloc[row, representative_column]) == "NATIONAL"
                for row in range(header_row + 1, min(len(frame), header_row + 40))
            )
            if national_count:
                score += 20

            profile = base.SemanticSheetProfile(
                sheet_name=str(sheet_name),
                dataframe=frame,
                header_row=header_row,
                representative_column=representative_column,
                location_column=location_column,
                product_metrics=product_metrics,
                score=score,
                capability=capability,
            )
            if best is None or profile.score > best.score:
                best = profile
        return best


def refined_competition_structure(service, sheet_name):
    """Content-first competition structure parser with header-quality ranking."""
    if not service._workbook:
        raise ValueError("Çalışma kitabı yüklenmemiş.")
    actual_map = {
        service._normalize_sheet_name(name): name for name in service._workbook.sheetnames
    }
    norm_target = service._normalize_sheet_name(sheet_name)
    if norm_target not in actual_map:
        raise ValueError(f"Sayfa bulunamadı: '{sheet_name}'")
    original = actual_map[norm_target]
    sheet = service._workbook[original]
    period_type, year, month = service._discover_metadata(sheet)

    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0
    best = None
    explicit_dimension_tokens = (
        "IAM BRICK", "BRICK", "TERRITOR", "SUBTERRITOR", "TTS ISMI",
        "TEMSILCI", "REPRESENTATIVE", "BOLGE", "REGION", "NATIONAL",
    )

    for row in range(1, min(max_row, 80) + 1):
        values = [service._get_cell_value(sheet, row, column) for column in range(1, max_col + 1)]
        normalized = [service._normalize_turkish_text(value) for value in values]
        product_columns = {}
        numeric_coverage = 0
        for column, value in enumerate(values, start=1):
            text = str(value).strip() if value is not None else ""
            if not text or service._is_meta_col(text):
                continue
            numeric_below = 0
            for data_row in range(row + 1, min(max_row, row + 250) + 1):
                cell = service._get_cell_value(sheet, data_row, column)
                if isinstance(cell, (int, float)):
                    numeric_below += 1
            if numeric_below:
                product_columns[column] = text
                numeric_coverage += numeric_below

        dimension_candidates = []
        for column, label in enumerate(normalized, start=1):
            if any(token in label for token in explicit_dimension_tokens):
                dimension_candidates.append(column)
        explicit_dimension_count = len(dimension_candidates)

        if product_columns and len(dimension_candidates) < 2:
            inferred = []
            for column in range(1, max_col + 1):
                if column in product_columns:
                    continue
                score = 0
                for data_row in range(row + 1, min(max_row, row + 50) + 1):
                    value = str(service._get_cell_value(sheet, data_row, column) or "").strip()
                    normalized_value = service._normalize_turkish_text(value)
                    if normalized_value == "NATIONAL":
                        score += 5
                    if re.match(r"^\s*\d{3}\b", normalized_value):
                        score += 4
                    if value and " " in value and not re.search(r"\d", value):
                        score += 1
                if score:
                    inferred.append((score, column))
            inferred.sort(reverse=True)
            dimension_candidates.extend(
                column for _score, column in inferred[:2]
                if column not in dimension_candidates
            )

        if not product_columns or not dimension_candidates:
            continue

        # Explicit dimension labels are stronger header evidence than a sparse
        # decorative/group row whose columns merely happen to have numbers
        # beneath them. Product breadth remains useful for pivot-style headers
        # that legitimately omit dimension labels.
        # Prefer the header that explains the greatest numeric body
        # coverage. Explicit dimension labels are a high-confidence semantic
        # discriminator, while full-body coverage prevents selecting a narrow
        # decorative sub-block from a wide competition pivot.
        score = (
            numeric_coverage * 10
            + len(product_columns) * 4
            + len(dimension_candidates) * 3
            + explicit_dimension_count * 250
        )
        if best is None or score > best[0]:
            best = (score, row, product_columns, dimension_candidates)

    if best is None:
        raise ValueError(f"{original}: rekabet başlığı/dimension yapısı semantik olarak bulunamadı.")

    _score, header_row, product_columns, dimensions = best
    metric_columns = set(product_columns)

    def dimension_score(column):
        territory_score = sub_score = 0
        for data_row in range(header_row + 1, min(max_row, header_row + 250) + 1):
            value = str(service._get_cell_value(sheet, data_row, column) or "").strip()
            normalized_value = service._normalize_turkish_text(value)
            if re.match(r"^\s*\d{3}\b", normalized_value):
                territory_score += 4
            if normalized_value == "NATIONAL":
                sub_score += 5
            if value and " " in value and not re.search(r"\d", value):
                sub_score += 1
        return territory_score, sub_score

    ranked = [
        (column, *dimension_score(column))
        for column in dimensions
        if column not in metric_columns
    ]
    if not ranked:
        raise ValueError(f"{original}: rekabet dimension kolonları bulunamadı.")

    dimension_labels = {
        column: service._normalize_turkish_text(
            service._get_cell_value(sheet, header_row, column)
        )
        for column, _territory_score, _sub_score in ranked
    }
    territory_semantic = [
        item for item in ranked
        if any(token in dimension_labels[item[0]] for token in ("TERRITOR", "BOLGE", "REGION"))
        and not any(token in dimension_labels[item[0]] for token in ("SUBTERRITOR", "BRICK"))
    ]
    territory_pool = territory_semantic or ranked
    territory_column = max(
        territory_pool,
        key=lambda item: (item[1], -item[2]),
    )[0]

    sub_candidates = [item for item in ranked if item[0] != territory_column]
    finest_geo = [
        item for item in sub_candidates
        if any(token in dimension_labels[item[0]] for token in ("SUBTERRITOR", "IAM BRICK", "BRICK"))
    ]
    representative_semantic = [
        item for item in sub_candidates
        if any(token in dimension_labels[item[0]] for token in ("TTS ISMI", "TEMSILCI", "REPRESENTATIVE"))
    ]
    sub_pool = finest_geo or representative_semantic or sub_candidates
    subterritory_column = (
        max(sub_pool, key=lambda item: (item[2], -item[1]))[0]
        if sub_pool else territory_column
    )

    data_start = None
    for row in range(header_row + 1, max_row + 1):
        territory = service._get_cell_value(sheet, row, territory_column)
        subterritory = service._get_cell_value(sheet, row, subterritory_column)
        if str(territory or "").strip() or str(subterritory or "").strip():
            data_start = row
            break
    if data_start is None:
        raise ValueError(f"{original}: rekabet veri başlangıcı bulunamadı.")
    data_end = service._find_data_end(sheet, data_start)

    original_groups = service._extract_product_groups(sheet, header_row)
    dimension_set = {item[0] for item in ranked}
    product_columns = {
        column: name
        for column, name in product_columns.items()
        if column not in dimension_set
    }
    product_groups = {
        group: [(name, column) for name, column in products if column in product_columns]
        for group, products in original_groups.items()
    }
    product_groups = {group: products for group, products in product_groups.items() if products}
    if not product_columns or not product_groups:
        raise ValueError(f"{original}: rekabet ürün kolonları semantik olarak bulunamadı.")

    return {
        "sheet_name": original,
        "sheet_type": service.get_sheet_type(original),
        "period_type": period_type,
        "year": year,
        "month": month,
        "header_row": header_row,
        "data_start_row": data_start,
        "data_end_row": data_end,
        "max_columns": max_col,
        "territory_column": territory_column,
        "subterritory_column": subterritory_column,
        "product_columns": product_columns,
        "product_groups": product_groups,
    }


def install_dynamic_import_refinement():
    """Install the second-pass semantic ranking refinements."""
    from app.services.competition_import_service import CompetitionImportService
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_dynamic_import_refinement_installed", False):
        return

    # Existing contract functions resolve this module global at runtime, so
    # replacing the locator class upgrades all later importer instances without
    # duplicating their business-write logic.
    base.WorkbookSemanticLocator = FlexibleSemanticLocator
    CompetitionImportService._parse_sheet_structure = refined_competition_structure
    IMSImportService._dynamic_import_refinement_installed = True
