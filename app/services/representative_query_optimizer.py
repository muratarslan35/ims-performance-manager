"""SQL-scoped read-path optimizations for representative market analysis.

The legacy service intentionally kept broad Python-side normalization fallbacks,
but that made a representative page scan an entire competition upload repeatedly.
These replacements push the normal brick/representative scope into SQL, select
only the columns used by the read model, and retain a compatibility fallback only
when the exact source labels do not match.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from sqlalchemy import or_

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSRawData, RepresentativeBrickAssignment
from app.services.alias_service import AliasService


def _key(value):
    return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())


def _scope_signature(values):
    encoded = "|".join(sorted(value for value in values if value)).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:16]


def _namespace_rows(rows):
    return [SimpleNamespace(**dict(row._mapping)) for row in rows]


def _label_candidates(value):
    """Return DB-safe source-label variants without broadening business scope."""
    raw = str(value or "").strip()
    if not raw:
        return set()
    normalized = str(AliasService.normalize(raw) or "").strip()
    return {candidate for candidate in (raw, normalized) if candidate}


def install_representative_market_query_optimizer():
    from app.services.representative_market_service import RepresentativeMarketService

    if getattr(RepresentativeMarketService, "_sql_scope_optimizer_installed", False):
        return

    original_workbook_fallback = RepresentativeMarketService._brick_competition_rows_from_workbook

    def scope_values(self, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        rows = db.session.query(RepresentativeBrickAssignment.brick).filter(
            RepresentativeBrickAssignment.representative_id == self.representative.id,
            RepresentativeBrickAssignment.year == year,
            RepresentativeBrickAssignment.month == month,
            RepresentativeBrickAssignment.active.is_(True),
            RepresentativeBrickAssignment.brick.isnot(None),
        ).all()
        brick_values = {str(brick).strip() for (brick,) in rows if str(brick or "").strip()}
        fallback_values = {
            str(value).strip()
            for value in (self.representative.territory, self.representative.city, self.representative.region)
            if str(value or "").strip()
        }
        return brick_values, fallback_values

    def competition_rows(self, brick_keys, fallback_keys, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        if upload_id is None:
            return None, []

        brick_values, fallback_values = scope_values(self)
        representative_labels = _label_candidates(self.representative.rep_name)
        scope_hash = _scope_signature(
            set(brick_keys or ()) | set(fallback_keys or ()) | representative_labels | {str(upload_id)}
        )
        cache_key = f"rep-market:competition:{self.representative.id}:{year}:{month}:{upload_id}:{scope_hash}"

        def load():
            query = db.session.query(
                CompetitionData.subterritory.label("subterritory"),
                CompetitionData.territory.label("territory"),
                CompetitionData.product_group.label("product_group"),
                CompetitionData.product_name.label("product_name"),
                CompetitionData.metric_type.label("metric_type"),
                CompetitionData.metric_value.label("metric_value"),
                CompetitionData.sheet_name.label("sheet_name"),
            ).filter(
                CompetitionData.upload_id == upload_id,
                CompetitionData.metric_type == "UNIT",
                CompetitionData.is_subtotal.is_(False),
                CompetitionData.is_grand_total.is_(False),
            )

            sql_scopes = []
            if representative_labels:
                sql_scopes.append(CompetitionData.subterritory.in_(sorted(representative_labels)))
            if brick_values:
                sql_scopes.append(CompetitionData.subterritory.in_(sorted(brick_values)))
            if fallback_values:
                sql_scopes.append(CompetitionData.territory.in_(sorted(fallback_values)))
            rows = _namespace_rows(query.filter(or_(*sql_scopes)).all()) if sql_scopes else []

            representative_key = self._key(self.representative.rep_name)
            representative_rows = [row for row in rows if self._key(row.subterritory) == representative_key]
            if representative_rows:
                return representative_rows

            scope_keys = set(brick_keys or ()) or set(fallback_keys or ())
            scoped = [
                row for row in rows
                if self._key(row.subterritory) in scope_keys or self._key(row.territory) in scope_keys
            ]
            if scoped or not scope_keys:
                return scoped

            # Compatibility only: historic rows may differ in punctuation/case
            # beyond the normal raw/normalized variants. The normal production
            # path never reaches this whole-upload scan.
            broad = _namespace_rows(query.all())
            representative_rows = [
                row for row in broad if self._key(row.subterritory) == representative_key
            ]
            if representative_rows:
                return representative_rows
            return [
                row for row in broad
                if self._key(row.subterritory) in scope_keys or self._key(row.territory) in scope_keys
            ]

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=45)

    def brick_raw_rows(self, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        brick_values, _ = scope_values(self, year, month)
        brick_keys = {_key(value) for value in brick_values if _key(value)}
        if upload_id is None or not brick_keys:
            return None, []
        cache_key = (
            f"rep-market:raw:{self.representative.id}:{year}:{month}:{upload_id}:"
            f"{_scope_signature(brick_keys)}"
        )

        def load():
            query = db.session.query(
                IMSRawData.product_id.label("product_id"),
                IMSRawData.brick.label("brick"),
                IMSRawData.sheet_type.label("sheet_type"),
                IMSRawData.unit.label("unit"),
            ).filter(
                IMSRawData.upload_id == upload_id,
                IMSRawData.year == year,
                IMSRawData.month == month,
                IMSRawData.product_id.isnot(None),
                IMSRawData.brick.isnot(None),
                IMSRawData.sheet_type.in_(("brick_sales", "competition_box")),
            )
            rows = _namespace_rows(query.filter(IMSRawData.brick.in_(sorted(brick_values))).all())
            scoped = [row for row in rows if self._key(row.brick) in brick_keys]
            if scoped:
                return scoped
            # Legacy compatibility for cosmetic source-label differences.
            return [row for row in _namespace_rows(query.all()) if self._key(row.brick) in brick_keys]

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=45)

    def brick_competition_rows(self, brick_keys):
        upload_id = self._latest_upload_id(self.year, self.month)
        brick_values, _ = scope_values(self)
        if upload_id is None or not brick_keys:
            return None, []
        cache_key = (
            f"rep-market:brick-competition:{self.representative.id}:{self.year}:{self.month}:{upload_id}:"
            f"{_scope_signature(set(brick_keys))}"
        )

        def load():
            query = db.session.query(
                CompetitionData.subterritory.label("subterritory"),
                CompetitionData.territory.label("territory"),
                CompetitionData.product_group.label("product_group"),
                CompetitionData.product_name.label("product_name"),
                CompetitionData.metric_type.label("metric_type"),
                CompetitionData.metric_value.label("metric_value"),
                CompetitionData.sheet_name.label("sheet_name"),
            ).filter(
                CompetitionData.upload_id == upload_id,
                CompetitionData.metric_type == "UNIT",
                CompetitionData.is_subtotal.is_(False),
                CompetitionData.is_grand_total.is_(False),
                CompetitionData.subterritory.in_(sorted(brick_values)),
            )
            rows = _namespace_rows(query.all())
            exact = [
                row for row in rows
                if self._key(row.subterritory) in brick_keys
                and "AYLIK" in AliasService.normalize(row.sheet_name)
                and "REKABET" in AliasService.normalize(row.sheet_name)
                and "KUTU" in AliasService.normalize(row.sheet_name)
            ]
            if exact:
                return exact
            return original_workbook_fallback(self, upload_id, brick_keys)

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=60)

    RepresentativeMarketService._competition_rows = competition_rows
    RepresentativeMarketService._brick_raw_rows = brick_raw_rows
    RepresentativeMarketService._brick_competition_rows = brick_competition_rows
    RepresentativeMarketService._sql_scope_optimizer_installed = True
