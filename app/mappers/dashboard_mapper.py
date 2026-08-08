"""
V3 Architecture: Dashboard Mapper Layer
=======================================
Repository ve Query Layer'dan gelen ham ORM objelerini ve SQLAlchemy Row nesnelerini
saf Python sözlüklerine (DTO) dönüştürür.
Kesinlikle iş kuralları (business logic), tarih formatlama, sayı yuvarlama içermez.
Tamamen Null-Safe çalışır ve hiçbir zaman exception atmaz.
"""
import logging
from typing import List, Dict, Any, Sequence, Optional, Mapping, Final

logger = logging.getLogger(__name__)


class DashboardMapper:
    """
    Maps raw ORM/SQLAlchemy rows to domain DTOs securely.
    
    Architecture & Capabilities:
    - Stateless & Thread-Safe
    - Memory Optimized (__slots__)
    - Guaranteed Null-Safety
    - Exception Safe & Side-Effect Free Helpers
    - Strict Constant Resolution (Zero Magic Literals)
    """

    __slots__ = ()

    # =========================================================================
    # PRIVATE CONSTANTS (Eliminating Magic Literals)
    # =========================================================================
    _KEY_TOTAL_PRODUCTS: Final[str] = "total_products"
    _KEY_TOTAL_REPS: Final[str] = "total_representatives"
    _KEY_TOTAL_TARGETS: Final[str] = "total_targets"
    _KEY_TOTAL_UPLOADS: Final[str] = "total_uploads"
    _KEY_COMPLETED_UPLOADS: Final[str] = "completed_uploads"
    _KEY_FAILED_UPLOADS: Final[str] = "failed_uploads"
    _KEY_PROC_UPLOADS: Final[str] = "processing_uploads"

    _KEY_UPLOAD_ID: Final[str] = "upload_id"
    _KEY_STATUS: Final[str] = "status"
    _KEY_FILE_NAME: Final[str] = "file_name"
    _KEY_QUARTER: Final[str] = "quarter"
    _KEY_MONTH: Final[str] = "month"
    _KEY_YEAR: Final[str] = "year"
    _KEY_UPLOADED_AT: Final[str] = "uploaded_at"
    _KEY_COMPLETED_AT: Final[str] = "completed_at"
    _KEY_PROC_TIME: Final[str] = "processing_time"
    _KEY_WARN_MSG: Final[str] = "warning_message"
    _KEY_ERR_MSG: Final[str] = "error_message"
    _KEY_SHEET_CNT: Final[str] = "sheet_count"
    _KEY_RAW_REC_CNT: Final[str] = "raw_record_count"
    _KEY_FACT_REC_CNT: Final[str] = "fact_record_count"
    _KEY_SUM_REC_CNT: Final[str] = "summary_record_count"
    
    _KEY_PENDING_MATCH: Final[str] = "pending_match_count"
    _KEY_RESOLVED_MATCH: Final[str] = "resolved_match_count"

    _KEY_REP_NAME: Final[str] = "rep_name"
    _KEY_CITY: Final[str] = "city"
    _KEY_ACTUAL_TL: Final[str] = "actual_tl"
    _KEY_BONUS_AMT: Final[str] = "bonus_amount"
    _KEY_TARGET_TL: Final[str] = "target_tl"
    _KEY_REP_COUNT: Final[str] = "rep_count"
    _KEY_AVG_SHARE: Final[str] = "avg_share"
    _KEY_BONUS: Final[str] = "bonus"

    _KEY_PENDING: Final[str] = "pending"
    _KEY_RES_REPS: Final[str] = "resolved_reps"
    _KEY_RES_PRODS: Final[str] = "resolved_products"

    # =========================================================================
    # PRIVATE HELPERS (Pure & Side-Effect Free)
    # =========================================================================

    def _log_mapping_error(self, method_name: str, error: Exception) -> None:
        """Centralized, lazy-logging helper for mapping exceptions."""
        logger.debug("[Mapper] Error in %s: %s", method_name, error, exc_info=False)

    def _safe_get(self, obj: Any, key_or_index: Any, default: Any = None) -> Any:
        """
        Safely retrieves a value from a Mapping, Sequence, ORM Object or Row.
        Optimized to eliminate bounds checking and AttributeError risks in a single flow.
        """
        if obj is None:
            return default

        # 1. Mapping Access (dict, TypedDict, etc.)
        if isinstance(obj, Mapping):
            val = obj.get(key_or_index)
            return val if val is not None else default

        # 2. Sequence Access (list, tuple, NamedTuple) - Excluding str/bytes
        if isinstance(key_or_index, int) and isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
            try:
                val = obj[key_or_index]
                return val if val is not None else default
            except IndexError:
                return default

        # 3. ORM Object Attribute Access
        if isinstance(key_or_index, str) and hasattr(obj, key_or_index):
            val = getattr(obj, key_or_index)
            return val if val is not None else default

        # 4. Fallback for SQLAlchemy Row or custom indexed objects
        try:
            val = obj[key_or_index]
            return val if val is not None else default
        except (KeyError, IndexError, TypeError):
            return default

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        """Safely casts a value to float. Optimized for inline execution."""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _safe_int(self, val: Any, default: int = 0) -> int:
        """Safely casts a value to int. Optimized for inline execution."""
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _safe_str(self, val: Any, default: str = "") -> str:
        """Safely casts a value to string. Optimized for inline execution."""
        if val is None:
            return default
        return str(val)

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def map_counts(self, counts: Optional[Any]) -> Dict[str, int]:
        """Maps system counts from raw query result safely."""
        try:
            if not counts:
                return {}
            return {
                self._KEY_TOTAL_PRODUCTS: self._safe_int(self._safe_get(counts, self._KEY_TOTAL_PRODUCTS)),
                self._KEY_TOTAL_REPS: self._safe_int(self._safe_get(counts, self._KEY_TOTAL_REPS)),
                self._KEY_TOTAL_TARGETS: self._safe_int(self._safe_get(counts, self._KEY_TOTAL_TARGETS)),
                self._KEY_TOTAL_UPLOADS: self._safe_int(self._safe_get(counts, self._KEY_TOTAL_UPLOADS)),
                self._KEY_COMPLETED_UPLOADS: self._safe_int(self._safe_get(counts, self._KEY_COMPLETED_UPLOADS)),
                self._KEY_FAILED_UPLOADS: self._safe_int(self._safe_get(counts, self._KEY_FAILED_UPLOADS)),
                self._KEY_PROC_UPLOADS: self._safe_int(self._safe_get(counts, self._KEY_PROC_UPLOADS)),
            }
        except Exception as e:
            self._log_mapping_error("map_counts", e)
            return {}

    def map_upload_details(
        self, 
        upload: Optional[Any], 
        match_summary: Optional[Dict[str, int]]
    ) -> Dict[str, Any]:
        """Maps upload ORM object and match counts safely."""
        try:
            ms = match_summary or {}
            pending = self._safe_int(self._safe_get(ms, self._KEY_PENDING))
            res_reps = self._safe_int(self._safe_get(ms, self._KEY_RES_REPS))
            res_prods = self._safe_int(self._safe_get(ms, self._KEY_RES_PRODS))
            
            return {
                self._KEY_UPLOAD_ID: self._safe_get(upload, "id") if upload else None,
                self._KEY_STATUS: self._safe_get(upload, self._KEY_STATUS) if upload else None,
                self._KEY_FILE_NAME: self._safe_get(upload, self._KEY_FILE_NAME) if upload else None,
                self._KEY_QUARTER: self._safe_get(upload, self._KEY_QUARTER) if upload else None,
                self._KEY_MONTH: self._safe_get(upload, self._KEY_MONTH) if upload else None,
                self._KEY_YEAR: self._safe_get(upload, self._KEY_YEAR) if upload else None,
                self._KEY_UPLOADED_AT: self._safe_get(upload, self._KEY_UPLOADED_AT) if upload else None,
                self._KEY_COMPLETED_AT: self._safe_get(upload, self._KEY_COMPLETED_AT) if upload else None,
                self._KEY_PROC_TIME: self._safe_float(self._safe_get(upload, self._KEY_PROC_TIME)) if upload else 0.0,
                self._KEY_WARN_MSG: self._safe_get(upload, self._KEY_WARN_MSG) if upload else None,
                self._KEY_ERR_MSG: self._safe_get(upload, self._KEY_ERR_MSG) if upload else None,
                self._KEY_SHEET_CNT: self._safe_int(self._safe_get(upload, self._KEY_SHEET_CNT)) if upload else 0,
                self._KEY_RAW_REC_CNT: self._safe_int(self._safe_get(upload, self._KEY_RAW_REC_CNT)) if upload else 0,
                self._KEY_FACT_REC_CNT: self._safe_int(self._safe_get(upload, self._KEY_FACT_REC_CNT)) if upload else 0,
                self._KEY_SUM_REC_CNT: self._safe_int(self._safe_get(upload, self._KEY_SUM_REC_CNT)) if upload else 0,
                self._KEY_PENDING_MATCH: pending,
                self._KEY_RESOLVED_MATCH: res_reps + res_prods
            }
        except Exception as e:
            self._log_mapping_error("map_upload_details", e)
            return {}

    def map_top_reps(self, rows: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        """Maps top representative performance raw rows securely."""
        try:
            if not rows:
                return []
            return [{
                self._KEY_REP_NAME: self._safe_str(self._safe_get(row, 1), ""),
                self._KEY_CITY: self._safe_str(self._safe_get(row, 2), "-"),
                self._KEY_ACTUAL_TL: self._safe_float(self._safe_get(row, 3)),
                self._KEY_BONUS_AMT: self._safe_float(self._safe_get(row, 4)),
                self._KEY_TARGET_TL: self._safe_float(self._safe_get(row, 5))
            } for row in rows]
        except Exception as e:
            self._log_mapping_error("map_top_reps", e)
            return []

    def map_city_performance(self, rows: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        """Maps aggregated city performance raw rows securely."""
        try:
            if not rows:
                return []
            return [{
                self._KEY_CITY: self._safe_str(self._safe_get(row, 0), "Unknown"),
                self._KEY_ACTUAL_TL: self._safe_float(self._safe_get(row, 1)),
                self._KEY_TARGET_TL: self._safe_float(self._safe_get(row, 2)),
                self._KEY_REP_COUNT: self._safe_int(self._safe_get(row, 3))
            } for row in rows]
        except Exception as e:
            self._log_mapping_error("map_city_performance", e)
            return []

    def map_market_trend(self, rows: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        """Maps market share trends raw rows securely."""
        try:
            if not rows:
                return []
            return [{
                self._KEY_YEAR: self._safe_int(self._safe_get(row, 0)),
                self._KEY_MONTH: self._safe_int(self._safe_get(row, 1, 1)),
                self._KEY_AVG_SHARE: self._safe_float(self._safe_get(row, 2))
            } for row in rows]
        except Exception as e:
            self._log_mapping_error("map_market_trend", e)
            return []

    def map_history(self, rows: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        """Maps simulation history raw rows securely."""
        try:
            if not rows:
                return []
            return [{
                self._KEY_YEAR: self._safe_int(self._safe_get(row, 0)),
                self._KEY_MONTH: self._safe_int(self._safe_get(row, 1, 1)),
                self._KEY_ACTUAL_TL: self._safe_float(self._safe_get(row, 2)),
                self._KEY_BONUS: self._safe_float(self._safe_get(row, 3))
            } for row in rows]
        except Exception as e:
            self._log_mapping_error("map_history", e)
            return []
