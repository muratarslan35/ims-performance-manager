"""Cached product and representative matching for the IMS ETL pipeline."""

import re
import threading
import unicodedata
from difflib import SequenceMatcher

from app.extensions import db
from app.models import (
    ManualMatchQueue,
    Product,
    ProductAlias,
    ProductMatch,
    Representative,
    RepresentativeAlias,
    RepresentativeMatch,
)


class AliasService:
    """Resolve workbook labels to master-data records with deterministic fallbacks.

    Matching priority (representative and product):
      1. RepresentativeMatch / ProductMatch persistent table (MATCH_TABLE)
      2. rep_code / product_code exact match (CODE)
      3. Exact name match (EXACT)
      4. Alias match (ALIAS)
      5. Contains match (CONTAINS / ALIAS_CONTAINS)
      6. Fuzzy similarity >= 90% (SIMILARITY / ALIAS_SIMILARITY)
      7. -> Add to ManualMatchQueue
    """

    SIMILARITY_LIMIT = 0.90
    _lock = threading.RLock()
    _initialized = False
    _cache_version = 0
    _product_cache = {}
    _product_alias_cache = {}
    _product_match_cache = {}
    _representative_cache = {}
    _representative_alias_cache = {}
    _representative_match_cache = {}
    _statistics = {
        "product": 0,
        "product_alias": 0,
        "representative": 0,
        "representative_alias": 0,
        "cache_hits": 0,
        "cache_miss": 0,
    }

    @classmethod
    def normalize(cls, value):
        if value is None:
            return ""

        text = unicodedata.normalize("NFKD", str(value).strip().upper())
        text = "".join(char for char in text if not unicodedata.combining(char))
        text = text.translate(str.maketrans({"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C"}))
        text = re.sub(r"[^A-Z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def clean_name(cls, value):
        return cls.normalize(value)

    @classmethod
    def similarity(cls, first, second):
        return SequenceMatcher(None, cls.normalize(first), cls.normalize(second)).ratio()

    @classmethod
    def exact(cls, first, second):
        return cls.normalize(first) == cls.normalize(second)

    @classmethod
    def contains(cls, source, target):
        return bool(cls.normalize(target)) and cls.normalize(target) in cls.normalize(source)

    @classmethod
    def startswith(cls, source, target):
        return cls.normalize(source).startswith(cls.normalize(target))

    @classmethod
    def endswith(cls, source, target):
        return cls.normalize(source).endswith(cls.normalize(target))

    @classmethod
    def build_match(cls, matched, score, method, obj):
        return {"matched": matched, "score": round(score, 2), "method": method, "object": obj}

    @classmethod
    def clear_cache(cls):
        with cls._lock:
            cls._initialized = False
            cls._product_cache = {}
            cls._product_alias_cache = {}
            cls._product_match_cache = {}
            cls._representative_cache = {}
            cls._representative_alias_cache = {}
            cls._representative_match_cache = {}

    @classmethod
    def load_cache(cls):
        with cls._lock:
            if cls._initialized:
                return

            cls._product_cache = {}
            cls._product_alias_cache = {}
            cls._product_match_cache = {}
            cls._representative_cache = {}
            cls._representative_alias_cache = {}
            cls._representative_match_cache = {}

            for product in Product.query.filter_by(is_active=True).all():
                for label in (product.product_name, product.product_code, product.ims_name):
                    normalized = cls.normalize(label)
                    if normalized:
                        cls._product_cache[normalized] = product

            for alias in ProductAlias.query.all():
                normalized = cls.normalize(alias.alias_name)
                if normalized and alias.product and alias.product.is_active:
                    cls._product_alias_cache[normalized] = alias.product

            for match in ProductMatch.query.all():
                normalized = cls.normalize(match.ims_name)
                if normalized and match.product and match.product.is_active:
                    cls._product_match_cache[normalized] = match.product

            for representative in Representative.query.filter_by(active=True).all():
                for label in (representative.rep_name, representative.rep_code, representative.ims_code):
                    normalized = cls.normalize(label)
                    if normalized:
                        cls._representative_cache[normalized] = representative

            for alias in RepresentativeAlias.query.all():
                normalized = cls.normalize(alias.alias_name)
                if normalized and alias.representative and alias.representative.active:
                    cls._representative_alias_cache[normalized] = alias.representative

            for match in RepresentativeMatch.query.all():
                normalized = cls.normalize(match.ims_name)
                if normalized and match.representative and match.representative.active:
                    cls._representative_match_cache[normalized] = match.representative

            cls._statistics.update(
                product=len({item.id for item in cls._product_cache.values()}),
                product_alias=len(cls._product_alias_cache),
                representative=len({item.id for item in cls._representative_cache.values()}),
                representative_alias=len(cls._representative_alias_cache),
            )
            cls._initialized = True
            cls._cache_version += 1

    @classmethod
    def refresh(cls):
        cls.clear_cache()
        cls.load_cache()

    @classmethod
    def _find(cls, value, primary_cache, alias_cache, match_cache, minimum_score):
        cls.load_cache()
        normalized = cls.normalize(value)
        if not normalized:
            cls._statistics["cache_miss"] += 1
            return cls.build_match(False, 0, "EMPTY", None)

        # Priority 1: persistent match table (manually confirmed or auto-persisted)
        obj = match_cache.get(normalized)
        if obj is not None:
            cls._statistics["cache_hits"] += 1
            return cls.build_match(True, 100, "MATCH_TABLE", obj)

        # Priority 2 & 3: exact primary cache (covers code, name, ims_name)
        # Priority 4: alias cache
        for cache, method in ((primary_cache, "EXACT"), (alias_cache, "ALIAS")):
            obj = cache.get(normalized)
            if obj is not None:
                cls._statistics["cache_hits"] += 1
                return cls.build_match(True, 100, method, obj)

        # Priority 5: contains match
        candidates = [
            (label, obj, "CONTAINS")
            for label, obj in primary_cache.items()
            if label in normalized or normalized in label
        ]
        candidates.extend(
            (label, obj, "ALIAS_CONTAINS")
            for label, obj in alias_cache.items()
            if label in normalized or normalized in label
        )
        if candidates:
            label, obj, method = max(candidates, key=lambda item: len(item[0]))
            cls._statistics["cache_hits"] += 1
            return cls.build_match(True, 100, method, obj)

        # Priority 6: fuzzy similarity >= threshold
        best_label = ""
        best_obj = None
        best_method = "NO_MATCH"
        best_score = 0.0
        for cache, method in ((primary_cache, "SIMILARITY"), (alias_cache, "ALIAS_SIMILARITY")):
            for label, obj in cache.items():
                score = cls.similarity(normalized, label)
                if score > best_score:
                    best_label, best_obj, best_method, best_score = label, obj, method, score

        if best_obj is not None and best_score >= minimum_score:
            cls._statistics["cache_hits"] += 1
            return cls.build_match(True, best_score * 100, best_method, best_obj)

        # No match found
        cls._statistics["cache_miss"] += 1
        return cls.build_match(False, best_score * 100, "NO_MATCH", None)

    @classmethod
    def find_product(cls, value, minimum_score=None):
        cls.load_cache()
        return cls._find(
            value,
            cls._product_cache,
            cls._product_alias_cache,
            cls._product_match_cache,
            cls.SIMILARITY_LIMIT if minimum_score is None else minimum_score,
        )

    @classmethod
    def find_representative(cls, value, minimum_score=None):
        cls.load_cache()
        return cls._find(
            value,
            cls._representative_cache,
            cls._representative_alias_cache,
            cls._representative_match_cache,
            cls.SIMILARITY_LIMIT if minimum_score is None else minimum_score,
        )

    @classmethod
    def enqueue_unmatched_representative(cls, ims_name, upload_id=None, best_candidate=None, best_score=0.0):
        """Add an unmatched representative name to the manual match queue (idempotent)."""
        normalized = cls.normalize(ims_name)
        if not normalized:
            return None
        existing = ManualMatchQueue.query.filter_by(
            entity_type=ManualMatchQueue.ENTITY_REPRESENTATIVE,
            ims_name=ims_name.strip(),
        ).first()
        if existing:
            if existing.status == ManualMatchQueue.STATUS_PENDING:
                existing.upload_id = upload_id or existing.upload_id
                existing.best_candidate = best_candidate or existing.best_candidate
                existing.best_score = max(best_score, existing.best_score)
            return existing
        entry = ManualMatchQueue(
            entity_type=ManualMatchQueue.ENTITY_REPRESENTATIVE,
            ims_name=ims_name.strip(),
            upload_id=upload_id,
            best_candidate=best_candidate,
            best_score=best_score,
            status=ManualMatchQueue.STATUS_PENDING,
        )
        db.session.add(entry)
        return entry

    @classmethod
    def enqueue_unmatched_product(cls, ims_name, upload_id=None, best_candidate=None, best_score=0.0):
        """Add an unmatched product name to the manual match queue (idempotent)."""
        normalized = cls.normalize(ims_name)
        if not normalized:
            return None
        existing = ManualMatchQueue.query.filter_by(
            entity_type=ManualMatchQueue.ENTITY_PRODUCT,
            ims_name=ims_name.strip(),
        ).first()
        if existing:
            if existing.status == ManualMatchQueue.STATUS_PENDING:
                existing.upload_id = upload_id or existing.upload_id
                existing.best_candidate = best_candidate or existing.best_candidate
                existing.best_score = max(best_score, existing.best_score)
            return existing
        entry = ManualMatchQueue(
            entity_type=ManualMatchQueue.ENTITY_PRODUCT,
            ims_name=ims_name.strip(),
            upload_id=upload_id,
            best_candidate=best_candidate,
            best_score=best_score,
            status=ManualMatchQueue.STATUS_PENDING,
        )
        db.session.add(entry)
        return entry

    @classmethod
    def persist_representative_match(cls, ims_name, representative, method="AUTO", score=100.0, created_by=None):
        """Persist a representative match to the match table and refresh cache."""
        normalized = cls.normalize(ims_name)
        if not normalized or representative is None:
            return None
        existing = RepresentativeMatch.query.filter_by(ims_name=ims_name.strip()).first()
        if existing:
            existing.representative_id = representative.id
            existing.match_method = method
            existing.match_score = score
            existing.created_by = created_by or existing.created_by
        else:
            existing = RepresentativeMatch(
                ims_name=ims_name.strip(),
                representative_id=representative.id,
                match_method=method,
                match_score=score,
                created_by=created_by,
            )
            db.session.add(existing)
        cls.refresh()
        return existing

    @classmethod
    def persist_product_match(cls, ims_name, product, method="AUTO", score=100.0, created_by=None):
        """Persist a product match to the match table and refresh cache."""
        normalized = cls.normalize(ims_name)
        if not normalized or product is None:
            return None
        existing = ProductMatch.query.filter_by(ims_name=ims_name.strip()).first()
        if existing:
            existing.product_id = product.id
            existing.match_method = method
            existing.match_score = score
            existing.created_by = created_by or existing.created_by
        else:
            existing = ProductMatch(
                ims_name=ims_name.strip(),
                product_id=product.id,
                match_method=method,
                match_score=score,
                created_by=created_by,
            )
            db.session.add(existing)
        cls.refresh()
        return existing

    @classmethod
    def product_id(cls, value):
        result = cls.find_product(value)
        return result["object"].id if result["matched"] else None

    @classmethod
    def representative_id(cls, value):
        result = cls.find_representative(value)
        return result["object"].id if result["matched"] else None

    @classmethod
    def exists_product(cls, value):
        return cls.find_product(value)["matched"]

    @classmethod
    def exists_representative(cls, value):
        return cls.find_representative(value)["matched"]

    @classmethod
    def _match_list(cls, values, matcher, object_key, name_key):
        matched, unmatched = [], []
        for value in values:
            result = matcher(value)
            if result["matched"]:
                item = result["object"]
                matched.append(
                    {
                        "source": value,
                        object_key: item.id,
                        name_key: getattr(item, name_key),
                        "score": result["score"],
                        "method": result["method"],
                    }
                )
            else:
                unmatched.append(value)
        return {
            "matched": matched,
            "unmatched": unmatched,
            "matched_count": len(matched),
            "unmatched_count": len(unmatched),
        }

    @classmethod
    def match_product_list(cls, values, minimum_score=None):
        return cls._match_list(
            values,
            lambda value: cls.find_product(value, minimum_score),
            "product_id",
            "product_name",
        )

    @classmethod
    def match_representative_list(cls, values, minimum_score=None):
        return cls._match_list(
            values,
            lambda value: cls.find_representative(value, minimum_score),
            "representative_id",
            "rep_name",
        )

    @classmethod
    def create_product_alias(cls, product, alias_name):
        if product is None or not cls.normalize(alias_name):
            return None
        existing = ProductAlias.query.filter_by(product_id=product.id, alias_name=alias_name.strip()).first()
        if existing:
            return existing
        alias = ProductAlias(product_id=product.id, alias_name=alias_name.strip())
        db.session.add(alias)
        db.session.commit()
        cls.refresh()
        return alias

    @classmethod
    def create_representative_alias(cls, representative, alias_name):
        if representative is None or not cls.normalize(alias_name):
            return None
        existing = RepresentativeAlias.query.filter_by(
            representative_id=representative.id, alias_name=alias_name.strip()
        ).first()
        if existing:
            return existing
        alias = RepresentativeAlias(representative_id=representative.id, alias_name=alias_name.strip())
        db.session.add(alias)
        db.session.commit()
        cls.refresh()
        return alias

    @classmethod
    def _conflicts(cls, model, identifier):
        seen, conflicts = {}, []
        for alias in model.query.all():
            key = cls.normalize(alias.alias_name)
            owner = getattr(alias, identifier)
            if key in seen and seen[key] != owner:
                conflicts.append({"alias": alias.alias_name, "first": seen[key], "second": owner})
            else:
                seen[key] = owner
        return conflicts

    @classmethod
    def alias_conflicts(cls):
        return cls._conflicts(ProductAlias, "product_id")

    @classmethod
    def representative_conflicts(cls):
        return cls._conflicts(RepresentativeAlias, "representative_id")

    @classmethod
    def statistics(cls):
        cls.load_cache()
        hit = cls._statistics["cache_hits"]
        miss = cls._statistics["cache_miss"]
        return {
            "cache_version": cls._cache_version,
            "initialized": cls._initialized,
            "products": cls._statistics["product"],
            "product_aliases": cls._statistics["product_alias"],
            "representatives": cls._statistics["representative"],
            "representative_aliases": cls._statistics["representative_alias"],
            "cache_hits": hit,
            "cache_miss": miss,
            "hit_ratio": round(hit * 100 / (hit + miss), 2) if hit + miss else 0,
        }

    @classmethod
    def reset_statistics(cls):
        cls._statistics["cache_hits"] = 0
        cls._statistics["cache_miss"] = 0
        return cls.statistics()

    @classmethod
    def validate(cls):
        cls.load_cache()
        errors = []
        if not cls._product_cache:
            errors.append("Aktif ürün bulunamadı.")
        if not cls._representative_cache:
            errors.append("Aktif temsilci bulunamadı.")
        if cls.alias_conflicts():
            errors.append("Ürün alias çakışmaları bulundu.")
        if cls.representative_conflicts():
            errors.append("Temsilci alias çakışmaları bulundu.")
        return {"success": not errors, "errors": errors, "statistics": cls.statistics()}

    @classmethod
    def health_check(cls):
        report = cls.validate()
        report.update(service="AliasService", status="Healthy" if report["success"] else "Warning")
        return report

    @classmethod
    def warmup(cls):
        cls.load_cache()
        return cls.statistics()

    @classmethod
    def export_cache(cls):
        cls.load_cache()
        return {
            "products": sorted(cls._product_cache),
            "product_aliases": sorted(cls._product_alias_cache),
            "representatives": sorted(cls._representative_cache),
            "representative_aliases": sorted(cls._representative_alias_cache),
        }

    @classmethod
    def clear(cls):
        cls.clear_cache()
        cls.reset_statistics()
        return True
