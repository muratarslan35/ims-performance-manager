"""
V3 Architecture: Dashboard Constants
====================================
Merkezi sabit (magic string) tanımlamaları ve metrik anahtarları.
Type-safe (Final) and immutable definitions.
"""

from typing import Any, Final, Tuple


class DashboardConstants:
    """
    DO NOT INSTANTIATE
    
    Only immutable application constants.
    
    DashboardService ve ilgili katmanlar için merkezi sabitlerin tutulduğu sınıf.
    Sadece salt okunur özellik taşır ve çalışma zamanında değiştirilemez.
    """
    
    # Runtime özellik eklenmesini engeller.
    __slots__ = ()

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        # Sınıfın instance (örnek) haline getirilmesini kesinlikle engeller.
        raise TypeError(f"{cls.__name__} static bir sınıftır ve örneklenemez (instantiate edilemez).")

    # ==================================================
    # 1. Service Metadata
    # ==================================================
    SERVICE_NAME: Final[str] = "DashboardService"
    SERVICE_VERSION: Final[str] = "3.2.0"
    ORCHESTRATOR_LAYER: Final[str] = "Orchestrator"

    # End of Service Metadata


    # ==================================================
    # 2. Time Constants
    # ==================================================
    SECONDS_PER_MINUTE: Final[int] = 60
    SECONDS_PER_HOUR: Final[int] = 3600
    DEFAULT_TIMEOUT_SECONDS: Final[int] = 30

    # End of Time Constants


    # ==================================================
    # 3. Status Constants
    # ==================================================
    # Bu statüler Orchestrator (DashboardService), Query Layer, Repository,
    # Domain Engine'ler ve Frontend Payload mapping katmanları tarafından
    # operasyonel veya iş mantığı durumlarını belirtmek için ortaklaşa kullanılır.
    STATUS_READY: Final[str] = "READY"
    STATUS_WARNING: Final[str] = "WARNING"
    STATUS_ERROR: Final[str] = "ERROR"
    STATUS_COMPLETED: Final[str] = "COMPLETED"
    STATUS_FAILED: Final[str] = "FAILED"
    STATUS_PROCESSING: Final[str] = "PROCESSING"
    STATUS_INITIALIZING: Final[str] = "INITIALIZING"
    STATUS_DEGRADED: Final[str] = "DEGRADED"
    STATUS_UNKNOWN: Final[str] = "UNKNOWN"

    # End of Status Constants


    # ==================================================
    # 4. Health Constants
    # ==================================================
    # Kubernetes / Docker ortamlarındaki REST Health Endpoint,
    # Readiness Probe ve Liveness Probe kontrollerinde kullanılacak durum bildirimleri.
    HEALTH_OK: Final[str] = "OK"
    HEALTH_WARNING: Final[str] = "WARNING"
    HEALTH_DEGRADED: Final[str] = "DEGRADED"
    HEALTH_FAILED: Final[str] = "FAILED"
    
    # End of Health Constants


    # ==================================================
    # 5. Settings
    # ==================================================
    SETTING_DASHBOARD_VERSION: Final[str] = "DASHBOARD_VERSION"
    SETTING_COMPANY_NAME: Final[str] = "COMPANY_NAME"
    SETTING_MAIN_PRIME: Final[str] = "MAIN_PRIME"
    SETTING_CIRO_PRIME: Final[str] = "CIRO_PRIME"
    
    # End of Settings


    # ==================================================
    # 6. Payload Keys
    # ==================================================
    KEY_STATUS: Final[str] = "status"
    KEY_CACHE: Final[str] = "cache"
    KEY_PERFORMANCE: Final[str] = "performance"
    KEY_SUCCESS: Final[str] = "success"
    KEY_SIMULATION: Final[str] = "simulation"
    KEY_ACTIVE_PERIOD: Final[str] = "active_period"
    KEY_PRODUCTS: Final[str] = "products"
    KEY_TOP_REPRESENTATIVES: Final[str] = "top_representatives"
    KEY_CITY_PERFORMANCE: Final[str] = "city_performance"
    KEY_HISTORY: Final[str] = "history"
    KEY_UPLOAD_DETAILS: Final[str] = "upload_details"
    KEY_PRIME_SUMMARY: Final[str] = "prime_summary"
    KEY_AI_ANALYTICS: Final[str] = "ai_analytics"
    KEY_RECOVERY: Final[str] = "recovery"
    KEY_QUARTER: Final[str] = "quarter"
    KEY_BREAKDOWN: Final[str] = "breakdown"
    KEY_TREND: Final[str] = "trend"
    KEY_WIDGETS: Final[str] = "widgets"
    KEY_METADATA: Final[str] = "metadata"

    # End of Payload Keys


    # ==================================================
    # 7. Localization
    # ==================================================
    # Bu alan, ileride eklenecek olan i18n (Uluslararasılaştırma / Çoklu Dil)
    # desteği için temel varsayılan değerleri belirler.
    
    # Varsayılan dil ayarı (Örn: UI metinleri ve çeviriler için)
    DEFAULT_LANGUAGE: Final[str] = "tr"
    # Varsayılan bölge ayarı (Örn: Sayı, para birimi ve format işlemleri için)
    DEFAULT_LOCALE: Final[str] = "tr_TR"
    # Varsayılan zaman dilimi (Örn: Timestamp tarih çevirileri için)
    DEFAULT_TIMEZONE: Final[str] = "Europe/Istanbul"
    # Sistem geneli karakter kodlaması (Örn: Dosya okuma/yazma)
    DEFAULT_ENCODING: Final[str] = "UTF-8"

    MONTH_NAMES: Final[Tuple[str, ...]] = (
        "Oca", "Şub", "Mar", "Nis", "May", "Haz", 
        "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"
    )
    
    TREND_UP: Final[str] = "artış"
    TREND_DOWN: Final[str] = "azalış"
    TREND_STABLE: Final[str] = "stabil"

    # End of Localization


    # ==================================================
    # 8. Cache
    # ==================================================
    CACHE_PREFIX: Final[str] = "dashboard:v3"
    CACHE_NAMESPACE: Final[str] = "ims"
    
    # CACHE_VERSION, önbellekte tutulan payload'ın veri yapısı sürümünü belirler.
    # SERVICE_VERSION (Dashboard API sürümü) ile farklı amaçlar taşır. Payload değiştiğinde güncellenir.
    CACHE_VERSION: Final[str] = "v3"
    
    # Cache Key Templates
    # DashboardService tarafından kullanılan birincil payload veri modeli cache anahtarı.
    CACHE_KEY_TEMPLATE: Final[str] = f"{CACHE_PREFIX}:{{year}}:{{month}}:rep_{{rep_id}}"
    
    # Health kontrol endpointi için kullanılan kısa ömürlü cache anahtarı.
    CACHE_KEY_HEALTH: Final[str] = f"{CACHE_PREFIX}:health"
    
    # DashboardQuery katmanından gelen karmaşık analitik (OLAP) sorgu sonuçları anahtarı.
    CACHE_KEY_QUERY: Final[str] = f"{CACHE_PREFIX}:query:{{query_name}}"
    
    # DashboardRepository katmanından okunan salt veritabanı okuma işlemlerinin anahtarı.
    CACHE_KEY_REPOSITORY: Final[str] = f"{CACHE_PREFIX}:repository:{{method_name}}"
    
    # PrimeEngine'in yoğun kaynak tüketen operasyonlarının ara ve nihai çıktılarının anahtarı.
    CACHE_KEY_PRIME: Final[str] = f"{CACHE_PREFIX}:prime:{{year}}:{{month}}:rep_{{rep_id}}"
    
    # Yüklenen (upload) IMS verisine ilişkin statik, denetim veya analiz verilerinin anahtarı.
    CACHE_KEY_UPLOAD: Final[str] = f"{CACHE_PREFIX}:upload:{{upload_id}}"
    
    # TTL Configurations
    CACHE_TTL_DEFAULT: Final[int] = 300
    CACHE_TTL_SHORT: Final[int] = 60
    CACHE_TTL_MEDIUM: Final[int] = 300
    CACHE_TTL_LONG: Final[int] = 3600
    CACHE_TTL_VERY_LONG: Final[int] = 86400

    # Cache Events
    CACHE_EVENT_HIT: Final[str] = "HIT"
    CACHE_EVENT_MISS: Final[str] = "MISS"
    CACHE_EVENT_REFRESH: Final[str] = "REFRESH"
    CACHE_EVENT_EXPIRED: Final[str] = "EXPIRED"
    CACHE_EVENT_INVALIDATE: Final[str] = "INVALIDATE"

    # End of Cache


    # ==================================================
    # 9. Events
    # ==================================================
    EVENT_RENDER_STARTED: Final[str] = "RENDER_STARTED"
    EVENT_RENDER_COMPLETED: Final[str] = "RENDER_COMPLETED"
    EVENT_RENDER_FAILED: Final[str] = "RENDER_FAILED"
    EVENT_CACHE_HIT: Final[str] = "CACHE_HIT"
    EVENT_CACHE_MISS: Final[str] = "CACHE_MISS"
    EVENT_ENGINE_STARTED: Final[str] = "ENGINE_STARTED"
    EVENT_ENGINE_COMPLETED: Final[str] = "ENGINE_COMPLETED"
    EVENT_ENGINE_FAILED: Final[str] = "ENGINE_FAILED"

    # End of Events


    # ==================================================
    # 10. Telemetry
    # ==================================================
    TRACE_ID_HEADER: Final[str] = "X-Trace-Id"
    SPAN_ID_HEADER: Final[str] = "X-Span-Id"
    REQUEST_ID_HEADER: Final[str] = "X-Request-Id"
    CORRELATION_ID_HEADER: Final[str] = "X-Correlation-Id"

    # End of Telemetry


    # ==================================================
    # 11. Metrics
    # ==================================================
    # METRIC_PREFIX yalnızca sisteme gelecekte eklenecek yeni metrik isimlendirmelerinde kullanılacaktır.
    # Mevcut metriklerin isimleri geriye dönük uyumluluğun korunması için değiştirilmemiştir.
    METRIC_PREFIX: Final[str] = "dashboard_"
    
    # --- Histogram (Süre ve Dağılım Ölçümleri) ---
    METRIC_DURATION_REPO_MS: Final[str] = "duration_repo_ms"
    METRIC_DURATION_QUERY_MS: Final[str] = "duration_query_ms"
    METRIC_DURATION_PRIME_MS: Final[str] = "duration_prime_ms"
    METRIC_DURATION_QUARTER_MS: Final[str] = "duration_quarter_ms"
    METRIC_DURATION_RECOVERY_MS: Final[str] = "duration_recovery_ms"
    METRIC_DURATION_AI_MS: Final[str] = "duration_ai_ms"
    METRIC_DURATION_MAPPER_MS: Final[str] = "duration_mapper_ms"
    METRIC_DURATION_FORMATTER_MS: Final[str] = "duration_formatter_ms"
    METRIC_DURATION_BUILDER_MS: Final[str] = "duration_builder_ms"
    METRIC_DURATION_CACHE_READ_MS: Final[str] = "duration_cache_read_ms"
    METRIC_RENDER_TOTAL_MS: Final[str] = "dashboard_render_total_ms"

    # --- Counter (Kümülatif Artış Gösteren Operasyon Metrikleri) ---
    METRIC_RENDER_SUCCESS: Final[str] = "dashboard_render_success_count"
    METRIC_RENDER_FAILURE: Final[str] = "dashboard_render_failure_count"

    METRIC_CACHE_HIT: Final[str] = "cache_hit_count"
    METRIC_CACHE_MISS: Final[str] = "cache_miss_count"
    METRIC_CACHE_EXPIRED: Final[str] = "cache_expired_count"
    METRIC_CACHE_REFRESH: Final[str] = "cache_refresh_count"
    METRIC_CACHE_INVALIDATE: Final[str] = "cache_invalidate_count"
    METRIC_CACHE_WRITE: Final[str] = "cache_write_count"
    METRIC_CACHE_DELETE: Final[str] = "cache_delete_count"

    # --- Gauge (Anlık Değerleri Ölçen Metrikler) ---
    # Gelecekte eklenecek olan anlık sistem metrikleri (Örn: Kuyruk boyutu, aktif bellek kullanımı)
    # bu alanda tanımlanacaktır. 
    # 
    # Örnek future metric isimleri:
    # dashboard_active_requests
    # dashboard_queue_size
    # dashboard_memory_usage
    # dashboard_cache_entries

    # End of Metrics

# End of DashboardConstants
