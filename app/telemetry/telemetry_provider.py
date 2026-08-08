"""
V3 Architecture: Telemetry Provider Abstraction
===============================================

Arayüz (Interface) ve varsayılan log tabanlı implementasyon.
İleride OpenTelemetry (OTel) veya Prometheus gibi sistemlere 
kolayca bağlanabilmesi için tasarlanmış izole kancadır (hook).
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Final

# Fallback logger if dependency injection is not utilized
_default_logger = logging.getLogger(__name__)


class TelemetryProvider(ABC):
    """
    Abstract base class for telemetry and metric events.
    
    Defines the structural contract for emitting distributed tracing spans,
    performance metrics, and managing the lifecycle of the underlying exporter.
    """

    @abstractmethod
    def emit_span(
        self,
        trace_id: str,
        span_id: str,
        component: str,
        duration_ms: float,
        status: str,
        tags: Optional[Mapping[str, Any]] = None
    ) -> None:
        """
        Emits a tracing span for distributed tracing capabilities.

        Args:
            trace_id (str): The unique identifier for the entire trace context.
            span_id (str): The unique identifier for this specific operation/span.
            component (str): The logical name of the component being traced.
            duration_ms (float): The execution duration of the span in milliseconds.
            status (str): The execution status (e.g., 'SUCCESS', 'ERROR').
            tags (Optional[Mapping[str, Any]]): Additional contextual metadata.
        """
        pass

    @abstractmethod
    def emit_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Mapping[str, str]] = None
    ) -> None:
        """
        Emits a performance, counter, or gauge metric to the observability stack.

        Args:
            metric_name (str): The unique name of the metric.
            value (float): The quantitative value of the metric.
            tags (Optional[Mapping[str, str]]): Additional labels for metric slicing.
        """
        pass

    @abstractmethod
    def flush(self) -> None:
        """
        Force flushes any buffered telemetry data to the underlying exporter.
        Used primarily during graceful shutdowns.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Cleanly shuts down the telemetry provider and releases associated resources.
        """
        pass


class LoggerTelemetryProvider(TelemetryProvider):
    """
    Default telemetry implementation routing events to structured application logs.
    
    Architecture & Capabilities:
    - Thread Safe
    - Exception Safe
    - Stateless
    - Dependency Injection Ready
    - OpenTelemetry Ready
    - Future Extensible
    
    Provides protected lifecycle hooks for future exporter extensibility.
    Uses strict slots and lazily evaluated timestamps/dictionaries for high performance.
    """

    # Magic string prevention for logging templates
    SPAN_MESSAGE_TEMPLATE: Final[str] = "[Telemetry] Span Emitted: {component}"
    METRIC_MESSAGE_TEMPLATE: Final[str] = "[Metric] {metric_name} = {value}"

    # Prevents runtime attribute assignment and reduces memory footprint
    __slots__ = (
        "_logger",
        "_enabled",
        "_component_name",
        "_log_level",
    )

    def __init__(
        self,
        logger_instance: Optional[logging.Logger] = None,
        enabled: bool = True,
        component_name: str = "Dashboard",
        log_level: int = logging.DEBUG
    ) -> None:
        """
        Initializes the LoggerTelemetryProvider.

        Args:
            logger_instance (Optional[logging.Logger]): Custom logger for dependency injection.
            enabled (bool): Global toggle to completely disable telemetry emissions.
            component_name (str): Logical identifier for the reporting component.
            log_level (int): Target log severity level (default: logging.DEBUG).
        """
        self._logger = logger_instance or _default_logger
        self._enabled = enabled
        self._component_name = component_name
        self._log_level = log_level

    # =========================================================================
    # READ-ONLY PROPERTIES
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Returns the global telemetry enablement status."""
        return self._enabled

    @property
    def component_name(self) -> str:
        """Returns the logical name of the reporting component."""
        return self._component_name

    @property
    def log_level(self) -> int:
        """Returns the targeted log severity level."""
        return self._log_level

    @property
    def logger(self) -> logging.Logger:
        """Returns the injected logger instance."""
        return self._logger

    # =========================================================================
    # EXTENSIBILITY HOOKS (For Future OpenTelemetry Integration)
    # =========================================================================

    def _before_emit_span(
        self,
        trace_id: str,
        span_id: str,
        component: str,
        duration_ms: float,
        status: str,
        tags: Optional[Mapping[str, Any]]
    ) -> None:
        """Hook executed immediately before a span is emitted."""
        pass

    def _after_emit_span(
        self,
        trace_id: str,
        span_id: str,
        component: str,
        duration_ms: float,
        status: str,
        tags: Optional[Mapping[str, Any]]
    ) -> None:
        """Hook executed immediately after a span is emitted successfully."""
        pass

    def _before_emit_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Mapping[str, str]]
    ) -> None:
        """Hook executed immediately before a metric is emitted."""
        pass

    def _after_emit_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Mapping[str, str]]
    ) -> None:
        """Hook executed immediately after a metric is emitted successfully."""
        pass

    def _before_flush(self) -> None:
        """Hook executed immediately before a flush operation."""
        pass

    def _after_flush(self) -> None:
        """Hook executed immediately after a flush operation."""
        pass

    def _before_shutdown(self) -> None:
        """Hook executed immediately before a shutdown operation."""
        pass

    def _after_shutdown(self) -> None:
        """Hook executed immediately after a shutdown operation."""
        pass

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _get_timestamp(self) -> str:
        """Generates an ISO8601 UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def _log(self, message: str, extra_data: Dict[str, Any]) -> None:
        """Executes the logging output."""
        self._logger.log(self._log_level, message, extra=extra_data)

    def _build_span_extra(
        self,
        trace_id: str,
        span_id: str,
        component: str,
        duration_ms: float,
        status: str,
        tags: Optional[Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """Safely constructs the dictionary for span payload."""
        if tags:
            extra_data: Dict[str, Any] = tags.copy() if hasattr(tags, "copy") else dict(tags)
        else:
            extra_data = {}

        extra_data["timestamp"] = self._get_timestamp()
        extra_data["trace_id"] = trace_id
        extra_data["span_id"] = span_id
        extra_data["component"] = component
        extra_data["duration_ms"] = round(duration_ms, 2)
        extra_data["status"] = status
        extra_data["provider_component"] = self._component_name

        return extra_data

    def _build_metric_extra(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Mapping[str, str]]
    ) -> Dict[str, Any]:
        """Safely constructs the dictionary for metric payload."""
        if tags:
            extra_data: Dict[str, Any] = tags.copy() if hasattr(tags, "copy") else dict(tags)
        else:
            extra_data = {}

        extra_data["timestamp"] = self._get_timestamp()
        extra_data["metric_name"] = metric_name
        extra_data["value"] = value
        extra_data["provider_component"] = self._component_name

        return extra_data

    # =========================================================================
    # IMPLEMENTATION OF ABSTRACT METHODS
    # =========================================================================

    def emit_span(
        self,
        trace_id: str,
        span_id: str,
        component: str,
        duration_ms: float,
        status: str,
        tags: Optional[Mapping[str, Any]] = None
    ) -> None:
        """
        Safely builds and emits a structured log representing a trace span.
        """
        if not self._enabled:
            return

        try:
            self._before_emit_span(trace_id, span_id, component, duration_ms, status, tags)

            # Performance Optimization: Prevent allocation overhead if log level is disabled
            if self._logger.isEnabledFor(self._log_level):
                extra_data = self._build_span_extra(trace_id, span_id, component, duration_ms, status, tags)
                message = self.SPAN_MESSAGE_TEMPLATE.format(component=component)
                self._log(message, extra_data)

            self._after_emit_span(trace_id, span_id, component, duration_ms, status, tags)

        except Exception:
            # Exception Safety: Telemetry failures must never disrupt the application flow
            pass

    def emit_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Mapping[str, str]] = None
    ) -> None:
        """
        Safely builds and emits a structured log representing a system metric.
        """
        if not self._enabled:
            return

        try:
            self._before_emit_metric(metric_name, value, tags)

            # Performance Optimization: Prevent allocation overhead if log level is disabled
            if self._logger.isEnabledFor(self._log_level):
                extra_data = self._build_metric_extra(metric_name, value, tags)
                message = self.METRIC_MESSAGE_TEMPLATE.format(metric_name=metric_name, value=value)
                self._log(message, extra_data)

            self._after_emit_metric(metric_name, value, tags)

        except Exception:
            # Exception Safety: Telemetry failures must never disrupt the application flow
            pass

    def flush(self) -> None:
        """
        Flushes telemetry buffers securely. 
        """
        if not self._enabled:
            return

        try:
            self._before_flush()
            # Standard logging handles its own buffering natively.
            # This is intentionally open for exporters overriding flush logic.
            self._after_flush()
        except Exception:
            pass

    def shutdown(self) -> None:
        """
        Shuts down the provider securely.
        """
        if not self._enabled:
            return

        try:
            self._before_shutdown()
            # Standard logging handles its own shutdown natively.
            # Intentionally open for background task termination in future OTEL implementations.
            self._after_shutdown()
        except Exception:
            pass
