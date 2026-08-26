"""Content-driven, coordinate-independent workbook reconciliation.

Business identity is derived from dimensions, product/market, metric family,
phase and period scope. Sheet names and physical coordinates are audit metadata
only. Independent pivots remain explicit masters; once a strong relationship is
discovered, conflicting or missing derived metrics fail closed.
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
    MONTH_TOKENS = {
        "OCAK", "SUBAT", "ŞUBAT", "MART", "NISAN", "NİSAN", "MAYIS",
        "HAZIRAN", "HAZİRAN", "TEMMUZ", "AGUSTOS", "AĞUSTOS", "EYLUL",
        "EYLÜL", "EKIM", "EKİM", "KASIM", "ARALIK", "JAN", "JANUARY",
        "FEB", "FEBRUARY", "MAR", "MARCH", "APR", "APRIL", "JUN", "JUNE",
        "JUL", "JULY", "AUG", "AUGUST", "SEP", "SEPTEMBER", "OCT",
        "OCTOBER", "NOV", "NOVEMBER", "DEC", "DECEMBER",
    }
    DERIVED_HINT_TYPES = {"master_pivot_derived", "brick_realization"}
    MONTHLY_HINT_TYPES = {"competition_tl", "competition_box", "competition_pp"}
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
        if not text or cls._norm(text) in {"NAN", "NONE", "-"} or not re.search(r"\d", text):
            return None
        text = re.sub(r"[^0-9,.-]", "", text)
        if text.count(",") and text.count("."):
            text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
        elif text.count(","):
            text = text.replace(".", "").replace(",", ".")
        try:
            number = float(text)
            return number if math.isfinite(number) else None
        except ValueError:
            return None

    def _header_row(self, sheet_name, frame):
        item = self._manifest_by_name.get(str(sheet_name), {})
        if item.get("header_row") is not None:
            return int(item["header_row"])
        best, best_score = 0, -1
        for row in range(min(40, len(frame))):
            text = " | ".join(self._norm(v) for v in frame.iloc[row].tolist() if self._meaningful(v))
            score = sum(2 for token in self.DIMENSION_TOKENS if token in text)
            score += 2 if any(token in text for token in ("VALUES REPORT", "UNITS REPORT", "TL", "KUTU", "HEDEF", "CIKIS", "ÇIKIŞ", "REAL")) else 0
            if score > best_score:
                best, best_score = row, score
        return best if best_score >= 2 else min(5, max(0, len(frame) - 1))

    def _header_matrix(self, frame, header_row):
        matrix = []
        for row in range(header_row + 1):
            raw = [self._norm(v) if self._meaningful(v) else "" for v in frame.iloc[row].tolist()]
            carried, active = [], ""
            for value in raw:
                if value:
                    active = value
                carried.append(value or active)
            matrix.append((raw, carried))
        return matrix

    @staticmethod
    def _column_context(matrix, column):
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
        candidates = []
        for col in range(min(4, frame.shape[1])):
            text_count = total = 0
            for row in range(header_row + 1, min(len(frame), header_row + 80)):
                value = frame.iloc[row, col]
                if not self._meaningful(value):
                    continue
                total += 1
                text_count += self._number(value) is None
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

    @staticmethod
    def _metric_family(raw_parts, carried_parts):
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

    @staticmethod
    def _phase(raw_parts, carried_parts):
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

    def _period_scope(self, raw_parts, carried_parts, sheet_type):
        def explicit_scope(parts):
            # Read the nearest/local header first. Horizontally carried pivot
            # labels can contain both a parent WEEK label and a later MONTH
            # sub-group; merging all text would incorrectly collapse those
            # two physical measures into one semantic key.
            for part in reversed(parts):
                normalized = self._norm(part)
                if normalized in {"HAFTA", "WEEK", "WEEKLY"}:
                    return "weekly"
                if normalized in {"AY", "MONTH", "MONTHLY"} or normalized in self.MONTH_TOKENS:
                    return "monthly"
            return None

        local_scope = explicit_scope(raw_parts)
        if local_scope:
            return local_scope
        carried_scope = explicit_scope(carried_parts)
        if carried_scope:
            return carried_scope
        if sheet_type in self.MONTHLY_HINT_TYPES or str(sheet_type).startswith("monthly_master"):
            return "monthly"
        return "unspecified"

    def _is_metadata_part(self, part):
        if not part:
            return True
        if part.startswith("PIVOTTABLE") or part.startswith("GROUPTABLE"):
            return True
        if "=" in part and any(token in part for token in ("MONTH", "WEEK", "AY", "HAFTA")):
            return True
        tokens = set(re.findall(r"[A-Z0-9ÇĞİÖŞÜ]+", part))
        generic = {
            "REPORT", "VALUES", "VALUE", "UNITS", "UNIT", "TL", "KUTU", "BOX", "ADET",
            "CIRO", "TUTAR", "MONTH", "MONTHS", "WEEK", "WEEKS", "HAFTA", "AY",
            "PRODUCTS", "MARKETPRODUCTS", "MKT", "NONE", "CIKIS", "ÇIKIŞ", "HEDEF",
            "TARGET", "REAL", "REALIZASYON", "REALİZASYON", "PAY", "SHARE", "PP", "METRIK", "METRİK",
        }
        return not tokens or tokens <= generic or tokens <= self.MONTH_TOKENS

    def _product_key(self, raw_parts, carried_parts):
        all_parts = raw_parts + [part for part in carried_parts if part not in raw_parts]
        joined = " ".join(all_parts)
        if "GRAND TOTAL" in joined or "GENEL TOPLAM" in joined:
            return "__TOTAL__"
        subtotal = [p for p in all_parts if "SUBTOTAL" in p or "ARA TOPLAM" in p]
        if subtotal:
            return re.sub(r"\b(SUBTOTAL|ARA TOPLAM|TOPLAM|TOTAL)\b", "", subtotal[-1]).strip() or "__TOTAL__"
        for part in reversed(raw_parts):
            if self._is_metadata_part(part) or any(dim in part for dim in self.DIMENSION_TOKENS):
                continue
            cleaned = re.sub(r"\b(VALUES?|UNITS?|REPORT|TL|KUTU|BOX|ADET)\b", " ", part)
            cleaned = " ".join(cleaned.split()).strip()
            if cleaned and not self._is_metadata_part(cleaned):
                return cleaned
        for part in reversed(carried_parts):
            if self._is_metadata_part(part) or any(dim in part for dim in self.DIMENSION_TOKENS):
                continue
            cleaned = re.sub(r"\b(VALUES?|UNITS?|REPORT|TL|KUTU|BOX|ADET)\b", " ", part)
            cleaned = " ".join(cleaned.split()).strip()
            if cleaned and not self._is_metadata_part(cleaned):
                return cleaned
        return "__TOTAL__"

    def _is_pivot_candidate(self, frame, sheet_type):
        if sheet_type in self.DERIVED_HINT_TYPES or str(sheet_type).startswith("monthly_master"):
            return True
        sample = " ".join(
            self._norm(v) for row in range(min(8, len(frame))) for v in frame.iloc[row].tolist() if self._meaningful(v)
        )
        return any(token in sample for token in ("PIVOTTABLE", "GROUPTABLE", "REALIZASYON", "REALİZASYON"))

    def _observations(self):
        observations, profiles = [], {}
        for sheet_name, frame in self.workbook.items():
            item = self._manifest_by_name.get(str(sheet_name), {})
            if item.get("coverage") in {"unclassified", "explicit_nondata"}:
                continue
            sheet_type = item.get("sheet_type")
            header_row = self._header_row(sheet_name, frame)
            matrix = self._header_matrix(frame, header_row)
            dims = self._dimension_columns(frame, header_row, matrix)
            pivot_candidate = self._is_pivot_candidate(frame, sheet_type)
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
                    obs = {
                        "sheet_name": str(sheet_name), "row": row + 1, "column": col + 1,
                        "value": value, "row_key": row_key, "metric_family": family,
                        "phase": self._phase(raw_parts, carried_parts),
                        "period_scope": self._period_scope(raw_parts, carried_parts, sheet_type),
                        "product_key": self._product_key(raw_parts, carried_parts),
                        "pivot_candidate": pivot_candidate,
                    }
                    obs["semantic_key"] = (obs["row_key"], obs["metric_family"], obs["phase"], obs["period_scope"], obs["product_key"])
                    observations.append(obs)
        return observations, profiles

    @classmethod
    def _equal(cls, left, right):
        return abs(float(left) - float(right)) <= cls.TOLERANCE

    @staticmethod
    def _relation_key(key):
        row_key, family, phase, _period, product = key
        return row_key, family, phase, product

    @staticmethod
    def _relation_index(mapping):
        index = defaultdict(list)
        for key, obs in mapping.items():
            index[WorkbookSemanticReconciler._relation_key(key)].append((key, obs))
        return index

    def reconcile(self):
        observations, profiles = self._observations()
        by_sheet_key = defaultdict(dict)
        duplicate_conflicts = []
        for obs in observations:
            key = obs["semantic_key"]
            sheet_name = obs["sheet_name"]
            previous = by_sheet_key[sheet_name].get(key)
            if previous is None:
                by_sheet_key[sheet_name][key] = dict(obs)
                continue
            if profiles.get(sheet_name, {}).get("pivot_candidate"):
                if not self._equal(previous["value"], obs["value"]):
                    duplicate_conflicts.append({"first": previous, "second": obs})
                continue
            # Repeated raw/fact rows are legitimate source granularity. Collapse
            # them deterministically for cross-sheet reconciliation instead of
            # treating them as duplicate-master conflicts.
            previous["value"] = float(previous["value"]) + float(obs["value"])
            previous.setdefault("source_cells", [(previous["row"], previous["column"])])
            previous["source_cells"].append((obs["row"], obs["column"]))

        relations = []
        sheets = list(by_sheet_key)
        for index, left_name in enumerate(sheets):
            left_rel = self._relation_index(by_sheet_key[left_name])
            for right_name in sheets[index + 1:]:
                right_rel = self._relation_index(by_sheet_key[right_name])
                pairs = []
                for rel_key in set(left_rel) & set(right_rel):
                    for lkey, lobs in left_rel[rel_key]:
                        for rkey, robs in right_rel[rel_key]:
                            if lkey[3] != rkey[3] and "unspecified" not in {lkey[3], rkey[3]}:
                                continue
                            pairs.append((lkey, rkey, lobs, robs))
                if len(pairs) < self.MIN_RELATION_MATCHES:
                    continue
                matched = [(lk, rk, lo, ro) for lk, rk, lo, ro in pairs if self._equal(lo["value"], ro["value"])]
                match_ratio = len(matched) / len(pairs)
                coverage = len({self._relation_key(lk) for lk, *_ in pairs}) / max(1, min(len(left_rel), len(right_rel)))
                if match_ratio >= self.RELATION_MATCH_RATIO and coverage >= self.RELATION_COVERAGE_RATIO:
                    relations.append({"left": left_name, "right": right_name, "pairs": pairs, "matched": matched, "match_ratio": match_ratio, "coverage": coverage})

        evidence, conflicts = {}, []
        for relation in relations:
            matched_pairs = {(lk, rk) for lk, rk, *_ in relation["matched"]}
            for lkey, rkey, lobs, robs in relation["pairs"]:
                if (lkey, rkey) in matched_pairs:
                    evidence[(lobs["sheet_name"], lobs["row"], lobs["column"])] = {
                        "matched": True, "semantic_key": repr(lkey), "source_sheet": robs["sheet_name"],
                        "source_row": robs["row"], "source_column": robs["column"], "source_value": robs["value"], "derived_value": lobs["value"],
                    }
                    evidence[(robs["sheet_name"], robs["row"], robs["column"])] = {
                        "matched": True, "semantic_key": repr(rkey), "source_sheet": lobs["sheet_name"],
                        "source_row": lobs["row"], "source_column": lobs["column"], "source_value": lobs["value"], "derived_value": robs["value"],
                    }
                else:
                    conflicts.append({"type": "VALUE_CONFLICT", "left": lobs, "right": robs})

            left_name, right_name = relation["left"], relation["right"]
            left_rel, right_rel = self._relation_index(by_sheet_key[left_name]), self._relation_index(by_sheet_key[right_name])
            left_set, right_set = set(left_rel), set(right_rel)
            if len(left_set) <= len(right_set):
                smaller_name, missing, source_index = left_name, right_set - left_set, right_rel
            else:
                smaller_name, missing, source_index = right_name, left_set - right_set, left_rel
            allowed_missing = max(1, int(max(len(left_set), len(right_set)) * (1.0 - self.RELATION_COVERAGE_RATIO)))
            if profiles.get(smaller_name, {}).get("pivot_candidate") and 0 < len(missing) <= allowed_missing:
                for rel_key in sorted(missing, key=repr):
                    conflicts.append({"type": "MISSING_DERIVED_CELL", "sheet_name": smaller_name, "semantic_key": repr(rel_key), "source": source_index[rel_key][0][1]})

        ledger = getattr(self.importer, "workbook_cell_ledger", []) or []
        obs_by_coord = {(o["sheet_name"], o["row"], o["column"]): o for o in observations}
        verified = imported_master = explicit_nondata = 0
        for cell in ledger:
            coord = (cell["sheet_name"], cell["row"], cell["column"])
            obs = obs_by_coord.get(coord)
            profile = profiles.get(cell["sheet_name"], {})
            if obs is None:
                if profile.get("pivot_candidate"):
                    # Header/metadata are non-data, but row dimensions inside a
                    # pivot are themselves master identity and must be audited.
                    if cell["row"] > int(profile.get("header_row", 0)) + 1:
                        cell["classification"] = "IMPORTED_MASTER"
                    else:
                        cell["classification"] = "EXPLICIT_NONDATA"
                        explicit_nondata += 1
                elif cell.get("classification") == "VERIFIED_DERIVED":
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
            {"left": r["left"], "right": r["right"], "match_ratio": r["match_ratio"], "coverage": r["coverage"]} for r in relations
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
            raise ValueError(f"Workbook semantic reconciliation başarısız; {len(problems)} conflict/missing cell: {problems[:5]}")
        return {"relationships": self.importer.semantic_relationships, "verified_derived_cells": verified, "independent_master_cells": imported_master, "conflicts": 0}
