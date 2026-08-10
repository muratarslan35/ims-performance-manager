"""
V3 Architecture: Dashboard Payload Builder
==========================================
Tüm formatlı alt bileşenleri (Formatted DTOs) bir araya getirerek,
Frontend API'nin beklediği tek, dev, iç içe geçmiş (nested) JSON Payload'ını üretir.
Builder Pattern tasarımı sayesinde dict objelerini manipüle etmeyi güvenli kılar,
ayrıca (isteğe bağlı) immutable kullanımını destekler.
"""
import copy
import logging
from typing import Dict, Any, Optional, Mapping, Callable

from app.constants.dashboard_constants import DashboardConstants

logger = logging.getLogger(__name__)


class DashboardPayloadBuilder:
    """
    Builder pattern for constructing the final Frontend API JSON contract.
    
    Architecture & Capabilities:
    - Fluent API design (method chaining via returning self).
    - Null-safe dict aggregations with Recursive Merge logic.
    - Explicit Immutability (Deepcopy) protection capability without reference leaking.
    - Memory Optimized (__slots__).
    - Exception Safe Setters.
    """

    __slots__ = ("_payload",)

    def __init__(self) -> None:
        """Initializes the empty state for the builder payload."""
        self._payload: Dict[str, Any] = {}

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _safe_execute_setter(self, method_name: str, action: Callable[[], None]) -> 'DashboardPayloadBuilder':
        """
        Centralized try/except handler for all setter operations.
        Ensures exception safety and maintains the fluent API chain.
        """
        try:
            action()
        except Exception as e:
            logger.debug("[Builder] %s error: %s", method_name, e, exc_info=False)
        return self

    def _deep_merge(self, target: Dict[str, Any], source: Mapping[str, Any]) -> None:
        """
        Recursively merges source Mapping into target Dict.
        Ensures existing nested dictionaries aren't wiped out completely, 
        None values do not overwrite existing state keys, and prevents mutable reference leaking.
        """
        for key, value in source.items():
            if value is None:
                continue

            if key in target and isinstance(target[key], dict) and isinstance(value, Mapping):
                self._deep_merge(target[key], value)
            else:
                # Prevent reference leaking for nested structures during mapping operations
                if isinstance(value, (Mapping, list, set)):
                    target[key] = copy.deepcopy(value)
                else:
                    target[key] = value

    def _safe_merge(self, source: Optional[Mapping[str, Any]]) -> None:
        """
        Safely bridges incoming mapping to the deep merge helper.
        """
        if not source or not isinstance(source, Mapping):
            return
        self._deep_merge(self._payload, source)

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def reset(self) -> 'DashboardPayloadBuilder':
        """Clears the current state of the builder efficiently for reuse."""
        def action() -> None:
            self._payload.clear()
        return self._safe_execute_setter("reset", action)

    def set_counts(self, counts: Optional[Dict[str, int]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_counts", lambda: self._safe_merge(counts))

    def set_upload_details(self, details: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_upload_details", lambda: self._safe_merge(details))

    def set_recovery(self, recovery: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_recovery", lambda: self._safe_merge(recovery))

    def set_top_reps(self, reps: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_top_reps", lambda: self._safe_merge(reps))

    def set_city_performance(self, perf: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_city_performance", lambda: self._safe_merge(perf))

    def set_market_trend(self, trend: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_market_trend", lambda: self._safe_merge(trend))

    def set_competition_analysis(self, analysis: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        def action() -> None:
            data = analysis or {}
            self._payload["competition_analysis"] = {"market_total_tl": data.get("market_total_tl", 0.0), "company_total_tl": data.get("company_total_tl", 0.0), "competitor_total_tl": data.get("competitor_total_tl", 0.0), "company_share_percent": data.get("company_share_percent", 0.0), "groups": data.get("groups", [])}
        return self._safe_execute_setter("set_competition_analysis", action)

    def set_region_realization(self, regions: Optional[list]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_region_realization", lambda: self._payload.__setitem__("region_realization", regions or []))

    def set_competitor_ai(self, insight: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_competitor_ai", lambda: self._payload.__setitem__("competitor_ai", insight or {"top_products": [], "hot_regions": []}))

    def set_history(self, history: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        return self._safe_execute_setter("set_history", lambda: self._safe_merge(history))

    def set_brick_assignments(self, assignments: Optional[list]) -> 'DashboardPayloadBuilder':
        def action() -> None:
            rows = assignments or []
            self._payload["brick_assignments"] = rows
            self._payload["brick_assignment_summary"] = {
                "total": len(rows),
                "manual": sum(1 for row in rows if row.get("source") == "MANUAL"),
                "auto": sum(1 for row in rows if row.get("source") == "AUTO"),
            }
        return self._safe_execute_setter("set_brick_assignments", action)

    def set_ai_data(self, ai_data: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        def action() -> None:
            data = ai_data or {}
            # AIAnalyticsService exposes domain names while dashboard.html is
            # deliberately kept on the V3 ``ai_*`` presentation contract.
            # Publish both forms for legacy consumers, but always provide
            # null-safe V3 values so a valid import never renders empty cards.
            self._safe_merge(data)
            self._safe_merge({
                "ai_scores": {
                    "risk_score": data.get("risk_score", 0),
                    "opportunity_score": data.get("opportunity_score", 0),
                    "goal_probability": data.get("goal_probability", 0),
                },
                "ai_messages": data.get("daily_summary") or [],
                "ai_next_month": data.get("next_month") or {},
                "ai_risky_products": data.get("risky_products") or [],
                "ai_risky_representatives": data.get("risky_representatives") or [],
                "ai_near_target": data.get("products_close_to_target") or [],
                "ai_recommendation": data.get("action_recommendations") or [],
            })
        return self._safe_execute_setter("set_ai_data", action)

    def set_prime_metrics(self, prime_data: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        """Injects complex Engine outputs and resolves root API keys safely."""
        def action() -> None:
            p_data = prime_data or {}
            payload_ext = {
                "overall_realization_tl": p_data.get("total_realization", 0.0),
                "overall_target_tl": p_data.get("total_target", 0.0),
                "overall_percent": p_data.get("total_tl_percent", 0.0),
                DashboardConstants.KEY_BREAKDOWN: p_data.get("breakdown", {}),
                "quarter_analysis": p_data.get("quarter_analysis", {}),
                "recovery_analysis": p_data.get("recovery_analysis", []),
                "trend_graphs": p_data.get("trend_graphs", {}),
                "what_if_analysis": p_data.get("what_if_analysis", []),
                "comparison_graph": p_data.get("comparison_graph", {}),
                DashboardConstants.KEY_PRODUCTS: p_data.get("products", []),
                DashboardConstants.KEY_STATUS: p_data.get("status", "-"),
                DashboardConstants.KEY_SUCCESS: p_data.get("success", False),
                DashboardConstants.KEY_SIMULATION: p_data.get("simulation", False)
            }
            self._safe_merge(payload_ext)
        return self._safe_execute_setter("set_prime_metrics", action)

    def set_prime_summary(self, summary: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        def action() -> None:
            self._payload[DashboardConstants.KEY_PRIME_SUMMARY] = summary or {}
        return self._safe_execute_setter("set_prime_summary", action)

    def set_quarter_summary(self, summary: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        def action() -> None:
            self._payload[DashboardConstants.KEY_QUARTER] = summary or {}
        return self._safe_execute_setter("set_quarter_summary", action)

    def set_active_period(self, year: int, month: int, quarter: int) -> 'DashboardPayloadBuilder':
        def action() -> None:
            self._payload[DashboardConstants.KEY_ACTIVE_PERIOD] = {
                "year": year, 
                "month": month, 
                "quarter": quarter
            }
        return self._safe_execute_setter("set_active_period", action)

    def set_executive_metrics(self, metrics: Optional[Dict[str, Any]]) -> 'DashboardPayloadBuilder':
        """Publish the workbook-reconciled National KPI contract separately."""
        return self._safe_execute_setter(
            "set_executive_metrics",
            lambda: self._payload.__setitem__("executive_metrics", metrics or {})
        )

    def set_performance(self, exec_time: float) -> 'DashboardPayloadBuilder':
        def action() -> None:
            self._payload[DashboardConstants.KEY_PERFORMANCE] = {
                "total_time": round(float(exec_time), 4)
            }
        return self._safe_execute_setter("set_performance", action)

    def set_cache_info(self, hit: bool, ttl: int) -> 'DashboardPayloadBuilder':
        def action() -> None:
            self._payload[DashboardConstants.KEY_CACHE] = {
                "hit": hit, 
                "ttl_seconds": ttl
            }
        return self._safe_execute_setter("set_cache_info", action)

    def build(self, immutable: bool = False) -> Dict[str, Any]:
        """
        Builds and returns the finalized payload API contract safely.
        
        Args:
            immutable (bool): If True, returns a deepcopy of the payload preventing mutations leaking.
        
        Returns:
            Dict[str, Any]: Presentation-ready Dashboard JSON Payload.
        """
        try:
            if immutable:
                return copy.deepcopy(self._payload)
            return self._payload
        except Exception as e:
            logger.debug("[Builder] Error during build: %s", e, exc_info=False)
            # Guarantee structure integrity on exception
            return self._payload if not immutable else {}
