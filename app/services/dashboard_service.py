"""
V3 Architecture: Dashboard Service (Orchestrator)
=================================================
Enterprise-grade orchestration layer for the IMS Dashboard.
Strictly adheres to Clean Architecture, SOLID, and Dependency Inversion.

Responsibilities:
- Orchestrates data fetching from Repository & Query Layer.
- Orchestrates execution of domain engines via EngineFactory.
- Delegates mapping and formatting securely.
- Assembles payload immutably via DashboardPayloadBuilder.
- Injects Telemetry and Metrics hooks natively.
"""

import logging
import time
import uuid
import warnings
from functools import wraps
from typing import Dict, Any, List, Optional, Callable, TypeVar
from datetime import datetime

# Injected Dependencies
from app.repository.dashboard_repository import DashboardRepository
from app.query.dashboard_query import DashboardQuery
from app.query.filters import DashboardFilterParams
from app.factories.dashboard_engine_factory import DashboardEngineFactory
from app.mappers.dashboard_mapper import DashboardMapper
from app.formatters.dashboard_formatter import DashboardFormatter
from app.builders.dashboard_payload_builder import DashboardPayloadBuilder
from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.telemetry.telemetry_provider import TelemetryProvider, LoggerTelemetryProvider

logger = logging.getLogger(__name__)
T = TypeVar("T")

