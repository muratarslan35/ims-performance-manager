"""SQL-scoped read-path optimizations for representative market analysis.

Every high-volume path is constrained by upload + representative/brick scope in
SQL. Source-label normalization is represented as a bounded set of SQL candidate
labels; it never falls back to loading an entire competition upload into Python.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from sqlalchemy import or_

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSRawData, RepresentativeBrickAssignment
from app.services.alias_service import AliasService
from app.services.production_result_service import ProductionResultService


_snapshot_upload_ids = ContextVar("representative_snapshot_upload_ids", default=None)
_snapshot_read_cache = ContextVar("representative_snapshot_read_cache", default=None)


@contextmanager
def use_snapshot_upload_ids(upload_ids):
    """Pin immutable source identity and reuse one representative's repeated reads.

    Normal requests keep their existing request-local behavior. The persistent
    snapshot builder, however, opens the same representative/month data through
    both the sales workspace and market workspace. A small context-local cache
    lets those paths share exact authoritative results without changing any
    formula, import row, publication rule or rollback state.
    """
    upload_token = _snapshot_upload_ids.set(dict(upload_ids or {}))
    cache_token = _snapshot_read_cache.set({
        "effective_products": {},
        "market_products": None,
        "market_scopes": {},
    })
    try:
        yield
    finally:
        _snapshot_read_cache.reset(cache_token)
        _snapshot_upload_ids.reset(upload_token)


def _key(value):
    return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())


def _scope_signature(values):
    encoded = "|".join(sorted(value for value in values if value)).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:16]


def _namespace_rows(rows):
    return [SimpleNamespace(**dict(row._mapping)) for row in rows]


def _label_candidates(value):
    raw = str(value or "").strip()
    if not raw:
        return set()
    normalized = str(AliasService.normalize(raw) or "").strip()
    return {candidate for candidate in (raw, normalized) if candidate}


def _candidate_set(values):
    candidates = set()
    for value in values or ():
        candidates.update(_label_candidates(value))
    return candidates


def install_representative_market_query_optimizer():
    from app.services.representative_market_service import RepresentativeMarketService

    if getattr(RepresentativeMarketService, "_sql_scope_optimizer_installed", False):
        return

    original_workbook_fallback = RepresentativeMarketService._brick_competition_rows_from_workbook
    original_build = RepresentativeMarketService.build
    original_latest_upload_id = RepresentativeMarketService._latest_upload_id
    original_products = RepresentativeMarketService._products
    original_scope = RepresentativeMarketService._scope
    original_effective_products = ProductionResultService.effective_products.__func__

    def effective_products(cls, year, month, representative_id, product_ids=None):
        """Reuse an exact production-aware period result inside one snapshot member.

        The representative workspace asks for the same effective period twice:
        once while aggregating sales and again while building market rows.  The
        authoritative resolver is still called for the first request; subsequent
        requests in that same snapshot member reuse the returned mapping.
        Outside snapshot generation this wrapper is a transparent pass-through.
        """
        cache = _snapshot_read_cache.get()
        if cache is None:
            return original_effective_products(cls, year, month, representative_id, product_ids)

        requested = tuple(sorted({int(item) for item in product_ids or ()})) or None
        key = (int(year), int(month), int(representative_id), requested)
        effective_cache = cache["effective_products"]
        if key not in effective_cache:
            effective_cache[key] = original_effective_products(
                cls, year, month, representative_id, product_ids
            )
        return effective_cache[key]

    def products(self):
        """Load the seven managed product objects once per representative build."""
        cache = _snapshot_read_cache.get()
        if cache is None:
            return original_products(self)
        if cache["market_products"] is None:
            cache["market_products"] = original_products(self)
        return cache["market_products"]

    def scope(self):
        """Reuse the market scope already loaded by the canonical market builder."""
        cache = _snapshot_read_cache.get()
        if cache is None:
            return original_scope(self)
        key = (int(self.representative.id), int(self.year), int(self.month))
        scoped = cache["market_scopes"].get(key)
        if scoped is None:
            scoped = original_scope(self)
            cache["market_scopes"][key] = scoped
        return scoped

    def latest_upload_id(self, year, month):
        """Resolve one period upload once per market-service build.

        A representative market build asks for the active upload from several
        independent read paths (aggregate competition, brick raw rows and exact
        brick competition).  The value cannot change inside one request/build,
        so repeating the same indexed SELECT only adds latency/query pressure.
        Keep the memo strictly on this service instance: no cross-request or
        cross-period state is shared.
        """
        key = (int(year), int(month))
        pinned = _snapshot_upload_ids.get()
        if pinned is not None and key in pinned:
            return pinned[key]
        cache = getattr(self, "_rep_query_upload_id_cache", None)
        if cache is None:
            cache = {}
            self._rep_query_upload_id_cache = cache
        if key not in cache:
            cache[key] = original_latest_upload_id(*key)
        return cache[key]

    def scope_values(self, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        key = (year, month)
        cache = getattr(self, "_rep_query_scope_values_cache", None)
        if cache is None:
            cache = {}
            self._rep_query_scope_values_cache = cache
        cached = cache.get(key)
        if cached is not None:
            # Return copies so downstream normalization cannot mutate the
            # request-local memo used by another path in this same build.
            return set(cached[0]), set(cached[1])

        snapshot_cache = _snapshot_read_cache.get()
        if snapshot_cache is not None:
            snapshot_scope = snapshot_cache["market_scopes"].get(
                (int(self.representative.id), year, month)
            )
            if snapshot_scope is not None:
                assignments, _brick_keys, _fallback_keys = snapshot_scope
                brick_values = {
                    str(item.brick).strip()
                    for item in assignments
                    if str(getattr(item, "brick", "") or "").strip()
                }
                fallback_values = {
                    str(value).strip()
                    for value in (
                        self.representative.territory,
                        self.representative.city,
                        self.representative.region,
                    )
                    if str(value or "").strip()
                }
                cache[key] = (set(brick_values), set(fallback_values))
                return brick_values, fallback_values

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
        cache[key] = (set(brick_values), set(fallback_values))
        return brick_values, fallback_values

    def competition_rows(self, brick_keys, fallback_keys, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = latest_upload_id(self, year, month)
        if upload_id is None:
            return None, []

        # The request-scoped Week-8 adapter rebuilds the previous-month rival
        # comparison from exact named brick rows.  Do not execute the base
        # aggregate comparison query as well: its result is immediately
        # replaced by that adapter and previously added one redundant
        # competition SELECT to every representative detail request.
        if (
            getattr(self, "_skip_base_previous_competition", False)
            and (year, month) != (self.year, self.month)
        ):
            return upload_id, []

        # Historical comparison intentionally applies the representative's
        # current brick scope to the requested historical upload. This keeps
        # month-over-month deltas comparable even when no assignment snapshot
        # exists for the previous month.
        brick_values, fallback_values = scope_values(self)
        representative_labels = _label_candidates(self.representative.rep_name)
        brick_labels = _candidate_set(brick_values)
        geography_labels = _candidate_set(fallback_values)
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
            if brick_labels:
                sql_scopes.append(CompetitionData.subterritory.in_(sorted(brick_labels)))
            if geography_labels:
                sql_scopes.append(CompetitionData.territory.in_(sorted(geography_labels)))
            rows = _namespace_rows(query.filter(or_(*sql_scopes)).all()) if sql_scopes else []

            # The exact-brick path executes immediately after this aggregate read
            # during one representative build. Keep the already-fetched bounded
            # row set on the service instance so that path can select its monthly
            # named-rival rows without issuing the same CompetitionData SELECT a
            # second time. This cache is request/build-local and never shared.
            raw_cache = getattr(self, "_rep_query_competition_raw_cache", None)
            if raw_cache is None:
                raw_cache = {}
                self._rep_query_competition_raw_cache = raw_cache
            raw_cache[(year, month, int(upload_id))] = list(rows)

            representative_key = self._key(self.representative.rep_name)
            representative_rows = [row for row in rows if self._key(row.subterritory) == representative_key]
            if representative_rows:
                return representative_rows

            scope_keys = set(brick_keys or ()) or set(fallback_keys or ())
            return [
                row for row in rows
                if self._key(row.subterritory) in scope_keys or self._key(row.territory) in scope_keys
            ]

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=45)

    def brick_raw_rows(self, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = latest_upload_id(self, year, month)
        brick_values, _ = scope_values(self, year, month)
        brick_keys = {_key(value) for value in brick_values if _key(value)}
        brick_labels = _candidate_set(brick_values)
        if upload_id is None or not brick_keys:
            return None, []
        cache_key = (
            f"rep-market:raw:{self.representative.id}:{year}:{month}:{upload_id}:"
            f"{_scope_signature(brick_keys)}"
        )

        def load():
            rows = db.session.query(
                IMSRawData.product_id.label("product_id"),
                IMSRawData.brick.label("brick"),
                IMSRawData.sheet_type.label("sheet_type"),
                IMSRawData.unit.label("unit"),
            ).filter(
                IMSRawData.upload_id == upload_id,
                IMSRawData.year == year,
                IMSRawData.month == month,
                IMSRawData.product_id.isnot(None),
                IMSRawData.brick.in_(sorted(brick_labels)),
                IMSRawData.sheet_type.in_(("brick_sales", "competition_box")),
            ).all()
            return [row for row in _namespace_rows(rows) if self._key(row.brick) in brick_keys]

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=45)

    def brick_competition_rows(self, brick_keys):
        upload_id = latest_upload_id(self, self.year, self.month)
        brick_values, _ = scope_values(self, self.year, self.month)
        brick_labels = _candidate_set(brick_values)
        if upload_id is None or not brick_keys:
            return None, []

        raw_cache = getattr(self, "_rep_query_competition_raw_cache", {})
        cached_rows = raw_cache.get((self.year, self.month, int(upload_id)))
        if cached_rows is not None:
            exact = [
                row for row in cached_rows
                if self._key(row.subterritory) in brick_keys
                and "AYLIK" in AliasService.normalize(row.sheet_name)
                and "REKABET" in AliasService.normalize(row.sheet_name)
                and "KUTU" in AliasService.normalize(row.sheet_name)
            ]
            if exact:
                return upload_id, exact
            return upload_id, original_workbook_fallback(self, upload_id, brick_keys)

        cache_key = (
            f"rep-market:brick-competition:{self.representative.id}:{self.year}:{self.month}:{upload_id}:"
            f"{_scope_signature(set(brick_keys))}"
        )

        def load():
            rows = db.session.query(
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
                CompetitionData.subterritory.in_(sorted(brick_labels)),
            ).all()
            exact = [
                row for row in _namespace_rows(rows)
                if self._key(row.subterritory) in brick_keys
                and "AYLIK" in AliasService.normalize(row.sheet_name)
                and "REKABET" in AliasService.normalize(row.sheet_name)
                and "KUTU" in AliasService.normalize(row.sheet_name)
            ]
            if exact:
                return exact
            return original_workbook_fallback(self, upload_id, brick_keys)

        return upload_id, RepresentativeAnalysisCache.get_or_compute(cache_key, load, ttl_seconds=60)

    def build_with_batched_production(self):
        # Clear only request/build-local memo state. A service instance may be
        # reused explicitly in tests or internal callers, and a later build
        # must re-resolve period identity rather than carrying stale state.
        self._rep_query_upload_id_cache = {}
        self._rep_query_scope_values_cache = {}
        self._rep_query_competition_raw_cache = {}

        # RepresentativeMarketService renders seven products and historically
        # called effective_product() once per row. Resolve the whole period once
        # and expose it only inside this execution context, so concurrent
        # requests cannot leak or reuse another representative's values.
        effective_rows = ProductionResultService.effective_products(
            self.year, self.month, self.representative.id
        )
        with ProductionResultService.use_effective_batch(
            self.year, self.month, self.representative.id, effective_rows
        ):
            return original_build(self)

    ProductionResultService.effective_products = classmethod(effective_products)
    RepresentativeMarketService._products = products
    RepresentativeMarketService._scope = scope
    RepresentativeMarketService._competition_rows = competition_rows
    RepresentativeMarketService._brick_raw_rows = brick_raw_rows
    RepresentativeMarketService._brick_competition_rows = brick_competition_rows
    RepresentativeMarketService.build = build_with_batched_production
    RepresentativeMarketService._sql_scope_optimizer_installed = True
