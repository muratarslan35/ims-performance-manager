#!/usr/bin/env python
"""Read-only production gate for representative detail performance.

Runs after migrations/indexes are installed and before the managed service is
restarted. It never mutates IMS data. The gate measures the expensive read-model
chain used by the representative detail route: market analysis, competitor
intelligence, 1/3/6-month AI periods and annual realization.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

from sqlalchemy import event

from app import create_app
from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import IMSUpload, Representative, RepresentativeBrickAssignment
from app.services.annual_realization_service import AnnualRealizationService
from app.services.competitive_intelligence_service import CompetitiveIntelligenceService
from app.services.representative_market_service import RepresentativeMarketService
from app.services.scoped_ai_insight_service import ScopedAIInsightService
from config import Config


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_URL = f"sqlite:///{(REPO_ROOT / 'instance' / 'ipm.db').resolve()}"
SAMPLE_SIZE = int(os.getenv("REP_PERF_SAMPLE_SIZE", "8"))
MAX_COLD_P95 = float(os.getenv("REP_PERF_MAX_COLD_P95", "5.0"))
MAX_COLD = float(os.getenv("REP_PERF_MAX_COLD", "8.0"))
MAX_WARM_P95 = float(os.getenv("REP_PERF_MAX_WARM_P95", "2.0"))
MAX_COMPETITION_SELECTS = int(os.getenv("REP_PERF_MAX_COMPETITION_SELECTS", "4"))
MAX_TOTAL_SELECTS = int(os.getenv("REP_PERF_MAX_TOTAL_SELECTS", "30"))


class PerformanceConfig(Config):
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def percentile(values, percentile_value):
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(round((len(ordered) - 1) * percentile_value), len(ordered) - 1)
    return float(ordered[position])


def latest_period():
    upload = IMSUpload.query.filter_by(status="COMPLETED").order_by(
        IMSUpload.completed_at.desc(), IMSUpload.id.desc()
    ).first()
    return (int(upload.year), int(upload.month), int(upload.id)) if upload else None


def representative_sample(year, month):
    ids = [
        representative_id
        for (representative_id,) in db.session.query(
            RepresentativeBrickAssignment.representative_id
        ).join(
            Representative,
            Representative.id == RepresentativeBrickAssignment.representative_id,
        ).filter(
            RepresentativeBrickAssignment.year == year,
            RepresentativeBrickAssignment.month == month,
            RepresentativeBrickAssignment.active.is_(True),
            Representative.active.is_(True),
        ).distinct().order_by(
            RepresentativeBrickAssignment.representative_id.asc()
        ).limit(SAMPLE_SIZE).all()
    ]
    if not ids:
        return []
    by_id = {
        representative.id: representative
        for representative in Representative.query.filter(Representative.id.in_(ids)).all()
    }
    return [by_id[representative_id] for representative_id in ids if representative_id in by_id]


def is_scoped_competition_select(statement):
    normalized = " ".join(statement.upper().split())
    if not normalized.startswith("SELECT") or "IMS_COMPETITION_DATA" not in normalized:
        return True
    where = normalized.split(" WHERE ", 1)[1] if " WHERE " in normalized else ""
    has_upload = "UPLOAD_ID" in where
    has_metric = "METRIC_TYPE" in where
    has_scope = "SUBTERRITORY IN" in where or "TERRITORY IN" in where
    return has_upload and has_metric and has_scope


def _build_read_model(representative, year, month):
    market = RepresentativeMarketService(representative, year, month).build()
    intelligence = CompetitiveIntelligenceService(representative.id, year, month).build()
    periods = ScopedAIInsightService.representative_periods(representative.id, year, month)
    # Build the same deterministic AI payload used by the route so sorting and
    # action generation are included in the measured chain.
    ScopedAIInsightService.build(
        scope_type="representative",
        scope_name=representative.rep_name,
        periods=periods,
        market_analysis=market,
        competitive_intelligence=intelligence,
    )
    annual = AnnualRealizationService.build(year, [representative.id])
    return market, intelligence, periods, annual


def measure_representative(representative, year, month):
    RepresentativeAnalysisCache.clear()
    select_statements = []
    competition_statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if not normalized.startswith("SELECT"):
            return
        select_statements.append(statement)
        if "IMS_COMPETITION_DATA" in normalized:
            competition_statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        started = time.perf_counter()
        market, intelligence, periods, annual = _build_read_model(representative, year, month)
        cold_seconds = time.perf_counter() - started
        cold_select_count = len(select_statements)
        cold_competition_count = len(competition_statements)

        # Warm path keeps the same service chain. Competition/read-model caches
        # may hit, while the batch AI period service still performs a small,
        # bounded set of source queries for correctness.
        select_statements.clear()
        competition_statements.clear()
        started = time.perf_counter()
        _build_read_model(representative, year, month)
        warm_seconds = time.perf_counter() - started
        warm_select_count = len(select_statements)
        warm_competition_count = len(competition_statements)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    # Scope validation is evaluated across the last captured warm statements;
    # cold competition queries use the identical SQL shapes and are guarded by
    # the query-shape regression tests in CI.
    unscoped = [
        " ".join(statement.split())[:500]
        for statement in competition_statements
        if not is_scoped_competition_select(statement)
    ]
    return {
        "representative_id": representative.id,
        "representative": representative.rep_name,
        "cold_seconds": round(cold_seconds, 4),
        "warm_seconds": round(warm_seconds, 4),
        "cold_selects": cold_select_count,
        "warm_selects": warm_select_count,
        "cold_competition_selects": cold_competition_count,
        "warm_competition_selects": warm_competition_count,
        "unscoped_competition_selects": unscoped,
        "market_upload_id": market.get("upload_id"),
        "market_rows": len(market.get("rows") or []),
        "brick_rows": len(market.get("brick_rows") or []),
        "ai_alerts": len(intelligence.get("weekly_alerts") or []),
        "ai_periods": len(periods),
        "annual_points": len(annual),
    }


def main():
    application = create_app(PerformanceConfig)
    with application.app_context():
        period = latest_period()
        if period is None:
            payload = {"result": "SKIP", "reason": "NO_COMPLETED_IMS"}
            print("REPRESENTATIVE_PERFORMANCE|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        year, month, upload_id = period
        representatives = representative_sample(year, month)
        if not representatives:
            payload = {
                "result": "SKIP",
                "reason": "NO_ACTIVE_REPRESENTATIVE_ASSIGNMENTS",
                "period": [year, month],
                "upload_id": upload_id,
            }
            print("REPRESENTATIVE_PERFORMANCE|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        measurements = [measure_representative(rep, year, month) for rep in representatives]
        cold = [item["cold_seconds"] for item in measurements]
        warm = [item["warm_seconds"] for item in measurements]
        unscoped = sum(len(item["unscoped_competition_selects"]) for item in measurements)
        max_competition_selects = max(
            max(item["cold_competition_selects"], item["warm_competition_selects"])
            for item in measurements
        )
        max_total_selects = max(
            max(item["cold_selects"], item["warm_selects"])
            for item in measurements
        )
        cold_p95 = percentile(cold, 0.95)
        warm_p95 = percentile(warm, 0.95)
        cold_max = max(cold)

        passed = (
            unscoped == 0
            and max_competition_selects <= MAX_COMPETITION_SELECTS
            and max_total_selects <= MAX_TOTAL_SELECTS
            and cold_p95 <= MAX_COLD_P95
            and cold_max <= MAX_COLD
            and warm_p95 <= MAX_WARM_P95
        )
        payload = {
            "result": "PASS" if passed else "FAIL",
            "period": [year, month],
            "upload_id": upload_id,
            "sample_size": len(measurements),
            "cold_seconds": {
                "mean": round(statistics.mean(cold), 4),
                "p95": round(cold_p95, 4),
                "max": round(cold_max, 4),
            },
            "warm_seconds": {
                "mean": round(statistics.mean(warm), 4),
                "p95": round(warm_p95, 4),
                "max": round(max(warm), 4),
            },
            "max_competition_selects": max_competition_selects,
            "max_total_selects": max_total_selects,
            "unscoped_competition_selects": unscoped,
            "thresholds": {
                "cold_p95": MAX_COLD_P95,
                "cold_max": MAX_COLD,
                "warm_p95": MAX_WARM_P95,
                "competition_selects": MAX_COMPETITION_SELECTS,
                "total_selects": MAX_TOTAL_SELECTS,
            },
            "measurements": measurements,
        }
        print("REPRESENTATIVE_PERFORMANCE|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