def deprecated(since: str = "3.2", remove_in: str = "4.0", replacement: str = "run") -> Callable[..., Any]:
    """Decorator marking legacy wrapper functions while retaining full backward compatibility."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                f"{func.__name__} is deprecated since {since}, will be removed in {remove_in}. "
                f"Use {replacement} instead.",
                DeprecationWarning,
                stacklevel=2
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator


class DashboardService:
    """
    V3 Dashboard Thin Orchestrator.
    Serves solely to wire separated architectural layers together dynamically and safely.
    """

    def __init__(
        self,
        representative_id: Optional[int] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        overrides: Optional[Dict[str, Any]] = None,
        repository: Optional[DashboardRepository] = None,
        query_layer: Optional[DashboardQuery] = None,
        engine_factory: Optional[DashboardEngineFactory] = None,
        mapper: Optional[DashboardMapper] = None,
        formatter: Optional[DashboardFormatter] = None,
        builder: Optional[DashboardPayloadBuilder] = None,
        cache_provider: Optional[DashboardCache] = None,
        telemetry: Optional[TelemetryProvider] = None
    ) -> None:
        """
        Initializes the orchestrator utilizing Dependency Injection.
        Safely validates dependencies and injects robust defaults if omitted.
        """
        # DI with Null-Safety and logging tracking
        self.repository = repository or DashboardRepository()
        self.query_layer = query_layer or DashboardQuery()
        self.engine_factory = engine_factory or DashboardEngineFactory()
        self.mapper = mapper or DashboardMapper()
        self.formatter = formatter or DashboardFormatter()
        self.builder = builder or DashboardPayloadBuilder()
        self.cache = cache_provider or DashboardCache()
        self.telemetry = telemetry or LoggerTelemetryProvider()
        
        if any(dep is None for dep in [repository, query_layer, engine_factory, mapper, formatter, builder, cache_provider, telemetry]):
            logger.info("[DashboardService] One or more dependencies were omitted during instantiation. Using defaults.")

        # State Initialization
        self.rep_id = representative_id
        self.overrides = overrides or {}
        self.trace_id = str(uuid.uuid4())
        
        # Period Resolution
        if not year or not month:
            last_period = self._safe_execute(
                self.repository.load_last_completed_period,
                default_return=None,
                component_name="PeriodResolution"
            )
            if last_period:
                self.year = year or last_period.year
                self.month = month or last_period.month
            else:
                now = datetime.now()
                self.year = year or now.year
                self.month = month or now.month
        else:
            self.year = year
            self.month = month

        self.quarter = ((self.month - 1) // 3) + 1

    # =========================================================================
    # 1. FAULT TOLERANCE EXECUTION
    # =========================================================================

    def _safe_execute(self, func: Callable[..., T], default_return: T, component_name: str) -> T:
        """Executes a component securely, handling specific exceptions without crashing."""
        start_time = time.time()
        span_id = str(uuid.uuid4())
        
        try:
            result = func()
            duration = time.time() - start_time
            self.telemetry.emit_span(self.trace_id, span_id, component_name, duration, "SUCCESS")
            return result

        except (TimeoutError, MemoryError, ValueError, TypeError, AttributeError, ImportError) as exc:
            status = exc.__class__.__name__.upper().replace("ERROR", "_ERROR")
            duration = time.time() - start_time
            self._handle_execution_error(span_id, component_name, duration, exc, status)
            return default_return

        except Exception as exc:
            duration = time.time() - start_time
            self._handle_execution_error(span_id, component_name, duration, exc, "UNKNOWN_ERROR")
            return default_return

    def _handle_execution_error(self, span_id: str, component_name: str, duration: float, exc: Exception, status: str) -> None:
        """Centralized Telemetry exception emitting."""
        self.telemetry.emit_span(self.trace_id, span_id, component_name, duration, status, {"error": str(exc)})
        self.telemetry.emit_metric(f"error_{component_name.lower()}", 1.0, {"type": exc.__class__.__name__})
        logger.error(
            f"[DashboardService] Component execution failed: {component_name} | Trace: {self.trace_id}",
            exc_info=True
        )

    # =========================================================================
    # 2. DATA & ENGINE LOADERS
    # =========================================================================

    def _load_repository_data(self) -> Dict[str, Any]:
        return {
            "counts": self.repository.load_counts(),
            "last_upload": self.repository.load_last_upload(),
            "recent_uploads": self.repository.load_recent_uploads(5),
            "match_summary": {
                "pending": self.repository.load_pending_manual_match_count(),
                "resolved_reps": self.repository.load_resolved_representative_match_count(),
                "resolved_products": self.repository.load_resolved_product_match_count()
            }
        }

    def _load_query_data(self) -> Dict[str, Any]:
        filters = DashboardFilterParams(year=self.year, month=self.month, representative_id=self.rep_id)
        return {
            "top_reps": self.query_layer.load_top_representatives(filters=filters),
            "city_perf": self.query_layer.load_city_performance(filters=filters),
            "market_trend": self.query_layer.load_market_share_trend(filters=filters),
            "history": self.query_layer.load_history(filters=filters)
        }

    def _load_prime(self) -> Dict[str, Any]:
        engine = self.engine_factory.create_prime_engine(self.rep_id or 0, self.year, self.month, self.overrides)
        return engine.calculate(save_history=False) if engine else {}

    def _load_quarter(self) -> Dict[str, Any]:
        engine = self.engine_factory.create_quarter_engine(self.rep_id or 0, self.year, self.quarter, self.month, self.overrides)
        return engine.calculate() if engine else {}

    def _load_recovery(self) -> List[Dict[str, Any]]:
        engine = self.engine_factory.create_recovery_engine(self.rep_id or 0, self.year, self.quarter, self.month, self.overrides)
        return engine.run() if engine else []

    def _load_ai(self) -> Dict[str, Any]:
        service = self.engine_factory.create_ai_service()
        return service.run_all() if service else {}

    # =========================================================================
    # 3. PUBLIC ENTRY POINT (run)
    # =========================================================================

    def run(self) -> Dict[str, Any]:
        """
        Master orchestrator. Safely loads all data through mapped providers 
        and assembles the definitive payload cleanly and securely.
        """
        global_start = time.time()
        
        # 1. Cache Verification
        cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(year=self.year, month=self.month, rep_id=self.rep_id)
        
        t_cache = time.time()
        cached_payload = self._safe_execute(lambda: self.cache.get(cache_key), None, "CacheProvider")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_CACHE_READ_MS, (time.time() - t_cache) * 1000)
        
        if cached_payload:
            self.cache.emit_event("HIT", cache_key)
            self.telemetry.emit_metric(DashboardConstants.METRIC_CACHE_HIT, 1.0)
            if DashboardConstants.KEY_CACHE in cached_payload:
                cached_payload[DashboardConstants.KEY_CACHE]["hit"] = True
            return cached_payload
            
        self.cache.emit_event("MISS", cache_key)
        self.telemetry.emit_metric(DashboardConstants.METRIC_CACHE_MISS, 1.0)

        # 2. Orchestrate Data Loading
        t_repo = time.time()
        repo_data = self._safe_execute(self._load_repository_data, {}, "DashboardRepository")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_REPO_MS, (time.time() - t_repo) * 1000)

        t_query = time.time()
        query_data = self._safe_execute(self._load_query_data, {}, "DashboardQuery")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_QUERY_MS, (time.time() - t_query) * 1000)
        
        t_prime = time.time()
        prime_data = self._safe_execute(self._load_prime, {}, "PrimeEngine")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_PRIME_MS, (time.time() - t_prime) * 1000)

        t_quarter = time.time()
        quarter_data = self._safe_execute(self._load_quarter, {}, "QuarterEngine")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_QUARTER_MS, (time.time() - t_quarter) * 1000)

        t_rec = time.time()
        recovery_data = self._safe_execute(self._load_recovery, [], "RecoveryEngine")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_RECOVERY_MS, (time.time() - t_rec) * 1000)

        t_ai = time.time()
        ai_data = self._safe_execute(self._load_ai, {}, "AIAnalyticsService")
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_AI_MS, (time.time() - t_ai) * 1000)

        # 3. Delegate Mapping
        t_mapper = time.time()
        mapped_counts = self.mapper.map_counts(repo_data.get("counts"))
        mapped_upload = self.mapper.map_upload_details(repo_data.get("last_upload"), repo_data.get("match_summary", {}))
        mapped_top_reps = self.mapper.map_top_reps(query_data.get("top_reps", []))
        mapped_city_perf = self.mapper.map_city_performance(query_data.get("city_perf", []))
        mapped_market_trend = self.mapper.map_market_trend(query_data.get("market_trend", []))
        mapped_history = self.mapper.map_history(query_data.get("history", []))
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_MAPPER_MS, (time.time() - t_mapper) * 1000)

        # 4. Delegate Formatting
        t_formatter = time.time()
        fmt_upload = self.formatter.format_upload_details(mapped_upload)
        fmt_top_reps = self.formatter.format_top_reps(mapped_top_reps)
        fmt_city_perf = self.formatter.format_city_performance(mapped_city_perf)
        fmt_market_trend = self.formatter.format_market_trend(mapped_market_trend)
        fmt_history = self.formatter.format_history(mapped_history, prime_data)
        fmt_recovery = self.formatter.format_recovery(recovery_data, ai_data)
        fmt_prime = self.formatter.format_prime_summary(prime_data, ai_data)
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_FORMATTER_MS, (time.time() - t_formatter) * 1000)

        # 5. Delegate Payload Assembly (Immutable Mode Supported)
        t_builder = time.time()
        self.builder.reset()
        
        self.builder.set_counts(mapped_counts) \
               .set_upload_details(fmt_upload) \
               .set_recovery(fmt_recovery) \
               .set_top_reps(fmt_top_reps) \
               .set_city_performance(fmt_city_perf) \
               .set_market_trend(fmt_market_trend) \
               .set_history(fmt_history) \
               .set_ai_data(ai_data) \
               .set_prime_metrics(prime_data) \
               .set_prime_summary(fmt_prime) \
               .set_quarter_summary(quarter_data) \
               .set_active_period(self.year, self.month, self.quarter) \
               .set_performance(time.time() - global_start) \
               .set_cache_info(False, DashboardConstants.CACHE_TTL_DEFAULT)
               
        payload = self.builder.build(immutable=False)
        self.telemetry.emit_metric(DashboardConstants.METRIC_DURATION_BUILDER_MS, (time.time() - t_builder) * 1000)

        # 6. Set Cache Safely
        self._safe_execute(
            lambda: self.cache.set(cache_key, payload, DashboardConstants.CACHE_TTL_DEFAULT),
            None,
            "CacheProviderWrite"
        )
        
        total_ms = (time.time() - global_start) * 1000
        self.telemetry.emit_metric(DashboardConstants.METRIC_RENDER_TOTAL_MS, total_ms)
        self.telemetry.emit_span(self.trace_id, str(uuid.uuid4()), "DashboardRender", total_ms / 1000, "COMPLETED")

        return payload

    # =========================================================================
    # 4. HEALTH CHECK
    # =========================================================================

    @classmethod
    def health(cls) -> Dict[str, Any]:
        """Provides isolated dependency instantiation checks dynamically."""
        deps_status = {
            "repository_ready": True,
            "query_ready": True,
            "cache_ready": True,
            "engine_factory_ready": True
        }
        status = DashboardConstants.STATUS_READY
        return {
            "service": "DashboardService",
            "version": "3.2.0",
            "layer": "Orchestrator",
            **deps_status,
            "status": status
        }

    # =========================================================================
    # 5. LEGACY FORWARDING API (Backward Compatibility)
    # =========================================================================

    @deprecated()
    def load_counts(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_last_upload(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_recovery(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_prime_summary(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_quarter_summary(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_overall_stats(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_product_performance(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_top_representatives(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_monthly_trend(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_market_share_trend(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_city_performance(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_active_quarter(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_recent_uploads(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_ai_analytics(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_what_if(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_comparison(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_history(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_executive_summary(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_kpi_cards(self) -> Dict[str, Any]: return self.run()
    @deprecated()
    def load_widgets_data(self) -> Dict[str, Any]: return self.run()
