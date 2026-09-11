"""Compatibility adapter for the temporary product-KPI IMS workbook layout.

The legacy readers remain untouched.  When the workbook exposes the paired
``2-TTS-BRICK ... REA%`` matrices, this adapter joins their actual columns into
the canonical wide brick-sales shape consumed by :class:`IMSImportService`.
Product KPI sheets supply the named competitor unit observations and the
authoritative PAZAR subtotal.  PP/RANK remain validation-only fields.
Changes here require the same production acceptance gates as other IMS importers.
"""
from __future__ import annotations

import re

import pandas as pd

from app.services.alias_service import AliasService


COMPAT_SHEET_NAME = "IMS COMPAT BRICK SATIS"
COMPAT_BALANCE_NAME = "IMS COMPAT BAKIYE"
COMPAT_WEEKLY_NAME = "IMS COMPAT HAFTALIK CIKIS"
COMPAT_COMPETITION_PREFIX = "AYLIK REKABET KUTU IMS COMPAT"
_KPI_RE = re.compile(r"^2 KUTU .+ KPI$")


def _norm(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return AliasService.normalize(value)


def _find_matrix(workbook, metric):
    token = "TL" if metric == "tl" else "KUTU"
    matches = [
        (name, frame) for name, frame in workbook.items()
        if "TTS BRICK" in _norm(name) and token in _norm(name) and "REA" in _norm(name)
    ]
    if len(matches) > 1:
        raise ValueError(f"Yeni IMS formatında birden fazla {token} brick matrisi bulundu.")
    return matches[0] if matches else (None, None)


def is_product_kpi_sheet(sheet_name):
    return bool(_KPI_RE.match(_norm(sheet_name)))


def _matrix_plan(frame, metric):
    for header_row in range(min(12, len(frame))):
        row = [_norm(value) for value in frame.iloc[header_row].tolist()]
        if "1 TTS" not in row or "2 TTS" not in row:
            continue
        group_row = header_row - 1
        if group_row < 0:
            continue
        current_product = ""
        products = {}
        for column in range(frame.shape[1]):
            group = _norm(frame.iloc[group_row, column])
            if group:
                current_product = group
            phase = _norm(frame.iloc[header_row, column])
            if current_product and "URUN CIKIS" in phase:
                products[current_product] = column
        if not products:
            continue
        return {
            "header_row": header_row,
            "data_start": header_row + 1,
            "region": 0,
            "province": 1,
            "brick": 2,
            "primary_rep": row.index("1 TTS"),
            "secondary_rep": row.index("2 TTS"),
            "products": products,
            "metric": metric,
        }
    raise ValueError(f"Yeni IMS {metric.upper()} brick matrisi başlıkları bulunamadı.")


def build_canonical_brick_frame(workbook, *, file_path=None):
    """Return ``(frame, consumed_names)`` or ``(None, set())`` for legacy files."""
    tl_name, tl_frame = _find_matrix(workbook, "tl")
    unit_name, unit_frame = _find_matrix(workbook, "unit")
    if not tl_name and not unit_name:
        return None, set()
    if not tl_name or not unit_name:
        raise ValueError("Yeni IMS formatında eşlenik TL ve KUTU brick sayfaları birlikte bulunmalıdır.")

    tl = _matrix_plan(tl_frame, "tl")
    unit = _matrix_plan(unit_frame, "unit")
    shared_products = sorted(set(tl["products"]) & set(unit["products"]))
    if set(tl["products"]) != set(unit["products"]) or not shared_products:
        raise ValueError("Yeni IMS TL/KUTU matrislerinin ürün kapsamı aynı değil.")

    def rows(frame, plan):
        result = {}
        for source_index in range(plan["data_start"], len(frame)):
            values = frame.iloc[source_index]
            key = tuple(
                "" if pd.isna(values.iloc[column]) else str(values.iloc[column]).strip()
                for column in (
                    plan["region"], plan["province"], plan["brick"],
                    plan["primary_rep"], plan["secondary_rep"],
                )
            )
            if not any(key):
                continue
            if key in result:
                raise ValueError(f"Yeni IMS brick matrisinde tekrarlı satır kimliği bulundu: {key}")
            result[key] = values
        return result

    tl_rows, unit_rows = rows(tl_frame, tl), rows(unit_frame, unit)
    # Pivot filters in the temporary export can mark most TL detail rows as
    # hidden while leaving their cached values intact. The normal importer
    # correctly honours hidden rows for legacy reports, but this paired matrix
    # must reconcile against the complete KUTU key set. Reload only this pair
    # without display filtering when needed.
    if set(tl_rows) != set(unit_rows) and file_path:
        raw_pair = pd.read_excel(file_path, sheet_name=[tl_name, unit_name], header=None)
        tl_frame, unit_frame = raw_pair[tl_name], raw_pair[unit_name]
        tl, unit = _matrix_plan(tl_frame, "tl"), _matrix_plan(unit_frame, "unit")
        tl_rows, unit_rows = rows(tl_frame, tl), rows(unit_frame, unit)
    if set(tl_rows) != set(unit_rows):
        only_tl = list(set(tl_rows) - set(unit_rows))[:3]
        only_unit = list(set(unit_rows) - set(tl_rows))[:3]
        raise ValueError(
            "Yeni IMS TL/KUTU brick satırları eşleşmiyor. "
            f"Yalnız TL={only_tl}, yalnız KUTU={only_unit}"
        )

    headers = ["BÖLGE", "İL", "IAM BRICK", "1 TTS ISMI", "2 TTS ISMI"]
    for product in shared_products:
        headers.extend((f"{product} KUTU ÇIKIŞ", f"{product} TL ÇIKIŞ"))
    output = []
    for key, tl_values in tl_rows.items():
        unit_values = unit_rows[key]
        row = list(key)
        for product in shared_products:
            row.extend((
                unit_values.iloc[unit["products"][product]],
                tl_values.iloc[tl["products"][product]],
            ))
        output.append(row)
    return pd.DataFrame(output, columns=headers), {tl_name, unit_name}


def _summary_rows(frame, plan):
    """Return source-authoritative national/region rows plus rep brick sums."""
    products = sorted(plan["products"])
    records = []
    representative_totals = {}
    for source_index in range(plan["data_start"], len(frame)):
        row = frame.iloc[source_index]
        territory = "" if pd.isna(row.iloc[plan["region"]]) else str(row.iloc[plan["region"]]).strip()
        province = "" if pd.isna(row.iloc[plan["province"]]) else str(row.iloc[plan["province"]]).strip()
        brick = "" if pd.isna(row.iloc[plan["brick"]]) else str(row.iloc[plan["brick"]]).strip()
        representative = "" if pd.isna(row.iloc[plan["primary_rep"]]) else str(row.iloc[plan["primary_rep"]]).strip()
        normalized_brick = _norm(brick)
        normalized_rep = _norm(representative)
        values = {
            product: {
                "target": pd.to_numeric(pd.Series([row.iloc[plan["products"][product] - 1]]), errors="coerce").fillna(0).iloc[0],
                "actual": pd.to_numeric(pd.Series([row.iloc[plan["products"][product]]]), errors="coerce").fillna(0).iloc[0],
            }
            for product in products
        }
        if normalized_brick == "NATIONAL":
            records.append(("", "NATIONAL", values))
        elif "SUBTOTAL" in normalized_brick and normalized_rep == _norm(territory):
            records.append((territory, representative, values))
        elif representative and normalized_rep not in {"NATIONAL", _norm(territory)}:
            key = (territory, representative)
            bucket = representative_totals.setdefault(
                key, {product: {"target": 0.0, "actual": 0.0} for product in products}
            )
            for product in products:
                bucket[product]["target"] += float(values[product]["target"] or 0)
                bucket[product]["actual"] += float(values[product]["actual"] or 0)
    records.extend((territory, representative, values) for (territory, representative), values in representative_totals.items())
    return products, records


def build_legacy_summary_frames(workbook, *, file_path=None):
    """Build the legacy BAKIYE/TTS views consumed by existing KPI services."""
    tl_name, tl_frame = _find_matrix(workbook, "tl")
    unit_name, unit_frame = _find_matrix(workbook, "unit")
    if not tl_name or not unit_name:
        return {}
    if file_path:
        raw_pair = pd.read_excel(file_path, sheet_name=[tl_name, unit_name], header=None)
        tl_frame, unit_frame = raw_pair[tl_name], raw_pair[unit_name]
    tl_plan, unit_plan = _matrix_plan(tl_frame, "tl"), _matrix_plan(unit_frame, "unit")
    tl_products, tl_rows = _summary_rows(tl_frame, tl_plan)
    unit_products, unit_rows = _summary_rows(unit_frame, unit_plan)
    if tl_products != unit_products:
        raise ValueError("Yeni IMS özet TL/KUTU ürün kapsamı aynı değil.")
    unit_map = {(territory, representative): values for territory, representative, values in unit_rows}
    if {(t, r) for t, r, _ in tl_rows} != set(unit_map):
        raise ValueError("Yeni IMS özet TL/KUTU temsilci kapsamı aynı değil.")

    products = tl_products
    balance_header = [
        None, "AYLIK HEDEF TL", *products,
        None, "AYLIK CIKIS TL", *products,
        None, "AYLIK KUTU HEDEF", *products,
    ]
    weekly_sections = [None, None, "AYLIK TL CIKISI", *([None] * (len(products) - 1)), "AYLIK KUTU CIKISI", *([None] * (len(products) - 1))]
    weekly_products = [None, None, *products, *products]
    balance_rows = [[None] * len(balance_header), balance_header]
    weekly_rows = [weekly_sections, weekly_products]
    for territory, representative, tl_values in tl_rows:
        units = unit_map[(territory, representative)]
        balance_rows.append([
            territory, representative,
            *[tl_values[product]["target"] for product in products], None,
            representative,
            *[tl_values[product]["actual"] for product in products],
            None, representative,
            *[units[product]["target"] for product in products],
        ])
        weekly_rows.append([
            territory, representative,
            *[tl_values[product]["actual"] for product in products],
            *[units[product]["actual"] for product in products],
        ])
    return {
        COMPAT_BALANCE_NAME: pd.DataFrame(balance_rows),
        COMPAT_WEEKLY_NAME: pd.DataFrame(weekly_rows),
    }


def build_competition_frames(workbook):
    """Translate product KPI tabs into legacy monthly brick competition tabs."""
    result = {}
    for sheet_name, frame in workbook.items():
        if not is_product_kpi_sheet(sheet_name):
            continue
        product = _norm(sheet_name).removeprefix("2 KUTU ").removesuffix(" KPI")
        header_row = next((
            row for row in range(min(12, len(frame)))
            if any(_norm(value) == "PAZAR" for value in frame.iloc[row].tolist())
        ), None)
        if header_row is None:
            raise ValueError(f"{sheet_name}: KPI ürün başlığı bulunamadı.")
        columns = []
        for column in range(5, frame.shape[1]):
            label = _norm(frame.iloc[header_row, column])
            if not label or label in {"PP", "RANK"}:
                continue
            columns.append((column, f"{product} SUBTOTAL" if label == "PAZAR" else str(frame.iloc[header_row, column]).strip()))
        rows = [
            [None] * (5 + len(columns)),
            [None] * 5 + [product] + [None] * (len(columns) - 1),
            ["BOLGE", "IL", "IAM BRICK", "1 TTS ISMI", "2 TTS ISMI", *[label for _, label in columns]],
            [None] * (5 + len(columns)),
        ]
        for row_index in range(header_row + 1, len(frame)):
            source = frame.iloc[row_index]
            brick = "" if pd.isna(source.iloc[2]) else str(source.iloc[2]).strip()
            if not brick or _norm(brick) == "NATIONAL" or "SUBTOTAL" in _norm(brick):
                continue
            rows.append([
                *[None if pd.isna(source.iloc[column]) else source.iloc[column] for column in range(5)],
                *[None if pd.isna(source.iloc[column]) else source.iloc[column] for column, _ in columns],
            ])
        result[f"{COMPAT_COMPETITION_PREFIX} {product}"] = pd.DataFrame(rows)
    return result


def validate_product_kpi_sheets(workbook, canonical):
    """Use optional KPI sheets only as a NATIONAL control for core units."""
    checked = 0
    key_columns = ["BÖLGE", "İL", "IAM BRICK", "1 TTS ISMI", "2 TTS ISMI"]
    canonical_rows = {
        tuple(str(value).strip() for value in row[key_columns].tolist()): row
        for _, row in canonical.iterrows()
    }
    for sheet_name, frame in workbook.items():
        if not is_product_kpi_sheet(sheet_name):
            continue
        product = _norm(sheet_name).removeprefix("2 KUTU ").removesuffix(" KPI")
        source_column = f"{product} KUTU ÇIKIŞ"
        if source_column not in canonical.columns:
            raise ValueError(f"{sheet_name}: KPI ürünü ana KUTU matrisinde bulunamadı ({product}).")
        header_row = next((
            row for row in range(min(12, len(frame)))
            if any(_norm(value) == "PAZAR" for value in frame.iloc[row].tolist())
        ), None)
        if header_row is None:
            raise ValueError(f"{sheet_name}: KPI ürün başlığı bulunamadı.")
        product_columns = [
            column for column in range(frame.shape[1])
            if _norm(frame.iloc[header_row, column]).startswith(product)
        ]
        if len(product_columns) != 1:
            raise ValueError(f"{sheet_name}: KPI ana ürün kolonu tekil değil ({product}).")
        product_column = product_columns[0]
        national_seen = False
        for row_index in range(header_row + 1, len(frame)):
            values = frame.iloc[row_index]
            key = tuple(
                "" if pd.isna(values.iloc[column]) else str(values.iloc[column]).strip()
                for column in range(5)
            )
            if not any(key):
                continue
            # KPI detail rows can use a different commercial brick allocation
            # from the TTS matrix. They are extra analytical data, not a source
            # for representative sales. Only the common NATIONAL control has
            # identical business meaning in both layouts.
            if _norm(key[2]) != "NATIONAL":
                continue
            source = canonical_rows.get(key)
            if source is None:
                raise ValueError(f"{sheet_name}: KPI satırı ana brick matrisinde bulunamadı: {key}")
            kpi_value = pd.to_numeric(pd.Series([values.iloc[product_column]]), errors="coerce").iloc[0]
            core_value = pd.to_numeric(pd.Series([source[source_column]]), errors="coerce").iloc[0]
            if pd.isna(kpi_value) and pd.isna(core_value):
                pass
            elif pd.isna(kpi_value) or pd.isna(core_value) or abs(float(kpi_value) - float(core_value)) > 1e-6:
                raise ValueError(
                    f"{sheet_name}: KPI doğrulaması ana KUTU matrisiyle uyuşmuyor; "
                    f"brick={key[2]}, KPI={kpi_value}, ana={core_value}."
                )
            national_seen = True
        if not national_seen:
            raise ValueError(f"{sheet_name}: KPI NATIONAL doğrulama satırı bulunamadı.")
        checked += 1
    return checked


def install_kpi_workbook_compat():
    from app.services.competition_import_service import CompetitionImportService
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_kpi_workbook_compat_installed", False):
        return

    original_analyze = IMSImportService.analyze_workbook

    def analyze_with_kpi_compat(self):
        canonical, consumed = build_canonical_brick_frame(
            self.workbook or {}, file_path=self.file_path
        )
        if canonical is None:
            return original_analyze(self)
        self.statistics["kpi_validation_sheets"] = validate_product_kpi_sheets(
            self.workbook or {}, canonical
        )
        compat_frames = build_legacy_summary_frames(
            self.workbook or {}, file_path=self.file_path
        )
        compat_frames.update(build_competition_frames(self.workbook or {}))
        self.workbook.update(compat_frames)
        analyses = []
        for sheet_name, frame in (self.workbook or {}).items():
            if sheet_name in consumed or is_product_kpi_sheet(sheet_name) or sheet_name in compat_frames:
                continue
            # The temporary workbook's representative summary and trend tabs
            # are filtered pivots. The paired brick matrices are the complete
            # source and must be the only sales authority for this format.
            normalized = _norm(sheet_name)
            if (
                normalized.startswith("1 TTS ")
                or "EKIP HAFTALIK TREND" in normalized
                or "ILGILI HAFTALIK" in normalized
            ):
                continue
            analysis = self.analyze_sheet(sheet_name, frame)
            if analysis is not None:
                analyses.append(analysis)
        analyses.append({
            "sheet_name": COMPAT_SHEET_NAME,
            "sheet_type": "brick_sales",
            "header_row": 0,
            "dataframe": canonical,
        })
        self.statistics["kpi_workbook_compat"] = 1
        self.statistics["kpi_workbook_brick_rows"] = len(canonical)
        return analyses

    IMSImportService.analyze_workbook = analyze_with_kpi_compat

    original_supported = CompetitionImportService.get_supported_sheets
    def supported_with_kpi(self):
        return [name for name in original_supported(self) if not is_product_kpi_sheet(name)]

    CompetitionImportService.get_supported_sheets = supported_with_kpi
    IMSImportService._kpi_workbook_compat_installed = True
