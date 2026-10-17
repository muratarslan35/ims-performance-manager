"""Adaptive target/aggregate authority for paired KPI-style IMS matrices.

The legacy importer remains unchanged.  When the already-supported paired
TL/KUTU TTS layout is present, this adapter reads the source rows directly and
persists targets plus NATIONAL/region aggregates from that same pair.
"""
from __future__ import annotations

import re
import pandas as pd

from app.extensions import db
from app.models import IMSSummary, Target
from app.services.alias_service import AliasService


def _norm(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return AliasService.normalize(value)


def _matrix_plan(frame):
    for header_row in range(min(20, len(frame))):
        row = [_norm(value) for value in frame.iloc[header_row].tolist()]
        # Preserve the legacy numbered header while accepting the newer
        # semantic identity pair used by week 41 exports: "TTS / BRICK" + "TTS".
        if "1 TTS" in row:
            primary_rep = row.index("1 TTS")
            brick_column = primary_rep - 1
            secondary_rep = row.index("2 TTS") if "2 TTS" in row else None
        else:
            brick_columns = [i for i, label in enumerate(row) if label == "TTS BRICK"]
            semantic_rep_columns = [
                i for i, label in enumerate(row)
                if label == "TTS" and brick_columns and i == brick_columns[0] + 1
            ]
            if len(brick_columns) != 1 or len(semantic_rep_columns) != 1:
                continue
            brick_column = brick_columns[0]
            primary_rep = semantic_rep_columns[0]
            secondary_rep = None

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
        if primary_rep < 3:
            continue
        return {
            "header_row": header_row,
            "data_start": header_row + 1,
            "region": 0,
            "province": 1,
            "brick": brick_column,
            "primary_rep": primary_rep,
            "secondary_rep": secondary_rep,
            "products": products,
        }
    return None


def _metric_hint(sheet_name, frame):
    surface = _norm(sheet_name)
    preview = " ".join(
        _norm(value)
        for row in range(min(5, len(frame)))
        for value in frame.iloc[row].tolist()
    )
    text = f" {surface} {preview} "
    has_tl = bool(re.search(r"(?:^|\s)TL(?:\s|$)", text))
    has_unit = any(token in text for token in (" KUTU ", " BOX ", " UNIT ", " ADET "))
    if has_tl and not has_unit:
        return "tl"
    if has_unit and not has_tl:
        return "unit"
    return None


def _find_pair(workbook):
    candidates = {"tl": [], "unit": []}
    structural = []
    for name, frame in (workbook or {}).items():
        plan = _matrix_plan(frame)
        if plan is None:
            continue
        structural.append((name, frame, plan))
        metric = _metric_hint(name, frame)
        if metric:
            candidates[metric].append((name, frame, plan))

    if len(candidates["tl"]) != 1 or len(candidates["unit"]) != 1:
        from app.services.kpi_workbook_compat import _find_matrix
        tl_name, tl_frame = _find_matrix(workbook or {}, "tl")
        unit_name, unit_frame = _find_matrix(workbook or {}, "unit")
        if tl_name or unit_name:
            if not tl_name or not unit_name:
                raise ValueError("Adaptive IMS: eşlenik TL/KUTU matrisi birlikte bulunmalıdır.")
            tl_plan = _matrix_plan(tl_frame)
            unit_plan = _matrix_plan(unit_frame)
            if tl_plan is None or unit_plan is None:
                def hint(name, frame):
                    header_hints = []
                    for row_index in range(min(5, len(frame))):
                        labels = [_norm(value) for value in frame.iloc[row_index].tolist() if _norm(value)]
                        if labels:
                            header_hints.append(f"r{row_index + 1}=" + "/".join(labels[:8]))
                    return f"{name}[{'; '.join(header_hints)}]"
                raise ValueError(
                    "Adaptive IMS: kabul edilen TL/KUTU matrisi semantik olarak çözümlenemedi. "
                    f"TL={hint(tl_name, tl_frame)}; KUTU={hint(unit_name, unit_frame)}"
                )
            candidates = {
                "tl": [(tl_name, tl_frame, tl_plan)],
                "unit": [(unit_name, unit_frame, unit_plan)],
            }
        elif structural:
            # Structural TTS-like sheets without a unique TL/KUTU semantic hint
            # are outside this adapter's authority. Do not guess or fail the
            # whole import: leave them to the legacy/dynamic import contract.
            return None
        else:
            return None

    if len(candidates["tl"]) != 1 or len(candidates["unit"]) != 1:
        raise ValueError(
            "Adaptive IMS: TL/KUTU TTS matrisi tekil belirlenemedi; "
            f"TL={len(candidates['tl'])}, KUTU={len(candidates['unit'])}."
        )
    tl = candidates["tl"][0]
    unit = candidates["unit"][0]
    if set(tl[2]["products"]) != set(unit[2]["products"]):
        raise ValueError("Adaptive IMS: TL/KUTU matrislerinin ürün kapsamı aynı değil.")
    return tl, unit


def _source_rows(frame, plan):
    """Read official aggregates and detail rows without counting V2 summaries twice.

    Legacy sheets use NATIONAL and region Subtotal rows. Week-41 V2 sheets
    use TÜRKİYE TOPLAM, a region row with an empty TTS cell, and one summary
    row per TTS where brick and TTS labels are identical and province is empty.
    TTS summaries are context only; representative totals come from detail rows.
    """
    products = sorted(plan["products"])
    aggregates = []
    reps = {}
    v2_summaries = []
    v2_layout_seen = False
    for source_index in range(plan["data_start"], len(frame)):
        row = frame.iloc[source_index]

        def cell(column):
            value = row.iloc[column]
            return "" if pd.isna(value) else str(value).strip()

        territory = cell(plan["region"])
        province = cell(plan["province"])
        representative = cell(plan["primary_rep"])
        brick = cell(plan["brick"])
        territory_norm = _norm(territory)
        province_norm = _norm(province)
        rep_norm = _norm(representative)
        brick_norm = _norm(brick)
        if not any((territory_norm, province_norm, rep_norm, brick_norm)):
            continue

        values = {
            product: {
                "target": float(pd.to_numeric(pd.Series([row.iloc[plan["products"][product] - 1]]), errors="coerce").fillna(0).iloc[0]),
                "actual": float(pd.to_numeric(pd.Series([row.iloc[plan["products"][product]]]), errors="coerce").fillna(0).iloc[0]),
            }
            for product in products
        }

        # National identity moved from legacy C/D columns to the V2 region label.
        if any(label in {"NATIONAL", "TURKIYE TOPLAM"} for label in (
            territory_norm, province_norm, rep_norm, brick_norm
        )):
            aggregates.append(("NATIONAL", "NATIONAL", values))
            continue

        # Legacy region totals use a named Subtotal province and repeat the
        # region in the representative column. V2 region totals have blank
        # province/TTS cells and repeat the region in the brick column.
        legacy_subtotal = bool(
            territory_norm
            and province_norm.endswith(" SUBTOTAL")
            and rep_norm == territory_norm
            and re.match(r"^\d{3}\b", territory_norm)
        )
        v2_region_total = bool(
            territory_norm
            and not province_norm
            and brick_norm == territory_norm
            and not rep_norm
            and re.match(r"^\d{3}\b", territory_norm)
        )
        if legacy_subtotal or v2_region_total:
            v2_layout_seen = v2_layout_seen or v2_region_total
            aggregates.append((territory_norm.split()[0], territory, values))
            continue

        # V2 repeats each TTS total before its brick rows. Skip that summary
        # to prevent adding the same target/actual twice to the representative.
        v2_tts_summary = bool(
            territory_norm and not province_norm and brick_norm and brick_norm == rep_norm
        )
        if v2_tts_summary:
            v2_layout_seen = True
            v2_summaries.append((territory, representative, values, source_index + 1))
            continue

        if representative and rep_norm not in {"NATIONAL", territory_norm, "TURKIYE TOPLAM"}:
            key = (territory, representative)
            bucket = reps.setdefault(key, {product: {"target": 0.0, "actual": 0.0} for product in products})
            for product in products:
                bucket[product]["target"] += values[product]["target"]
                bucket[product]["actual"] += values[product]["actual"]
    if v2_layout_seen:
        # Each V2 summary must reconcile to its own detailed brick rows. This
        # proves the workbook was read completely and prevents silent undercounts.
        for territory, representative, summary_values, source_row in v2_summaries:
            detail_values = reps.get((territory, representative))
            if detail_values is None:
                raise ValueError(
                    f"Adaptive IMS: V2 TTS özeti için brick satırı bulunamadı "
                    f"(satır={source_row}, bölge={territory}, TTS={representative})."
                )
            for product in products:
                for metric in ("target", "actual"):
                    expected = float(summary_values[product][metric] or 0)
                    actual = float(detail_values[product][metric] or 0)
                    if abs(expected - actual) > max(0.01, abs(expected) * 1e-6):
                        raise ValueError(
                            "Adaptive IMS: V2 TTS özeti brick detaylarıyla uyuşmuyor "
                            f"(satır={source_row}, bölge={territory}, TTS={representative}, "
                            f"ürün={product}, metrik={metric}, özet={expected}, detay={actual})."
                        )

        # V2 explicitly supplies national and region aggregates. Check product
        # target/actual columns against the sum of the region totals.
        national_rows = [values for territory, _representative, values in aggregates if territory == "NATIONAL"]
        region_rows = [values for territory, _representative, values in aggregates if territory != "NATIONAL"]
        if len(national_rows) != 1:
            raise ValueError(
                f"Adaptive IMS: V2 matriste tek Türkiye toplamı bekleniyordu; bulundu={len(national_rows)}."
            )
        region_keys = [territory for territory, _representative, _values in aggregates if territory != "NATIONAL"]
        if len(region_keys) != len(set(region_keys)):
            raise ValueError("Adaptive IMS: V2 matriste yinelenen bölge toplamı bulundu.")
        for product in products:
            for metric in ("target", "actual"):
                expected = float(national_rows[0][product][metric] or 0)
                actual = sum(float(values[product][metric] or 0) for values in region_rows)
                if abs(expected - actual) > max(0.01, abs(expected) * 1e-6):
                    raise ValueError(
                        "Adaptive IMS: V2 Türkiye toplamı bölge toplamlarıyla uyuşmuyor "
                        f"(ürün={product}, metrik={metric}, Türkiye={expected}, bölgeler={actual})."
                    )
    return products, aggregates, reps

def _pair_views(importer):
    pair = _find_pair(importer.workbook or {})
    if pair is None:
        return None
    (tl_name, _tl_frame, _tl_plan), (unit_name, _unit_frame, _unit_plan) = pair
    raw = pd.read_excel(importer.file_path, sheet_name=[tl_name, unit_name], header=None)
    tl_frame, unit_frame = raw[tl_name], raw[unit_name]
    tl_plan, unit_plan = _matrix_plan(tl_frame), _matrix_plan(unit_frame)
    if tl_plan is None or unit_plan is None:
        raise ValueError("Adaptive IMS: ham TL/KUTU matris başlıkları çözümlenemedi.")
    tl_products, tl_aggregates, tl_reps = _source_rows(tl_frame, tl_plan)
    unit_products, unit_aggregates, unit_reps = _source_rows(unit_frame, unit_plan)
    if tl_products != unit_products:
        raise ValueError("Adaptive IMS: ham TL/KUTU ürün kapsamı aynı değil.")
    if set(tl_reps) != set(unit_reps):
        raise ValueError("Adaptive IMS: TL/KUTU temsilci kapsamı aynı değil.")
    tl_agg = {(territory, representative): values for territory, representative, values in tl_aggregates}
    unit_agg = {(territory, representative): values for territory, representative, values in unit_aggregates}
    if set(tl_agg) != set(unit_agg):
        raise ValueError("Adaptive IMS: TL/KUTU NATIONAL/bölge kapsamı aynı değil.")
    return {
        "tl_name": tl_name,
        "unit_name": unit_name,
        "products": tl_products,
        "tl_reps": tl_reps,
        "unit_reps": unit_reps,
        "tl_aggregates": tl_agg,
        "unit_aggregates": unit_agg,
    }


def install_adaptive_kpi_target_authority():
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_adaptive_kpi_target_authority_installed", False):
        return

    original_balance = IMSImportService.apply_balance_summary
    original_dashboard = IMSImportService.persist_national_dashboard_metrics

    def apply_adaptive_targets(self, year, month):
        original_balance(self, year, month)
        views = _pair_views(self)
        if views is None:
            return
        targets = {(row.representative_id, row.product_id): row for row in Target.query.filter_by(year=year, month=month).all()}
        summaries = {(row.representative_id, row.product_id): row for row in IMSSummary.query.filter_by(year=year, month=month).all()}
        product_map = {}
        for product_name in views["products"]:
            match = self.resolve_product_match(product_name)
            if not match.get("matched"):
                raise ValueError(f"Adaptive IMS: ürün eşleşmedi: {product_name}")
            product_map[product_name] = int(match["object"].id)

        written = 0
        for (territory, representative_name), tl_values in views["tl_reps"].items():
            unit_values = views["unit_reps"][(territory, representative_name)]
            if self._is_vacancy_representative(representative_name):
                rep_id = self._ensure_vacancy_representative(territory, vacancy_name=representative_name)
            else:
                match = self.resolve_representative_match(representative_name)
                if not match.get("matched"):
                    raise ValueError(f"Adaptive IMS: temsilci eşleşmedi: {representative_name}")
                rep_id = int(match["object"].id)
            for product_name, product_id in product_map.items():
                key = (rep_id, product_id)
                target = targets.get(key)
                if target is None:
                    target = Target(
                        year=year, month=month, quarter=self.quarter_for(month),
                        representative_id=rep_id, product_id=product_id,
                    )
                    db.session.add(target)
                    targets[key] = target
                target.tl_target = float(tl_values[product_name]["target"] or 0)
                target.unit_target = float(unit_values[product_name]["target"] or 0)
                summary = summaries.get(key)
                if summary is not None:
                    summary.target_tl = target.tl_target
                    summary.target_unit = target.unit_target
                    summary.realization_percent = (
                        round(float(summary.tl or 0) * 100 / target.tl_target, 2)
                        if target.tl_target else 0.0
                    )
                written += 1
        self.statistics["adaptive_direct_target_records"] = written
        db.session.flush()

    def persist_adaptive_aggregates(self, year, month):
        # Critical ordering: the generic dashboard path builds/reconciles a
        # synthetic compatibility summary.  For paired KPI workbooks that
        # synthetic layer can disagree with the workbook's own NATIONAL/region
        # KUTU rows and fail before this adapter gets a chance to replace them.
        # Detect the accepted pair first.  Legacy/non-paired workbooks continue
        # through the original path unchanged.
        views = _pair_views(self)
        if views is None:
            return original_dashboard(self, year, month)

        from app.services import official_aggregate_service as official
        product_map = {}
        for product_name in views["products"]:
            match = self.resolve_product_match(product_name)
            if not match.get("matched"):
                raise ValueError(f"Adaptive IMS: aggregate ürün eşleşmedi: {product_name}")
            product_map[product_name] = int(match["object"].id)

        target_written = actual_written = 0
        for identity, tl_values in views["tl_aggregates"].items():
            territory, representative = identity
            unit_values = views["unit_aggregates"][identity]
            for product_name, product_id in product_map.items():
                official._upsert(
                    self, year, month, views["tl_name"], official.TARGET_TYPE,
                    territory, representative, product_id,
                    unit_values[product_name]["target"], tl_values[product_name]["target"],
                    {"source": "adaptive paired IMS matrix", "metric": "target"},
                )
                official._upsert(
                    self, year, month, views["tl_name"], official.ACTUAL_TYPE,
                    territory, representative, product_id,
                    unit_values[product_name]["actual"], tl_values[product_name]["actual"],
                    {"source": "adaptive paired IMS matrix", "metric": "actual"},
                )
                target_written += 1
                actual_written += 1
        self.statistics["adaptive_official_target_records"] = target_written
        self.statistics["adaptive_official_actual_records"] = actual_written
        db.session.flush()
        # Reconcile only after the workbook-authoritative TL and KUTU values are
        # both persisted.  This keeps the same fail-closed safety gate without
        # letting the synthetic compatibility aggregate pre-empt the adapter.
        official.reconcile_national_regions(self)

    IMSImportService.apply_balance_summary = apply_adaptive_targets
    IMSImportService.persist_national_dashboard_metrics = persist_adaptive_aggregates
    IMSImportService._adaptive_kpi_target_authority_installed = True
