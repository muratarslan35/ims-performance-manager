"""
V3 Architecture: Dashboard Engine Factory
=========================================
Domain Engine'lerin (Prime, Quarter, Recovery, AI) kontrollü şekilde üretilmesi
için Factory katmanı. Service'i somut sınıf bağımlılığından (DIP) kurtarır.
"""
from typing import Dict, Any, Optional

from app.constants.dashboard_constants import DashboardConstants
from app.services.prime_engine import PrimeEngine
from app.services.ai_analytics_service import AIAnalyticsService

try:
    from app.services.quarter_engine import QuarterEngine
    from app.services.recovery_engine import RecoveryEngine
except ImportError:
    QuarterEngine = RecoveryEngine = None  # type: ignore


class DashboardEngineFactory:
    """
    Factory responsible for instantiating heavy calculation engines safely.
    
    Architecture & Capabilities:
    - Stateless
    - Dependency Injection Ready
    - SOLID Compliant
    - Open Closed Principle
    - Future Extensible
    - Thread Safe
    """

    __slots__ = ()

    VERSION = "3.2.0"
    FACTORY_NAME = "DashboardEngineFactory"
    
    ENGINE_PRIME = "PrimeEngine"
    ENGINE_QUARTER = "QuarterEngine"
    ENGINE_RECOVERY = "RecoveryEngine"
    ENGINE_AI = "AIAnalyticsService"

    # =========================================================================
    # READ-ONLY PROPERTIES
    # =========================================================================

    @property
    def version(self) -> str:
        """Returns the current factory API version."""
        return self.VERSION

    @property
    def supports_optional_engines(self) -> bool:
        """Indicates if the factory gracefully handles missing engine dependencies."""
        return True

    @property
    def supports_dependency_injection(self) -> bool:
        """Indicates if the factory supports usage in DI containers."""
        return True

    @property
    def stateless(self) -> bool:
        """Indicates that the factory maintains no internal state."""
        return True

    # =========================================================================
    # HOOKS (FUTURE EXTENSIBILITY)
    # =========================================================================

    def _before_create(self, engine_name: str) -> None:
        """Hook executed immediately before any engine is instantiated."""
        pass

    def _after_create(self, engine_name: str) -> None:
        """Hook executed immediately after any engine is instantiated."""
        pass

    def _on_optional_engine_missing(self, engine_name: str) -> None:
        """Hook executed when an optional engine (Quarter/Recovery) is unavailable."""
        pass

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _normalize_overrides(self, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Safely normalizes the overrides dictionary, ensuring it never returns None.
        """
        return overrides or {}

    def _create_prime(self, rep_id: int, year: int, month: int, overrides: Dict[str, Any]) -> PrimeEngine:
        """Internal physical creation logic for PrimeEngine."""
        return PrimeEngine(
            representative_id=rep_id, 
            year=year, 
            month=month, 
            overrides=overrides, 
            use_cache=True
        )

    def _create_quarter(self, rep_id: int, year: int, quarter: int, month: int, overrides: Dict[str, Any]) -> Optional[Any]:
        """Internal physical creation logic for QuarterEngine."""
        if not QuarterEngine:
            self._on_optional_engine_missing(self.ENGINE_QUARTER)
            return None
            
        return QuarterEngine(
            representative_id=rep_id, 
            year=year, 
            quarter=quarter, 
            month=month, 
            overrides=overrides
        )

    def _create_recovery(self, rep_id: int, year: int, quarter: int, month: int, overrides: Dict[str, Any]) -> Optional[Any]:
        """Internal physical creation logic for RecoveryEngine."""
        if not RecoveryEngine:
            self._on_optional_engine_missing(self.ENGINE_RECOVERY)
            return None
            
        return RecoveryEngine(
            representative_id=rep_id, 
            year=year, 
            quarter=quarter, 
            month=month, 
            overrides=overrides
        )

    def _create_ai(self) -> AIAnalyticsService:
        """Internal physical creation logic for AIAnalyticsService."""
        return AIAnalyticsService()

    # =========================================================================
    # PUBLIC API (ORCHESTRATION)
    # =========================================================================

    def create_prime_engine(
        self, 
        rep_id: int, 
        year: int, 
        month: int, 
        overrides: Optional[Dict[str, Any]] = None
    ) -> PrimeEngine:
        """
        Instantiates and configures a new PrimeEngine.

        Args:
            rep_id (int): Representative ID for context resolution.
            year (int): Target year for calculations.
            month (int): Target month for calculations.
            overrides (Optional[Dict[str, Any]]): What-if simulation parameters.

        Returns:
            PrimeEngine: Fully constructed and configured engine instance.
        """
        self._before_create(self.ENGINE_PRIME)
        safe_overrides = self._normalize_overrides(overrides)
        engine = self._create_prime(rep_id, year, month, safe_overrides)
        self._after_create(self.ENGINE_PRIME)
        return engine
        
    def create_quarter_engine(
        self, 
        rep_id: int, 
        year: int, 
        quarter: int, 
        month: int, 
        overrides: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Instantiates and configures a new QuarterEngine, if the module is available.

        Args:
            rep_id (int): Representative ID for context resolution.
            year (int): Target year for calculations.
            quarter (int): Target quarter (1-4).
            month (int): Target month for period alignment.
            overrides (Optional[Dict[str, Any]]): What-if simulation parameters.

        Returns:
            Optional[Any]: Constructed QuarterEngine instance, or None if the dependency is missing.
        """
        self._before_create(self.ENGINE_QUARTER)
        safe_overrides = self._normalize_overrides(overrides)
        engine = self._create_quarter(rep_id, year, quarter, month, safe_overrides)
        self._after_create(self.ENGINE_QUARTER)
        return engine
        
    def create_recovery_engine(
        self, 
        rep_id: int, 
        year: int, 
        quarter: int, 
        month: int, 
        overrides: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Instantiates and configures a new RecoveryEngine, if the module is available.

        Args:
            rep_id (int): Representative ID for context resolution.
            year (int): Target year for calculations.
            quarter (int): Target quarter (1-4).
            month (int): Target month for period alignment.
            overrides (Optional[Dict[str, Any]]): What-if simulation parameters.

        Returns:
            Optional[Any]: Constructed RecoveryEngine instance, or None if the dependency is missing.
        """
        self._before_create(self.ENGINE_RECOVERY)
        safe_overrides = self._normalize_overrides(overrides)
        engine = self._create_recovery(rep_id, year, quarter, month, safe_overrides)
        self._after_create(self.ENGINE_RECOVERY)
        return engine
        
    def create_ai_service(self) -> AIAnalyticsService:
        """
        Instantiates a new AIAnalyticsService.

        Returns:
            AIAnalyticsService: Constructed service ready for analysis execution.
        """
        self._before_create(self.ENGINE_AI)
        service = self._create_ai()
        self._after_create(self.ENGINE_AI)
        return service

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    def health(self) -> Dict[str, Any]:
        """
        Returns the structural availability and operational health of the factory.
        
        Returns:
            Dict[str, Any]: Dictionary containing presence flags for domain engines.
        """
        return {
            "factory": self.FACTORY_NAME,
            "status": DashboardConstants.STATUS_READY,
            "version": self.version,
            "stateless": self.stateless,
            "prime_available": True,
            "quarter_available": QuarterEngine is not None,
            "recovery_available": RecoveryEngine is not None,
            "ai_available": True
                        }
