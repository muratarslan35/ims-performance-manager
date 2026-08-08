"""
V3 Architecture: Dashboard Formatter Layer
==========================================
Yalnızca DTO (Data Transfer Object) sözlüklerini Frontend JSON sözleşmesine göre biçimlendirir.
Sayı yuvarlama (rounding), tarih formatlama (ISO-8601), statü çözümleme ve 
yüzdelik hesaplamalarından sorumludur.
"""
import logging
from typing import Dict, Any, List, Optional, Final, Tuple
from app.constants.dashboard_constants import DashboardConstants

logger = logging.getLogger(__name__)


class DashboardFormatter:
    """
    Formats DTOs into Presentation-ready structures with guaranteed null-safety.
    
    Architecture & Capabilities:
    - Stateless & Thread-Safe
    - Memory Optimized (__slots__)
    - Centralized Constant Resolution
    - Exception Safe & Pure Operations
    - Future i18n Ready via Localized Helpers
    """

    __slots__ = ()

    # =========================================================================
    # PRIVATE CONSTANTS
    # =========================================================================
    _STR_UNKNOWN_CITY: Final[str] = "Unknown"
    _STR_FALLBACK_STATUS: Final[str] = "-"
    _STATUS_CRITICAL_KEYS: Final[Tuple[str, ...]] = ("Kritik", "Critical")
    _STATUS_RISK_KEYS: Final[Tuple[str, ...]] = ("Riskli", "Risk")
    _STATUS_WARNING_KEYS: Final[Tuple[str, ...]] = ("Takip", "Warning")

    # =========================================================================
    # PRIVATE HELPERS (Pure Functions)
    # =========================================================================

    def _log_formatting_error(self, method_name: str, error: Exception) -> None:
        """Centralized lazy logging for formatting errors."""
        logger.debug("[Formatter] Error in %s: %s", method_name, error, exc_info=False)

    def _to_iso_date(self, val: Any) -> Optional[str]:
        """Safely converts a datetime/date object to ISO-8601 string."""
        if not val:
            return None
        if hasattr(val, "isoformat"):
            try:
                return val.isoformat()
            except Exception:
                pass
        return str(val)

    def _safe_round(self, val: Any, digits: int = 0) -> float:
        """Safely parses and rounds numerical values without raising Exceptions."""
        if val is None:
            return 0.0
        try:
            return round(float(val), digits)
        except (ValueError, TypeError):
            return 0.0

    def _calc_percentage(self, actual: float, target: float) -> float:
        """Safely calculates realization percentage without ZeroDivisionError."""
        try:
            if not target or target <= 0:
                return 0.0
            return round((float(actual) / float(target) * 100.0), 1)
        except (ValueError, TypeError):
            return 0.0

    def _resolve_trend(self, growth: float) -> str:
        """Resolves trend indicator strings securely using central constants."""
        try:
            growth = float(growth)
            if growth > 1.0:
                return DashboardConstants.TREND_UP
            if growth < -1.0:
                return DashboardConstants.TREND_DOWN
            return DashboardConstants.TREND_STABLE
        except (ValueError, TypeError):
            return DashboardConstants.TREND_STABLE

    def _calc_risk_score(self, pct: float) -> int:
        """Safely calculates the algorithmic risk score."""
        try:
            return max(0, 100 - int(float(pct)))
        except (ValueError, TypeError):
            return 100

    def _calc_opportunity_score(self, pct: float) -> int:
        """Safely calculates the algorithmic opportunity score."""
        try:
            return int(float(pct))
        except (ValueError, TypeError):
            return 0

    def _resolve_month_label(self, month_idx: int) -> str:
        """Safely resolves month names for charts utilizing central constants."""
        try:
            idx = int(month_idx) - 1
            if 0 <= idx < 12:
                return DashboardConstants.MONTH_NAMES[idx]
        except (ValueError, TypeError):
            pass
        return ""

    def _build_localized_summary(self, total: int, critical: int) -> str:
        """Builds localized summary text securely for future i18n support."""
        return f"Toplam {total} üründen {critical} tanesi kritik durumda."

    def _aggregate_history_metrics(self, dtos: List[Dict[str, Any]], prime_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], float, float]:
        """Consolidates simulation history list and calculates growth & averages."""
        history_list = []
        primes = []
        
        for item in dtos:
            bonus = self._safe_round(item.get("bonus"), 2)
            actual = self._safe_round(item.get("actual_tl"), 2)
            history_list.append({
                "simulation_date": f"{item.get('year', 0)}-{item.get('month', 1):02d}-01T00:00:00",
                "bonus": bonus,
                "summary": {
                    "total_prime": bonus,
                    "total_realization": actual,
                    "total_percent": 0.0
                }
            })
            primes.append(bonus)

        engine_history = prime_data.get("history_entry")
        if engine_history:
            history_list.insert(0, engine_history)
            primes.insert(0, self._safe_round(engine_history.get("summary", {}).get("total_prime")))
            
        avg_prime = self._safe_round(sum(primes) / len(primes), 2) if primes else 0.0
        
        growth = 0.0
        if len(primes) >= 2 and primes[-1]:
            growth = self._safe_round(((primes[0] - primes[-1]) / primes[-1]) * 100.0, 2)
            
        return history_list, avg_prime, growth

    def _aggregate_recovery_stats(self, recovery_data: List[Dict[str, Any]]) -> Tuple[int, int, int, int]:
        """Calculates recovery state buckets based on standard classification tuples."""
        critical = risk = warning = healthy = 0
        for item in recovery_data:
            status = str(item.get("status", ""))
            if status in self._STATUS_CRITICAL_KEYS:
                critical += 1
            elif status in self._STATUS_RISK_KEYS:
                risk += 1
            elif status in self._STATUS_WARNING_KEYS:
                warning += 1
            else:
                healthy += 1
        return critical, risk, warning, healthy

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def format_percentage(self, actual: float, target: float) -> float:
        """Public alias for percentage calculation for backward compatibility."""
        return self._calc_percentage(actual, target)

    def format_upload_details(self, dto: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Formats upload information and constructs nested dictionary."""
        try:
            if not dto or not dto.get("upload_id"):
                return {
                    "last_upload": None,
                    "latest_upload_file": None,
                    "latest_upload_date": None,
                    "latest_upload_status": None,
                    DashboardConstants.KEY_UPLOAD_DETAILS: {}
                }

            uploaded_iso = self._to_iso_date(dto.get("uploaded_at"))
            completed_iso = self._to_iso_date(dto.get("completed_at"))
            
            return {
                "last_upload": {"id": dto.get("upload_id"), "status": dto.get("status")},
                "latest_upload_file": dto.get("file_name"),
                "latest_upload_date": uploaded_iso,
                "latest_upload_status": dto.get("status"),
                DashboardConstants.KEY_UPLOAD_DETAILS: {
                    "file": dto.get("file_name"),
                    "quarter": dto.get("quarter"),
                    "month": dto.get("month"),
                    "year": dto.get("year"),
                    "uploaded_at": uploaded_iso,
                    "completed_at": completed_iso,
                    "processing_time": self._safe_round(dto.get("processing_time"), 2),
                    "status": dto.get("status"),
                    "warning_message": dto.get("warning_message"),
                    "error_message": dto.get("error_message"),
                    "sheet_count": dto.get("sheet_count", 0),
                    "raw_record_count": dto.get("raw_record_count", 0),
                    "fact_record_count": dto.get("fact_record_count", 0),
                    "summary_record_count": dto.get("summary_record_count", 0),
                    "pending_match_count": dto.get("pending_match_count", 0),
                    "resolved_match_count": dto.get("resolved_match_count", 0)
                }
            }
        except Exception as e:
            self._log_formatting_error("format_upload_details", e)
            return {}

    def format_top_reps(self, dtos: Optional[List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Formats top representatives and assigns frontend ranks."""
        try:
            if not dtos: 
                return {DashboardConstants.KEY_TOP_REPRESENTATIVES: []}
            
            formatted = []
            for item in dtos:
                pct = self._calc_percentage(item.get("actual_tl", 0.0), item.get("target_tl", 0.0))
                formatted.append({
                    "rep_name": item.get("rep_name", ""),
                    "city": item.get("city", "-"),
                    "total_tl": self._safe_round(item.get("actual_tl"), 0),
                    "realization_percent": pct,
                    "bonus_amount": self._safe_round(item.get("bonus_amount"), 0)
                })
            
            formatted.sort(key=lambda x: x["realization_percent"], reverse=True)
            for i, item in enumerate(formatted):
                item["rank"] = i + 1
                
            return {DashboardConstants.KEY_TOP_REPRESENTATIVES: formatted}
        except Exception as e:
            self._log_formatting_error("format_top_reps", e)
            return {DashboardConstants.KEY_TOP_REPRESENTATIVES: []}

    def format_city_performance(self, dtos: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        """Formats city metrics and calculates risk/opportunity frontend scores."""
        try:
            if not dtos: 
                return {DashboardConstants.KEY_CITY_PERFORMANCE: {}}
                
            formatted = {}
            for item in dtos:
                pct = self._calc_percentage(item.get("actual_tl", 0.0), item.get("target_tl", 0.0))
                city_name = str(item.get("city", self._STR_UNKNOWN_CITY))
                formatted[city_name] = {
                    "tl": self._safe_round(item.get("actual_tl"), 0),
                    "target": self._safe_round(item.get("target_tl"), 0),
                    "percent": pct,
                    "representative_count": item.get("rep_count", 0),
                    "risk_score": self._calc_risk_score(pct),
                    "opportunity_score": self._calc_opportunity_score(pct)
                }
            return {DashboardConstants.KEY_CITY_PERFORMANCE: formatted}
        except Exception as e:
            self._log_formatting_error("format_city_performance", e)
            return {DashboardConstants.KEY_CITY_PERFORMANCE: {}}

    def format_market_trend(self, dtos: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Resolves generic constant month names and structures for charting arrays."""
        try:
            if not dtos: 
                return {"market_share_trend": {"labels": [], "values": []}}
                
            labels, values = [], []
            for item in dtos:
                month_val = item.get("month", 1)
                name = self._resolve_month_label(month_val)
                labels.append(f"{name} {item.get('year', 0)}")
                values.append(self._safe_round(item.get("avg_share"), 2))
                
            return {"market_share_trend": {"labels": labels, "values": values}}
        except Exception as e:
            self._log_formatting_error("format_market_trend", e)
            return {"market_share_trend": {"labels": [], "values": []}}

    def format_history(self, dtos: Optional[List[Dict[str, Any]]], prime_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculates growth trends, merges engine history and resolves trend constants."""
        try:
            history_list, avg_prime, growth = self._aggregate_history_metrics(dtos or [], prime_data or {})
            trend = self._resolve_trend(growth)
            highest_realization = max([h["bonus"] for h in history_list]) if history_list else 0.0

            return {
                "simulation_history": history_list,
                "history_count": len(history_list),
                "monthly_average": avg_prime,
                "prime_growth": growth,
                "history_trend": trend,
                "last_successful_simulation": history_list[0] if history_list else None,
                "highest_realization": highest_realization,
                "average_prime": avg_prime
            }
        except Exception as e:
            self._log_formatting_error("format_history", e)
            return {}

    def format_recovery(self, recovery_data: Optional[List[Dict[str, Any]]], ai_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Resolves recovery states, calculates overall risks and limits priority products."""
        try:
            rec_data = recovery_data or []
            critical, risk, warning, healthy = self._aggregate_recovery_stats(rec_data)
            
            total = len(rec_data)
            comp_pct = self._calc_percentage(float(healthy), float(total)) if total else 100.0
            risk_pct = self._calc_percentage(float(critical + risk), float(total)) if total else 0.0
            
            sorted_rec = sorted(rec_data, key=lambda x: self._safe_round(x.get("remaining_tl")), reverse=True)
            priority = sorted_rec[:5]
            
            return {
                "risk_products": risk,
                "critical_products": critical,
                "warning_products": warning,
                "healthy_products": healthy,
                "completion_percent": comp_pct,
                "risk_percent": risk_pct,
                "priority_products": priority,
                DashboardConstants.KEY_RECOVERY: rec_data,
                "summary": self._build_localized_summary(total, critical),
                "ai_recommendation": (ai_data or {}).get("action_recommendations", [])
            }
        except Exception as e:
            self._log_formatting_error("format_recovery", e)
            return {}

    def format_prime_summary(self, prime_data: Optional[Dict[str, Any]], ai_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Consolidates complex PrimeEngine mechanics into a flat presentation dictionary."""
        try:
            p_data = prime_data or {}
            breakdown = p_data.get("breakdown", {})
            
            total_target = self._safe_round(p_data.get("total_target"))
            total_real = self._safe_round(p_data.get("total_realization"))
            pct = self._calc_percentage(total_real, total_target)
            gap = self._safe_round(max(0.0, total_target - total_real), 2)
            
            ai_scores = (ai_data or {}).get("ai_scores", {})
            
            return {
                "main_prime": self._safe_round(breakdown.get("main_prime"), 2),
                "ciro_prime": self._safe_round(breakdown.get("ciro_prime"), 2),
                "recovery_prime": self._safe_round(ai_scores.get("recovery_prime", breakdown.get("recovery")), 2),
                "expected_prime": self._safe_round(ai_scores.get("expected_prime"), 2),
                "maximum_prime": self._safe_round(ai_scores.get("max_prime"), 2),
                "lost_prime": self._safe_round(ai_scores.get("lost_prime"), 2),
                "bonus": self._safe_round(breakdown.get("bonus"), 2),
                "penalty": self._safe_round(breakdown.get("penalty"), 2),
                "quarter_effect": self._safe_round(breakdown.get("quarter_effect"), 2),
                "product_effect": self._safe_round(breakdown.get("product_effect"), 2),
                "total_prime": self._safe_round(breakdown.get("total"), 2),
                "prime_percentage": pct,
                "prime_gap": gap,
                DashboardConstants.KEY_STATUS: p_data.get("status", self._STR_FALLBACK_STATUS),
                DashboardConstants.KEY_SUCCESS: p_data.get("success", False),
                DashboardConstants.KEY_SIMULATION: p_data.get("simulation", False),
                DashboardConstants.KEY_BREAKDOWN: breakdown
            }
        except Exception as e:
            self._log_formatting_error("format_prime_summary", e)
            return {}
