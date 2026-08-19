"""Content-driven, coordinate-independent workbook reconciliation.

The engine never uses a sheet name, row number or column number as business
identity.  Physical coordinates are retained only for audit evidence.  Metric
identity is derived from row dimensions + product/market + metric family +
phase + period scope.  Pivot-like sheets with no upstream equivalent remain
explicit master sources; once a strong cross-sheet relationship is discovered,
missing or conflicting cells become blocking errors.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

from app.services.alias_service import AliasService


class WorkbookSemanticReconciler:
    DIMENSION_TOKENS = {
        "TERRITORIES", "TERRITORY", "SUBTERRITORIES", "SUBTERRITORY",
        "BOLGE", "REGION", "IAM BRICK", "BRICK", "TEMSILCI", "TTS ISMI",
        "REPRESENTATIVE", "1 TTS ISMI", "2 TTS ISMI",
    }
    GENERIC_TOKENS = {
        "PIVOTTABLE", "GROUPTABLE", "LIDS", "REPORT", "VALUES", "VALUE",
        "UNITS", "UNIT", "TL", "KUTU", "BOX", "ADET", "CIRO", "TUTAR",
        "MONTH", "MONTHS", "WEEK", "WEEKS", "HAFTA", "AY", "PRODUCTS",
        "MARKETPRODUCTS", "MKT", "NONE", "CIKIS", "ÇIKIŞ", "HEDEF", "TARGET",
        "REAL", "REALIZASYON", "REALİZASYON", "PAY", "SHARE", "PP",
    }
    MONTH_TOKENS = {
        "OCAK", "SUBAT", "ŞUBAT", "MART", "NISAN", "NİSAN", "MAYIS",
        "HAZIRAN", "HAZİRAN", "TEMMUZ", "AGUSTOS", "AĞUSTOS", "EYLUL",
        "EYLÜL", "EKIM", "EKİM", "KASIM", "ARALIK", "JAN", "JANUARY",
        "FEB", "FEBRUARY", "MAR", "MARCH", "APR", "APRIL", "MAY", "JUN",
        "JUNE", "JUL", "JULY", "AUG", "AUGUST", "SEP", "SEPTEMBER", "OCT",
        "OCTOBER", "NOV", "NOVEMBER", "DEC", "DECEMBER",
    }
    DERIVED_HINT_TYPES = {"master_pivot_derived", "brick_realization"}
    MIN_RELATION_MATCHES = 5
    RELATION_MATCH_RATIO = 0.90
    RELATION_COVERAGE_RATIO = 0.80
    TOLERANCE = 0.01

    def __init__(self, importer):
        self.importer = importer
        self.workbook = importer.workbook or {}
        self.manifest = getattr(importer, "workbook_manifest", []) or []
        self._manifest_by_name = {item["sheet_name"]: item for item in self.manifest}

    @staticmethod
    def _norm(value):
        return AliasService.normalize(value)

    @staticmethod
    def _meaningful(value):
        if value is None:
            return False
        try:
            if value != value:
                return False
        except Exception:
            pass
        return not (isinstance(value, str) and not value.strip())

    @classmethod
    def _number(cls, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = float(value)
            return number if math.isfinite(number) else None
        text = str(value).strip().replace("\u00a0", "")
        if not text or cls._norm(text) in {"NAN", "NONE", "-"}:
            return None
        if not re.search(r"\d", text):
            return None
        text = re.sub(r"[^0-9,.-]", "", text)
        if text.count(",") and text.count("."):
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif text.count(","):
            text = text.replace(".", "").replace(",", ".")
        try:
            number = float(text)
            return number if math.isfinite(number) else None
        except ValueError:
            return None

    def _header_row(self, sheet_name, frame):
        manifest = self._manifest_by_name.get(str(sheet_name), {})
        header = manifest.get("header_row")
        if header is not None:
            return int(header)
        best = None
        best_score = -1
        for row in range(min(40, len(frame))):
            values = [self._norm(v) for v in frame.iloc[row].tolist() if self._meaningful(v)]
            joined = " | ".join(values)
            score = sum(2 for token in self.DIMENSION_TOKENS if token in joined)
            if any(token in joined for token in ("VALUES REPORT", "UNITS REPORT", "TL", "KUTU", "HEDEF", "CIKIS", "ÇIKIŞ", "REAL")):
                score += 2
            if score > best_score:
                best, best_score = row, score
        return best if best_score >= 2 else min(5, max(0, len(frame) - 1))

    def _header_matrix(self, frame, header_row):
        matrix = []
        for row in range(header_row + 1):
            raw = [self._norm(v) if self._meaningful(v) else "" for v in frame.iloc[row].tolist()]
            # Excel merged section headings are commonly stored only in the
            # first cell.  Carry them rightward for semantic context only.
            carried = []
            active = ""
            for value in raw:
                if value:
                    active = value
                carried.append(value or active)
            matrix.append((raw, carried))
        return matrix

    def _column_context(self, matrix, column):
        raw_parts, carried_parts = [], []
        for raw, carried in matrix:
            if column < len(raw) and raw[column] and raw[column] not in raw_parts:
                raw_parts.append(raw[column])
            if column < len(carried) and carried[column] and carried[column] not in carried_parts:
                carried_parts.append(carried[column])
        return raw_parts, carried_parts

    def _dimension_columns(self, frame, header_row, matrix):
        columns = []
        for col in range(frame.shape[1]):
            raw, carried = self._column_context(matrix, col)
            text = " ".join(raw + carried)
            if any(token in text for token in self.DIMENSION_TOKENS):
                columns.append(col)
        if columns:
            return sorted(set(columns))[:4]
        # Fallback for unnamed pivots: leading columns whose data is mostly text.
        candidates = []
        for col in range(min(4, frame.shape[1])):
            text_count = 0
            total = 0
            for row in range(header_row + 1, min(len(frame), header_row + 80)):
                value = frame.iloc[row, col]
                if not self._meaningful(value):
                    continue
                total += 1
                if self._number(value) is None:
                    text_count += 1
            if total and text_count / total >= 0.70:
                candidates.append(col)
        return candidates or [0]

    def _row_key(self, frame, row, dimension_columns):
        parts = []
        for col in dimension_columns:
            if col >= frame.shape[1]:
                continue
            value = self._norm(frame.iloc[row, col])
            if value and value not in {"NAN", "NONE"}:
                parts.append(value)
        return tuple(parts)

    def _metric_family(self, raw_parts, carried_parts):
        text = " ".join(raw_parts + carried_parts)
        if any(token in text for token in ("REAL%", "REALIZASYON", "REALİZASYON")):
            return "ratio"
        if any(token in text for token in ("PP", "PAZAR PAY", "MARKET SHARE", "VALUE SHARE")):
            return "share"
        if any(token in text for token in ("KUTU", "UNITS REPORT", "UNIT REPORT", "BOX", "ADET")):
            return "unit"
        if any(token in text for token in ("TL", "VALUES REPORT", "VALUE REPORT", "CIRO", "TUTAR")):
            return "tl"
        return None

    def _phase(self, raw_parts, carried_parts):
        text = " ".join(raw_parts + carried_parts)
        if "HEDEF" in text or "TARGET" in text:
            return "target"
        if "BAKIYE" in text or "BAKİYE" in text:
            return "balance"
        if "REAL%" in text or "REALIZASYON" in text or "REALİZASYON" in text:
            return "realization"
        if "CIKIS" in text or "ÇIKIŞ" in text or "ACTUAL" in text:
            return "actual"
        return "market"

    def _period_scope(self, raw_parts, carried_parts):
        text = " ".join(raw_parts + carried_parts)
        if "HAFTA" in text or "WEEK" in text:
            return "weekly"
        if "MONTH" in text or re.search(r"\bAY\b", text) or any(token in text for token in self.MONTH_TOKENS):
            return "monthly"
        return "unspecified"

    def _product_key(self, raw_parts, carried_parts):
        all_parts = raw_parts + [part for part in carried_parts if part not in raw_parts]
        joined = " ".join(all_parts)
        if "GRAND TOTAL" in joined or "GENEL TOPLAM" in joined:
            return "__TOTAL__"
        subtotal_parts = [part for part in all_parts if "SUBTOTAL" in part or "ARA TOPLAM" in part]
        if subtotal_parts:
            candidate = subtotal_parts[-1]
            return re.sub(r"\b(SUBTOTAL|ARA TOPLAM|TOPLAM|TOTAL)\b", "", candidate).strip() or "__TOTAL__"
        candidates = []
        for part in all_parts:
            tokens = set(re.findall(r"[A-Z0-9ÇĞİÖŞÜ]+", part))
            if not tokens:
                continue
            if any(dim in part for dim in self.DIMENSION_TOKENS):
                continue
            if tokens <= self.GENERIC_TOKENS or tokens <= self.MONTH_TOKENS:
                continue
            cleaned = part
            for generic in self.GENERIC_TOKENS | self.MONTH_TOKENS:
                cleaned = re.sub(rf"\b{re.escape(generic)}\b", " ", cleaned)
            cleaned = re.sub(r"\b20\d{2}\b|\b\d{1,2}[./-]\d{1,2}\b", " ", cleaned)
            cleaned = " ".join(cleaned.split()).strip()
            if cleaned:
                candidates.append(cleaned)
        if not candidates:
            return "__TOTAL__"
        # The lowest/last header level is normally the most specific product.
        return candidates[-1]

    def _is_pivot_candidate(self, sheet_name, frame, sheet_type):
        if sheet_type in self.DERIVED_HINT_TYPES or str(sheet_type).startswith("monthly_master"):
            return True
        sample = " ".join(
            self._norm(v)
            for row in range(min(8, len(frame)))
            for v in frame.iloc[row].tolist()
            if self._meaningful(v)
        )
        return "PIVOTTABLE" in sample or "GROUPTABLE" in sample or "REALIZASYON" in sample or "REALİZASYON" in sample

    def _observations(self):
        observations = []
        profiles = {}
        for sheet_name, frame in self.workbook.items():
            item = self._manifest_by_name.get(str(sheet_name), {})
            if item.get("coverage") in {"unclassified", "explicit_nondata"}:
                continue
            header_row = self._header_row(sheet_name, frame)
            matrix = self._header_matrix(frame, header_row)
            dims = self._dimension_columns(frame, header_row, matrix)
            pivot_candidate = self._is_pivot_candidate(sheet_name, frame, item.get("sheet_type"))
            profiles[str(sheet_name)] = {"pivot_candidate": pivot_candidate, "header_row": header_row, "dimension_columns": dims}
            for row in range(header_row + 1, len(frame)):
                row_key = self._row_key(frame, row, dims)
                if not row_key:
                    continue
                for col in range(frame.shape[1]):
                    if col in dims:
                        continue
                    value = self._number(frame.iloc[row, col])
                    if value is None:
                        continue
                    raw_parts, carried_parts = self._column_context(matrix, col)
                    family = self._metric_family(raw_parts, carried_parts)
                    if family is None:
                        continue
                    observation = {
                        "sheet_name": str(sheet_name),
                        "row": row + 1,
                        "column": col + 1,
                        "value": value,
                        "row_key": row_key,
                        "metric_family": family,
                        "phase": self._phase(raw_parts, carried_parts),
                        "period_scope": self._period_scope(raw_parts, carried_parts),
                        "product_key": self._product_key(raw_parts, carried_parts),
                        "pivot_candidate": pivot_candidate,
                    }
                    observation["semantic_key"] = (
                        observation["row_key"], observation["metric_family"],
                        observation["phase"], observation["period_scope"],
                        observation["product_key"],
                    )
                    observations.append(observation)
        return observations, profiles

    @classmethod
    def _equal(cls, left, right):
        return abs(float(left) - float(right)) <= cls.TOLERANCE

    def reconcile(self):
        observations, profiles = self._observations()
        by_sheet_key = defaultdict(dict)
        duplicate_conflicts = []
        for obs in observations:
            key = obs["semantic_key"]
            previous = by_sheet_key[obs["sheet_name"]].get(key)
            if previous is not None and not self._equal(previous["value"], obs["value"]):
                duplicate_conflicts.append({"first": previous, "second": obs})
            else:
                by_sheet_key[obs["sheet_name"]][key] = obs

        relations = []
        sheets = list(by_sheet_key)
        for index, left_name in enumerate(sheets):
            left = by_sheet_key[left_name]
            for right_name in sheets[index + 1:]:
                right = by_sheet_key[right_name]
                common = set(left) & set(right)
                if len(common) < self.MIN_RELATION_MATCHES:
                    continue
                matched = [key for key in common if self._equal(left[key]["value"], right[key]["value"])]
                match_ratio = len(matched) / len(common)
                coverage = len(common) / max(1, min(len(left), len(right)))
                if match_ratio >= self.RELATION_MATCH_RATIO and coverage >= self.RELATION_COVERAGE_RATIO:
                    relations.append({
                        "left": left_name, "right": right_name,
                        "common": common, "matched": set(matched),
                        "match_ratio": match_ratio, "coverage": coverage,
                    })

        evidence = {}
        conflicts = []
        related_keys = defaultdict(set)
        for relation in relations:
            left_name, right_name = relation["left"], relation["right"]
            left, right = by_sheet_key[left_name], by_sheet_key[right_name]
            for key in relation["common"]:
                lobs, robs = left[key], right[key]
                related_keys[left_name].add(key); related_keys[right_name].add(key)
                if key in relation["matched"]:
                    evidence[(lobs["sheet_name"], lobs["row"], lobs["column"])] = {
                        "matched": True, "semantic_key": repr(key),
                        "source_sheet": robs["sheet_name"], "source_row": robs["row"], "source_column": robs["column"],
                        "source_value": robs["value"], "derived_value": lobs["value"],
                    }
                    evidence[(robs["sheet_name"], robs["row"], robs["column"])] = {
                        "matched": True, "semantic_key": repr(key),
                        "source_sheet": lobs["sheet_name"], "source_row": lobs["row"], "source_column": lobs["column"],
                        "source_value": lobs["value"], "derived_value": robs["value"],
                    }
                else:
                    conflicts.append({"type": "VALUE_CONFLICT", "left": lobs, "right": robs})

            # Once a high-coverage relation exists, a small number of missing
            # semantic cells is evidence of an incomplete pivot rather than a
            # reason to silently reclassify it as a new master.
            smaller_name, larger_name = (left_name, right_name) if len(left) <= len(right) else (right_name, left_name)
            smaller, larger = by_sheet_key[smaller_name], by_sheet_key[larger_name]
            missing = set(larger) - set(smaller)
            allowed_missing = max(1, int(len(larger) * (1.0 - self.RELATION_COVERAGE_RATIO)))
            if profiles.get(smaller_name, {}).get("pivot_candidate") and 0 < len(missing) <= allowed_missing:
                for key in sorted(missing, key=repr):
                    conflicts.append({"type": "MISSING_DERIVED_CELL", "sheet_name": smaller_name, "semantic_key": repr(key), "source": larger[key]})

        ledger = getattr(self.importer, "workbook_cell_ledger", []) or []
        obs_by_coord = {(o["sheet_name"], o["row"], o["column"]): o for o in observations}
        verified = 0
        imported_master = 0
        explicit_nondata = 0
        for cell in ledger:
            coord = (cell["sheet_name"], cell["row"], cell["column"])
            obs = obs_by_coord.get(coord)
            profile = profiles.get(cell["sheet_name"], {})
            if obs is None:
                # Header/label/metadata cells are intentional non-data, not
                # fake derived metrics requiring numeric evidence.
                if profile.get("pivot_candidate") or cell.get("classification") == "VERIFIED_DERIVED":
                    cell["classification"] = "EXPLICIT_NONDATA"
                    explicit_nondata += 1
                continue
            proof = evidence.get(coord)
            if profile.get("pivot_candidate") and proof:
                cell["classification"] = "VERIFIED_DERIVED"
                cell["verification"] = proof
                verified += 1
            elif profile.get("pivot_candidate"):
                cell["classification"] = "IMPORTED_MASTER"
                cell["verification"] = {"matched": False, "reason": "NO_UPSTREAM_EQUIVALENT; retained as independent master", "semantic_key": repr(obs["semantic_key"])}
                imported_master += 1

        self.importer.derived_verification_evidence = evidence
        self.importer.semantic_relationships = [
            {k: v for k, v in relation.items() if k not in {"common", "matched"}}
            for relation in relations
        ]
        self.importer.statistics["verified_derived_cells"] = verified
        self.importer.statistics["independent_master_cells"] = imported_master
        self.importer.statistics["explicit_nondata_cells"] = explicit_nondata
        self.importer.statistics["duplicate_conflict"] = int(self.importer.statistics.get("duplicate_conflict", 0) or 0) + len(duplicate_conflicts)
        self.importer.statistics["conflicting_match"] = int(self.importer.statistics.get("conflicting_match", 0) or 0) + len(conflicts)
        self.importer.statistics["semantic_relationship_count"] = len(relations)
        self.importer.statistics["unclassified_master_cell"] = 0

        problems = duplicate_conflicts + conflicts
        if problems:
            sample = problems[:5]
            raise ValueError(f"Workbook semantic reconciliation başarısız; {len(problems)} conflict/missing cell: {sample}")
        return {
            "relationships": self.importer.semantic_relationships,
            "verified_derived_cells": verified,
            "independent_master_cells": imported_master,
            "conflicts": 0,
        }
