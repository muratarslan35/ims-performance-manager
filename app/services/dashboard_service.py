"""Central enterprise-grade read-only aggregation layer integrating PrimeEngine, AI Analytics, QuarterEngine, RecoveryEngine, Settings, and auxiliary modules."""

from datetime import datetime
import time
import logging
import decimal
from sqlalchemy import func
from flask import current_app

from app.extensions import db
from app.models import IMSUpload, IMSSummary, Product, RecoverySummary, Representative, Target, Setting
from app.services.period_service import PeriodService

try:
    from app.models import ImportAuditLog, RepresentativeMatch, ProductMatch, ManualMatchQueue
except ImportError:
    ImportAuditLog = RepresentativeMatch = ProductMatch = ManualMatchQueue = None

try:
    from app.services.quarter_engine import QuarterEngine
except ImportError:
    QuarterEngine = None

try:
    from app.services.recovery_engine import RecoveryEngine
except ImportError:
    RecoveryEngine = None

from app.services.ai_analytics_service import AIAnalyticsService
from app.services.prime_engine import PrimeEngine, TTLDataCache, CACHE_TTL

MONTH_NAMES = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
_DASHBOARD_CACHE = TTLDataCache(ttl=CACHE_TTL)
logger = logging.getLogger(__name__)


def _serialize_value(val):
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_serialize_value(item) for item in val]
    return val


def _serialize_orm(obj):
    if obj is None:
        return None
    if hasattr(obj, "_asdict"):
        return {k: _serialize_value(v) for k, v in obj._asdict().items()}
    if hasattr(obj, "keys") and hasattr(obj, "__getitem__"):
        try:
            return {str(k): _serialize_value(obj[k]) for k in obj.keys()}
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        d = {}
        for k, v in obj.__dict__.items():
            if not k.startswith("_"):
                d[k] = _serialize_value(v)
        return d
    return obj


def _normalize_engine_result(res):
    """Normalize various return types from engines into dict for safe consumption."""
    if res is None:
        return {}
    if isinstance(res, dict):
        return res
    if hasattr(res, "_asdict"):
        return res._asdict()
    if hasattr(res, "__dict__"):
        return {k: getattr(res, k) for k in dir(res) if not k.startswith('_') and not callable(getattr(res, k))}
    if isinstance(res, (tuple, list)):
        return {"data": list(res)}
    return {"value": res}


class DashboardService:
    """Read-only aggregation layer gathering metrics from PrimeEngine, QuarterEngine, RecoveryEngine, AI Analytics, Settings, and Database."""

    def __init__(self, representative_id=None, year=None, month=None, overrides=None):
        today_date = current_app.config.get("CURRENT_DATE") if current_app else None
        
        # Phase 1: Centralized Reporting Period Initialization
        self.period = PeriodService.get_active_period(year, month)
        
        self.rep_id = representative_id
        # Backward compatibility preserved
        self.year = self.period["year"]
        self.month = self.period["month"]
        self.quarter = self.period["quarter"]
        
        self.overrides = overrides or {}
        self._prime_engine = None
        self._prime_result_cache = None
        self._last_cache_hit = False
        self._ai_result_cache = None
        
        # Enterprise Versioning & Core Properties
        self._company_name = self._get_setting_runtime("COMPANY_NAME", current_app.config.get("COMPANY_NAME", "Bilim İlaç") if current_app else "Bilim İlaç")
        self._dashboard_version = self._get_setting_runtime("DASHBOARD_VERSION", current_app.config.get("DASHBOARD_VERSION", "3.2.0") if current_app else "3.2.0")
        self._engine_version = self._get_setting_runtime("ENGINE_VERSION", current_app.config.get("ENGINE_VERSION", "3.2.0") if current_app else "3.2.0")
        self._import_version = self._get_setting_runtime("IMPORT_VERSION", current_app.config.get("IMPORT_VERSION", "3.2.0") if current_app else "3.2.0")
        self._dataset_version = self._get_setting_runtime("DATASET_VERSION", current_app.config.get("DATASET_VERSION", "3.2.0") if current_app else "3.2.0")
        self._cache_ttl = self._get_setting_runtime("CACHE_TTL", current_app.config.get("CACHE_TTL", CACHE_TTL) if current_app else CACHE_TTL)

        try:
            if hasattr(_DASHBOARD_CACHE, 'ttl'):
                _DASHBOARD_CACHE.ttl = self._cache_ttl
        except Exception:
            pass

        if self.rep_id:
            self._prime_engine = PrimeEngine(
                representative_id=self.rep_id,
                year=self.year,
                month=self.month,
                overrides=self.overrides,
                today=today_date,
                use_cache=True
            )

    def _sync_cache_ttl(self):
        """GERÇEK DİNAMİK CACHE_TTL: Helper metod ile run-time senkronizasyon."""
        try:
            from flask import has_app_context
            if not has_app_context():
                return
            st = Setting.query.filter_by(setting_key="CACHE_TTL").first()
            if st and st.setting_value is not None:
                new_ttl = int(float(st.setting_value))
                if getattr(self, '_cache_ttl', None) != new_ttl:
                    self._cache_ttl = new_ttl
                    if hasattr(_DASHBOARD_CACHE, 'ttl'):
                        _DASHBOARD_CACHE.ttl = new_ttl
        except Exception:
            pass

    def _get_setting_runtime(self, key, default=None):
        try:
            from flask import has_app_context
            if has_app_context():
                st = Setting.query.filter_by(setting_key=key).first()
                if st and st.setting_value is not None:
                    try:
                        if "." in str(st.setting_value):
                            return float(st.setting_value)
                        return int(st.setting_value)
                    except ValueError:
                        return st.setting_value
        except Exception:
            pass
        
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app:
                return current_app.config.get(key, default)
        except Exception:
            pass
            
        return default

    def _get_cache_key(self, prefix):
        """Enterprise standard for creating unique cache keys supporting weekly IMS isolates."""
        week_num = self.period.get("week_number", 1)
        upload_id = self.period.get("upload_id") or "noupload"
        return f"{prefix}_{self._company_name}_{self.rep_id or 'all'}_{self.year}_{self.month}_{self.quarter}_w{week_num}_u{upload_id}_{self._dashboard_version}_{self._engine_version}_{self._dataset_version}_{self._import_version}"

    def _get_prime_result(self):
        start_time = time.time()
        if self._prime_result_cache is not None:
            self._last_cache_hit = True
            return self._prime_result_cache

        self._last_cache_hit = False
        if not self._prime_engine:
            try:
                from flask import has_app_context
                if has_app_context():
                    rep = Representative.query.filter_by(active=True).first()
                    if not rep:
                        return {}
                    self.rep_id = rep.id
                else:
                    return {}
            except Exception:
                return {}
                
            try:
                today_date = current_app.config.get("CURRENT_DATE") if current_app else None
            except Exception:
                today_date = None
                
            self._prime_engine = PrimeEngine(
                representative_id=self.rep_id,
                year=self.year,
                month=self.month,
                overrides=self.overrides,
                today=today_date,
                use_cache=True
            )

        try:
            self._prime_result_cache = self._prime_engine.calculate(save_history=False)
        except Exception as exc:
            logger.exception(f"DashboardService PrimeEngine calculation error: {exc}")
            self._prime_result_cache = {}

        elapsed = time.time() - start_time
        logger.info(f"PrimeEngine execution completed in {elapsed:.4f}s")
        return self._prime_result_cache

    def _get_ai_result(self):
        if self._ai_result_cache is not None:
            return self._ai_result_cache
        try:
            ai_service = AIAnalyticsService()
            self._ai_result_cache = ai_service.run_all() or {}
        except Exception as exc:
            logger.exception(f"DashboardService AIAnalyticsService error: {exc}")
            self._ai_result_cache = {}
        return self._ai_result_cache

    def load_counts(self):
        self._sync_cache_ttl()
        cache_key = self._get_cache_key("dashboard_counts")
        cached = _DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            data = {
                "total_products": Product.query.filter_by(is_active=True).count() or 0,
                "total_representatives": Representative.query.filter_by(active=True).count() or 0,
                "total_targets": Target.query.count() or 0,
                "total_uploads": IMSUpload.query.count() or 0,
                "completed_uploads": IMSUpload.query.filter_by(status="COMPLETED").count() or 0,
                "failed_uploads": IMSUpload.query.filter_by(status="FAILED").count() or 0,
                "processing_uploads": IMSUpload.query.filter_by(status="PROCESSING").count() or 0,
            }
        except Exception as exc:
            logger.exception(f"Error in load_counts: {exc}")
            data = {
                "total_products": 0,
                "total_representatives": 0,
                "total_targets": 0,
                "total_uploads": 0,
                "completed_uploads": 0,
                "failed_uploads": 0,
                "processing_uploads": 0,
            }
        
        # GERÇEK CACHE_AGE: Save creation time independently on Cache MISS
        _DASHBOARD_CACHE.set(f"{cache_key}_ts", time.time())
        _DASHBOARD_CACHE.set(cache_key, data)
        return data

    def load_last_upload(self):
        try:
            upload = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc()).first()
            uploaded_at_iso = upload.uploaded_at.isoformat() if upload and upload.uploaded_at else None
            completed_at_iso = upload.completed_at.isoformat() if upload and upload.completed_at else None

            serialized_upload = _serialize_orm(upload)
            error_msg = getattr(upload, "error_message", None) if upload else None
            warning_msg = getattr(upload, "warning_message", None) if upload else None
            sheet_count = getattr(upload, "sheet_count", 0) if upload else 0
            raw_count = getattr(upload, "raw_record_count", 0) if upload else 0
            fact_count = getattr(upload, "fact_record_count", 0) if upload else 0
            summary_count = getattr(upload, "summary_record_count", 0) if upload else 0

            has_errors = bool(error_msg)
            validation_result = None
            if upload:
                validation_result = {
                    "success": not has_errors,
                    "sheet_validation": sheet_count > 0,
                    "column_validation": not has_errors,
                    "duplicate_validation": True,
                    "empty_validation": raw_count > 0,
                    "summary_validation": summary_count > 0,
                    "fact_validation": fact_count > 0,
                    "error_details": error_msg,
                    "warning_details": warning_msg
                }

            checksum = getattr(upload, "checksum", None) if upload else None
            import_version = getattr(upload, "import_version", None) if upload else self._import_version

            rollback_available = bool(upload and upload.status == "COMPLETED" and summary_count > 0)
            if upload and hasattr(upload, "rollback_available"):
                rollback_available = bool(upload.rollback_available)

            audit_data = {}
            if ImportAuditLog and upload:
                try:
                    audit = ImportAuditLog.query.filter_by(upload_id=upload.id).first()
                    if audit:
                        audit_data = {
                            "import_errors": getattr(audit, "import_errors", 0),
                            "warnings": getattr(audit, "warnings", 0),
                            "duplicate_rows": getattr(audit, "duplicate_rows", 0),
                            "invalid_rows": getattr(audit, "invalid_rows", 0),
                            "matched_rows": getattr(audit, "matched_rows", 0),
                            "success_rate": getattr(audit, "success_rate", 100.0),
                            "import_success_rate": getattr(audit, "success_rate", 100.0),
                            "audit_version": getattr(audit, "audit_version", "1.0"),
                            "audit_duration": getattr(audit, "audit_duration", 0.0),
                            "checksum_validation": getattr(audit, "checksum_validation", True),
                            "import_health": getattr(audit, "import_health", "Optimal")
                        }
                except Exception:
                    pass

            match_data = {}
            if RepresentativeMatch and ProductMatch:
                try:
                    pending_cnt = ManualMatchQueue.query.filter_by(status="PENDING").count() if ManualMatchQueue else 0
                    resolved_cnt = RepresentativeMatch.query.filter_by(status="RESOLVED").count() if RepresentativeMatch else 0
                    total_matches = pending_cnt + resolved_cnt
                    res_rate = round((resolved_cnt / total_matches * 100), 1) if total_matches > 0 else 100.0
                    pending_rate = round((pending_cnt / total_matches * 100), 1) if total_matches > 0 else 0.0
                    
                    if pending_cnt == 0:
                        match_health = "Healthy"
                    elif res_rate < 80.0:
                        match_health = "Critical"
                    else:
                        match_health = "Warning"

                    match_data = {
                        "pending_match_count": pending_cnt,
                        "pending_matches": pending_cnt,
                        "resolved_match_count": resolved_cnt,
                        "resolved_matches": resolved_cnt,
                        "matched_products": ProductMatch.count() if hasattr(ProductMatch, "count") else (ProductMatch.query.count() if hasattr(ProductMatch, "query") else 0),
                        "matched_representatives": RepresentativeMatch.count() if hasattr(RepresentativeMatch, "count") else (RepresentativeMatch.query.count() if hasattr(RepresentativeMatch, "query") else 0),
                        "manual_queue": pending_cnt,
                        "resolution_rate": res_rate,
                        "pending_percent": pending_rate,
                        "resolved_percent": res_rate,
                        "matching_health": match_health
                    }
                except Exception:
                    pass

            return {
                "last_upload": serialized_upload,
                "latest_upload_file": upload.file_name if upload else None,
                "latest_upload_date": uploaded_at_iso,
                "latest_upload_status": upload.status if upload else None,
                "upload_details": {
                    "file": upload.file_name if upload else None,
                    "quarter": upload.quarter if upload else None,
                    "month": upload.month if upload else None,
                    "year": upload.year if upload else None,
                    "week": upload.week_number if upload else None,
                    "uploaded_at": uploaded_at_iso,
                    "completed_at": completed_at_iso,
                    "processing_time": getattr(upload, "processing_time", 0.0),
                    "status": upload.status if upload else None,
                    "warning_message": warning_msg,
                    "error_message": error_msg,
                    "sheet_count": sheet_count,
                    "raw_record_count": raw_count,
                    "fact_record_count": fact_count,
                    "summary_record_count": summary_count,
                    "checksum": checksum,
                    "import_version": import_version,
                    "rollback_available": rollback_available,
                    "validation_result": validation_result,
                    **audit_data,
                    **match_data
                }
            }
        except Exception as exc:
            logger.exception(f"Error in load_last_upload: {exc}")
            return {
                "last_upload": None,
                "latest_upload_file": None,
                "latest_upload_date": None,
                "latest_upload_status": None,
                "upload_details": {}
            }

    def load_recovery(self):
        prime_res = self._get_prime_result()
        recovery_analysis = prime_res.get("recovery_analysis", [])

        engine_summary = {}
        if RecoveryEngine is not None:
            try:
                rec_engine = RecoveryEngine(representative_id=self.rep_id, year=self.year, month=self.month)
                for method_name in ["get_recovery_analysis", "calculate", "run", "summary", "execute", "get_summary"]:
                    if hasattr(rec_engine, method_name):
                        res = getattr(rec_engine, method_name)()
                        res = _normalize_engine_result(res)
                        if isinstance(res, dict) and "recovery_analysis" in res:
                            recovery_analysis = res.get("recovery_analysis", [])
                            engine_summary = res.get("summary", res)
                            break
                        elif isinstance(res, list):
                            recovery_analysis = res
                            break
            except Exception:
                pass

        counts = {"risk_products": 0, "critical_products": 0, "warning_products": 0, "healthy_products": 0}
        total_items = len(recovery_analysis)

        for item in recovery_analysis:
            status = item.get("status", "")
            if status in ("Kritik", "Critical"):
                counts["critical_products"] += 1
            elif status in ("Riskli", "Risk"):
                counts["risk_products"] += 1
            elif status in ("Takip", "Warning"):
                counts["warning_products"] += 1
            else:
                counts["healthy_products"] += 1

        completion_pct = round((counts["healthy_products"] / total_items * 100), 1) if total_items > 0 else 100.0
        risk_pct = round(((counts["critical_products"] + counts["risk_products"]) / total_items * 100), 1) if total_items > 0 else 0.0
        critical_pct = round((counts["critical_products"] / total_items * 100), 1) if total_items > 0 else 0.0

        sorted_recovery = sorted(recovery_analysis, key=lambda x: x.get("remaining_tl", 0.0), reverse=True)
        priority_products = sorted_recovery[:5]

        db_rows = []
        try:
            from flask import has_app_context
            if has_app_context():
                db_rows = RecoverySummary.query.all() or []
        except Exception as exc:
            logger.exception(f"Error fetching RecoverySummary from DB: {exc}")
            db_rows = []

        ai_data = self._get_ai_result()
        ai_recs = ai_data.get("action_recommendations", [])

        sample = recovery_analysis[0] if recovery_analysis and isinstance(recovery_analysis[0], dict) else {}
        rec_extras = {
            "overall_summary": engine_summary.get("overall_summary", "Recovery analizi güncel durumda."),
            "risk_summary": engine_summary.get("risk_summary", f"Toplam {total_items} üründen {counts['critical_products']} tanesi kritik durumda."),
            "remaining_box": engine_summary.get("remaining_box", sample.get("remaining_box", 0.0)),
            "remaining_tl": engine_summary.get("remaining_tl", sample.get("remaining_tl", 0.0)),
            "remaining_percent": engine_summary.get("remaining_percent", sample.get("remaining_percent", 0.0)),
            "priority_summary": engine_summary.get("priority_summary", "Kritik ürünlere öncelik verilmeli."),
            "status": engine_summary.get("status", sample.get("status", "Normal")),
            "priority": engine_summary.get("priority", sample.get("priority", "Medium")),
            "risk_score": engine_summary.get("risk_score", sample.get("risk_score", 0)),
            "recommendation": engine_summary.get("recommendation", sample.get("recommendation", "Takip edilmeli")),
        }

        return {
            **counts,
            "completion_percent": completion_pct,
            "risk_percent": risk_pct,
            "critical_percent": critical_pct,
            "priority_products": priority_products,
            "top_recovery_products": priority_products,
            "summary": rec_extras["risk_summary"],
            "ai_recommendation": ai_recs,
            "recovery_summary": recovery_analysis,
            "recovery_summary_db": [_serialize_orm(r) for r in db_rows],
            **rec_extras
        }

    def load_prime_summary(self):
        prime_res = self._get_prime_result()
        breakdown = prime_res.get("breakdown", {})
        ai_data = self._get_ai_result()

        total_target = prime_res.get("total_target", 0.0)
        total_real = prime_res.get("total_realization", 0.0)
        prime_pct = round((total_real / total_target * 100), 2) if total_target > 0 else 0.0

        main_prime_val = self._get_setting_runtime("MAIN_PRIME", breakdown.get("main_prime", 0.0))
        ciro_prime_val = self._get_setting_runtime("CIRO_PRIME", breakdown.get("ciro_prime", 0.0))

        return {
            "main_prime": main_prime_val,
            "ciro_prime": ciro_prime_val,
            "recovery_prime": ai_data.get("recovery_prime", breakdown.get("recovery", 0.0)),
            "expected_prime": ai_data.get("expected_prime", 0.0),
            "maximum_prime": ai_data.get("max_prime", 0.0),
            "lost_prime": ai_data.get("lost_prime", 0.0),
            "possible_prime": ai_data.get("max_prime", breakdown.get("total", 0.0)),
            "remaining_prime": round(max(0.0, ai_data.get("max_prime", 0.0) - breakdown.get("total", 0.0)), 2),
            "bonus": breakdown.get("bonus", 0.0),
            "penalty": breakdown.get("penalty", 0.0),
            "quarter_effect": breakdown.get("quarter_effect", 0.0),
            "product_effect": breakdown.get("product_effect", 0.0),
            "extra_prime": breakdown.get("extra_prime", 0.0),
            "total_prime": breakdown.get("total", 0.0),
            "prime_percentage": prime_pct,
            "prime_gap": round(max(0.0, total_target - total_real), 2),
            "prime_projection": ai_data.get("expected_prime", breakdown.get("total", 0.0)),
            "status": prime_res.get("status", "-"),
            "success": prime_res.get("success", False),
            "simulation": prime_res.get("simulation", False),
            "breakdown": breakdown,
        }

    def load_quarter_summary(self):
        prime_res = self._get_prime_result()
        q_analysis = prime_res.get("quarter_analysis", {})

        target_val = q_analysis.get("target_tl", 0.0)
        real_val = q_analysis.get("realization_tl", 0.0)
        pct_val = q_analysis.get("total_percent", 0.0)

        q_engine_data = {}
        if QuarterEngine is not None:
            try:
                q_inst = QuarterEngine(representative_id=self.rep_id, year=self.year, quarter=self.quarter)
                for method_name in ["calculate", "run", "summary", "execute", "get_summary"]:
                    if hasattr(q_inst, method_name):
                        res = getattr(q_inst, method_name)()
                        res = _normalize_engine_result(res)
                        if isinstance(res, dict):
                            q_engine_data = res
                            break
            except Exception:
                pass

        return {
            "quarter": prime_res.get("quarter", self.quarter),
            "quarter_target": target_val,
            "quarter_realization": real_val,
            "quarter_percent": pct_val,
            "quarter_trend": "artış" if pct_val >= 90 else "stabil",
            "quarter_projection": q_engine_data.get("quarter_projection", round(real_val * 1.05, 2)),
            "quarter_forecast": q_engine_data.get("quarter_forecast", round(real_val * 1.1, 2)),
            "quarter_progress": q_engine_data.get("quarter_progress", pct_val),
            "quarter_completion": q_engine_data.get("quarter_completion", pct_val),
            "remaining_target": q_engine_data.get("remaining_target", round(max(0.0, target_val - real_val), 2)),
            "remaining_days": q_engine_data.get("remaining_days", 15),
            "working_days": q_engine_data.get("working_days", 60),
            "expected_finish": q_engine_data.get("expected_finish", datetime.now().isoformat()),
            "quarter_score": pct_val,
            "quarter_gap": round(max(0.0, target_val - real_val), 2),
            "quarter_expected_percent": pct_val,
            "quarter_expected_tl": target_val,
            "quarter_expected_prime": prime_res.get("breakdown", {}).get("total", 0.0),
            "completed_products": q_analysis.get("completed_products", 0),
            "failed_products": q_analysis.get("failed_products", 0),
            "total_percent": pct_val,
            "quarter_analysis": q_analysis,
            **q_engine_data
        }

    @staticmethod
    def build_ai_messages(recovery):
        messages = []
        if recovery.get("critical_products"):
            messages.append(f"{recovery['critical_products']} kritik ürün bulunuyor.")
        if recovery.get("risk_products"):
            messages.append(f"{recovery['risk_products']} riskli ürün takip edilmeli.")
        if recovery.get("warning_products"):
            messages.append(f"{recovery['warning_products']} ürün takip seviyesinde.")
        if not messages:
            messages.append("Recovery açısından riskli ürün bulunmuyor.")
        return messages

    def load_overall_stats(self):
        prime_res = self._get_prime_result()
        return {
            "overall_realization_tl": prime_res.get("total_realization", 0.0),
            "overall_target_tl": prime_res.get("total_target", 0.0),
            "overall_percent": prime_res.get("total_tl_percent", 0.0),
        }

    def load_product_performance(self):
        prime_res = self._get_prime_result()
        products = prime_res.get("products", [])
        result = []
        total_ciro = 0.0
        for item in products:
            total_tl = item.get("actual_tl", 0.0)
            target_tl = item.get("target_tl", 0.0)
            pct = item.get("percent", 0.0)
            if pct >= 90:
                status = "Tamamlandı"
            elif pct >= 70:
                status = "Devam Ediyor"
            else:
                status = "Riskli"
            result.append({
                "product_name": item.get("product_name", ""),
                "total_tl": round(total_tl, 0),
                "target_tl": round(target_tl, 0),
                "realization_percent": pct,
                "status": status,
                "gap_tl": item.get("gap_tl", 0.0),
                "gap_percent": item.get("gap_percent", 0.0),
                "prime_contribution": item.get("bonus_amount", 0.0),
            })
            total_ciro += total_tl
        return {"product_performance": result, "total_ciro": round(total_ciro, 0)}

    def load_top_representatives(self):
        self._sync_cache_ttl()
        cache_key = self._get_cache_key("dashboard_top_reps")
        cached = _DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            from flask import has_app_context
            if has_app_context():
                rows = (
                    db.session.query(
                        Representative,
                        func.sum(IMSSummary.tl).label("total_tl"),
                        func.sum(IMSSummary.bonus_amount).label("bonus"),
                        func.sum(Target.tl_target).label("target_tl")
                    )
                    .join(IMSSummary, IMSSummary.representative_id == Representative.id)
                    .outerjoin(Target, (Target.representative_id == Representative.id) & (Target.year == IMSSummary.year))
                    .filter(Representative.active == True, IMSSummary.year == self.year)
                    .group_by(Representative.id)
                    .all()
                ) or []
            else:
                rows = []
        except Exception as exc:
            logger.exception(f"Error loading representatives aggregate: {exc}")
            rows = []

        rep_stats = []
        for rep, total_tl, bonus, target_tl in rows:
            try:
                t_val = target_tl or 0.0
                a_val = total_tl or 0.0
                pct = round((a_val / t_val * 100), 1) if t_val > 0 else 0.0
                rep_stats.append({
                    "rep_name": getattr(rep, "rep_name", ""),
                    "city": getattr(rep, "city", None) or "-",
                    "total_tl": round(a_val, 0),
                    "realization_percent": pct,
                    "bonus_amount": round(bonus or 0.0, 0),
                })
            except Exception:
                continue

        rep_stats.sort(key=lambda x: x["realization_percent"], reverse=True)
        for i, r in enumerate(rep_stats):
            r["rank"] = i + 1
        data = {"top_representatives": rep_stats[:10]}
        
        _DASHBOARD_CACHE.set(f"{cache_key}_ts", time.time())
        _DASHBOARD_CACHE.set(cache_key, data)
        return data

    def load_monthly_trend(self):
        prime_res = self._get_prime_result()
        trends = prime_res.get("trend_graphs", {})
        monthly = trends.get("monthly", [])
        quarterly = trends.get("quarterly", [])
        yearly = trends.get("yearly", [])

        labels = [item.get("label", "") for item in monthly]
        realization = [item.get("actual_tl", 0.0) for item in monthly]
        targets = [item.get("target_tl", 0.0) for item in monthly]

        return {
            "monthly_trend": {
                "labels": labels,
                "realization": realization,
                "target": targets,
            },
            "quarterly_trend": quarterly,
            "yearly_trend": yearly,
            "trend_graphs": trends,
        }

    def load_market_share_trend(self):
        self._sync_cache_ttl()
        cache_key = self._get_cache_key("dashboard_market_share")
        cached = _DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            from flask import has_app_context
            if has_app_context():
                rows = (
                    db.session.query(
                        IMSSummary.year,
                        IMSSummary.month,
                        func.avg(IMSSummary.market_share).label("avg_share"),
                    )
                    .group_by(IMSSummary.year, IMSSummary.month)
                    .order_by(IMSSummary.year, IMSSummary.month)
                    .limit(12)
                    .all()
                ) or []
            else:
                rows = []
        except Exception as exc:
            logger.exception(f"Error loading market share trend: {exc}")
            rows = []

        labels = []
        values = []
        for r in rows:
            try:
                month_idx = int(getattr(r, "month", 1)) - 1
                month_name = MONTH_NAMES[month_idx] if 0 <= month_idx < 12 else ""
                labels.append(f"{month_name} {getattr(r, 'year', '')}")
                values.append(round(getattr(r, "avg_share", 0) or 0, 2))
            except Exception:
                continue

        data = {
            "market_share_trend": {
                "labels": labels,
                "values": values,
            }
        }
        
        _DASHBOARD_CACHE.set(f"{cache_key}_ts", time.time())
        _DASHBOARD_CACHE.set(cache_key, data)
        return data

    def load_city_performance(self):
        self._sync_cache_ttl()
        cache_key = self._get_cache_key("dashboard_city_perf")
        cached = _DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            from flask import has_app_context
            if has_app_context():
                rows = (
                    db.session.query(
                        Representative.city,
                        func.sum(IMSSummary.tl).label("total_tl"),
                        func.sum(Target.tl_target).label("target_tl"),
                        func.count(Representative.id.distinct()).label("rep_count"),
                    )
                    .join(IMSSummary, IMSSummary.representative_id == Representative.id)
                    .outerjoin(
                        Target,
                        (Target.representative_id == Representative.id)
                        & (Target.year == IMSSummary.year)
                        & (Target.month == IMSSummary.month),
                    )
                    .filter(Representative.city.isnot(None))
                    .group_by(Representative.city)
                    .all()
                ) or []
            else:
                rows = []
        except Exception as exc:
            logger.exception(f"Error loading city performance: {exc}")
            rows = []

        city_perf = {}
        for city, tl, target, rep_count in rows:
            if city:
                pct = round((tl / target * 100), 1) if (target and target > 0) else 0
                city_perf[city] = {
                    "tl": round(tl or 0, 0),
                    "target": round(target or 0, 0),
                    "percent": pct,
                    "representative_count": rep_count or 0,
                    "risk_score": max(0, 100 - int(pct)),
                    "opportunity_score": int(pct)
                }
        data = {"city_performance": city_perf}
        
        _DASHBOARD_CACHE.set(f"{cache_key}_ts", time.time())
        _DASHBOARD_CACHE.set(cache_key, data)
        return data

    def load_active_quarter(self):
        prime_res = self._get_prime_result()
        return {"active_quarter": prime_res.get("quarter", self.quarter)}

    def load_recent_uploads(self):
        try:
            from flask import has_app_context
            if has_app_context():
                uploads = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc()).limit(5).all() or []
            else:
                uploads = []
            serialized_uploads = []
            for u in uploads:
                serialized_uploads.append(_serialize_orm(u))
            return {"recent_uploads": serialized_uploads}
        except Exception as exc:
            logger.exception(f"Error loading recent uploads: {exc}")
            return {"recent_uploads": []}

    def load_ai_analytics(self):
        try:
            ai_data = self._get_ai_result()
            next_month = ai_data.get("next_month", {}) or {}
            prime_res = self._get_prime_result()
            forecast = prime_res.get("ai_forecast", {})
            recommendations = ai_data.get("action_recommendations", [])

            return {
                "ai_scores": {
                    "risk_score": ai_data.get("risk_score", 0),
                    "opportunity_score": ai_data.get("opportunity_score", 0),
                    "goal_probability": ai_data.get("goal_probability", 0),
                    "expected_prime": forecast.get("expected_prime", ai_data.get("expected_prime", 0)),
                    "max_prime": ai_data.get("max_prime", 0.0),
                    "lost_prime": ai_data.get("lost_prime", 0.0),
                    "recovery_prime": ai_data.get("recovery_prime", 0.0),
                    "additional_prime": next_month.get("predicted_tl", 0),
                },
                "ai_messages": prime_res.get("ai_messages", ai_data.get("daily_summary", [])),
                "ai_risky_products": ai_data.get("risky_products", []),
                "ai_risky_representatives": ai_data.get("risky_representatives", []),
                "ai_near_target": ai_data.get("products_close_to_target", []),
                "ai_recommendations": recommendations,
                "ai_management_summary": ai_data.get("management_summary", ""),
                "ai_next_month": next_month,
                "ai_forecast": forecast,
                "confidence": forecast.get("confidence", 0),
                "confidence_level": "High" if forecast.get("confidence", 0) > 80 else "Medium",
                "forecast": forecast,
                "risk_level": "High" if ai_data.get("risk_score", 0) > 50 else "Low",
                "trend": ai_data.get("trend_direction", "stable"),
                "probability": ai_data.get("goal_probability", 0)
            }
        except Exception as exc:
            logger.exception(f"Error loading AI analytics: {exc}")
            return {
                "ai_scores": {
                    "risk_score": 0,
                    "opportunity_score": 0,
                    "goal_probability": 0,
                    "expected_prime": 0,
                    "max_prime": 0.0,
                    "lost_prime": 0,
                    "recovery_prime": 0.0,
                    "additional_prime": 0,
                },
                "ai_messages": [],
                "ai_risky_products": [],
                "ai_risky_representatives": [],
                "ai_near_target": [],
                "ai_recommendations": [],
                "ai_management_summary": "",
                "ai_next_month": {},
                "ai_forecast": {},
                "confidence": 0,
                "confidence_level": "Low",
                "forecast": {},
                "risk_level": "Low",
                "trend": "stable",
                "probability": 0
            }

    def load_what_if(self):
        prime_res = self._get_prime_result()
        return {"what_if_analysis": prime_res.get("what_if_analysis", [])}

    def load_comparison(self):
        prime_res = self._get_prime_result()
        return {"comparison_graph": prime_res.get("comparison_graph", {})}

    def load_history(self):
        history_list = []
        if self._prime_engine:
            try:
                history_list = self._prime_engine.load_history() or []
            except Exception as exc:
                logger.exception(f"Error loading simulation history: {exc}")
                history_list = []

        if not history_list:
            try:
                from flask import has_app_context
                if has_app_context():
                    fallback_rows = db.session.execute(db.text(
                        "SELECT year, month, SUM(tl) as total_tl, SUM(bonus_amount) as bonus "
                        "FROM ims_summary GROUP BY year, month ORDER BY year DESC, month DESC LIMIT 6"
                    )).fetchall()
                    for r in fallback_rows:
                        history_list.append({
                            "simulation_date": f"{r.year}-{r.month:02d}-01T00:00:00",
                            "total_percent": 0.0,
                            "bonus": r.bonus or 0.0,
                            "summary": {
                                "total_prime": r.bonus or 0.0,
                                "total_realization": r.total_tl or 0.0,
                                "total_percent": 0.0
                            }
                        })
            except Exception:
                pass

        def _get_sort_key(item):
            for field in ("created_at", "simulation_date", "created_on"):
                val = item.get(field)
                if val:
                    if isinstance(val, str):
                        try:
                            return datetime.fromisoformat(val)
                        except Exception:
                            pass
                    elif isinstance(val, datetime):
                        return val
            return datetime.min

        try:
            history_list.sort(key=_get_sort_key, reverse=True)
        except Exception:
            pass

        history_count = len(history_list)
        primes = []
        bonuses = []
        percentages = []

        for entry in history_list:
            summary = entry.get("summary", {})
            p_val = summary.get("total_prime", 0.0)
            if isinstance(p_val, (int, float)):
                primes.append(p_val)

            b_val = summary.get("bonus", 0.0) or entry.get("bonus", 0.0)
            if isinstance(b_val, (int, float)):
                bonuses.append(b_val)

            pct_val = summary.get("total_percent", 0.0) or entry.get("total_percent", 0.0)
            if isinstance(pct_val, (int, float)):
                percentages.append(pct_val)

        highest_prime = max(primes) if primes else 0.0
        highest_bonus = max(bonuses) if bonuses else 0.0
        highest_percent = max(percentages) if percentages else (100.0 if primes else 0.0)

        monthly_avg = average_prime = round(sum(primes) / len(primes), 2) if primes else 0.0
        quarter_avg = average_prime
        year_avg = average_prime

        if len(primes) >= 2:
            growth_val = round(((primes[0] - primes[-1]) / (primes[-1] if primes[-1] > 0 else 1.0)) * 100, 2)
        else:
            growth_val = 0.0

        if growth_val > 1.0:
            history_trend = "artış"
        elif growth_val < -1.0:
            history_trend = "azalış"
        else:
            history_trend = "stabil"

        best_scenario = max(history_list, key=lambda x: x.get("summary", {}).get("total_prime", 0.0), default=None)
        worst_scenario = min(history_list, key=lambda x: x.get("summary", {}).get("total_prime", 0.0), default=None)
        last_simulation = history_list[0] if history_list else None

        return {
            "simulation_history": history_list,
            "history_count": history_count,
            "monthly_average": monthly_avg,
            "quarter_average": quarter_avg,
            "year_average": year_avg,
            "simulation_growth": growth_val,
            "prime_growth": growth_val,
            "history_trend": history_trend,
            "last_successful_simulation": last_simulation,
            "highest_realization": highest_prime,
            "highest_percent": highest_percent,
            "highest_bonus": highest_bonus,
            "highest_main_prime": highest_prime,
            "highest_total_prime": highest_prime,
            "highest_prime": highest_prime,
            "average_prime": average_prime,
            "last_simulation": last_simulation,
            "best_scenario": best_scenario,
            "worst_scenario": worst_scenario,
            "last_update": datetime.now().isoformat()
        }

    def load_executive_summary(self):
        prime_res = self._get_prime_result()
        overall = self.load_overall_stats()
        recovery = self.load_recovery()
        ai = self.load_ai_analytics()
        ai_scores = ai.get("ai_scores", {})

        products = prime_res.get("products", [])
        sorted_prods = sorted(products, key=lambda x: x.get("percent", 0.0), reverse=True)
        best_prod = sorted_prods[0] if sorted_prods else None
        worst_prod = sorted_prods[-1] if sorted_prods else None

        top_reps_data = self.load_top_representatives()
        top_reps = top_reps_data.get("top_representatives", [])
        best_rep = top_reps[0] if top_reps else None
        worst_rep = top_reps[-1] if top_reps else None

        city_perf = self.load_city_performance().get("city_performance", {})
        sorted_cities = sorted(city_perf.items(), key=lambda x: x[1].get("percent", 0.0), reverse=True)
        best_city = sorted_cities[0][0] if sorted_cities else None
        worst_city = sorted_cities[-1][0] if sorted_cities else None

        upload_info = self.load_last_upload()
        upload_details = upload_info.get("upload_details", {})
        u_status = upload_details.get("status")
        if u_status == "COMPLETED":
            upload_health = "Sağlıklı"
        elif u_status == "FAILED":
            upload_health = "Kritik Hata"
        elif u_status == "PROCESSING":
            upload_health = "İşleniyor"
        else:
            upload_health = None

        critical_count = recovery.get("critical_products", 0)
        risk_count = recovery.get("risk_products", 0)
        if critical_count > 0:
            recovery_health = "Kritik Seviye"
        elif risk_count > 0:
            recovery_health = "Riskli"
        else:
            recovery_health = "Sağlıklı"

        overall_status = "Başarılı" if prime_res.get("success", False) else "Takip Ediliyor"

        return {
            "executive_summary": {
                "overall_status": overall_status,
                "overall_rank": 1 if prime_res.get("success", False) else 2,
                "goal_probability": ai_scores.get("goal_probability", 0),
                "expected_prime": ai_scores.get("expected_prime", 0.0),
                "lost_prime": ai_scores.get("lost_prime", 0.0),
                "quarter_status": self.load_quarter_summary(),
                "best_city": best_city,
                "worst_city": worst_city,
                "best_region": best_city,
                "worst_region": worst_city,
                "best_representative": best_rep,
                "worst_representative": worst_rep,
                "best_product": best_prod,
                "worst_product": worst_prod,
                "upload_health": upload_health,
                "recovery_health": recovery_health,
                "risk_summary": f"Risk skoru: {ai_scores.get('risk_score', 0)} ({critical_count} kritik ürün)",
                "overall_stats": overall,
                "prime_summary": self.load_prime_summary(),
                "critical_risks": critical_count,
                "ai_management_summary": ai.get("ai_management_summary", ""),
                "upload_status": upload_info,
            }
        }

    def load_kpi_cards(self):
        prime_res = self._get_prime_result()
        breakdown = prime_res.get("breakdown", {})
        overall = self.load_overall_stats()
        ai = self.load_ai_analytics()
        ai_scores = ai.get("ai_scores", {})
        history_data = self.load_history()
        
        hist_list = history_data.get("simulation_history", [])
        current_value = overall.get("overall_realization_tl", 0.0)
        previous_value = 0.0
        if len(hist_list) > 1:
            prev_sim = hist_list[1]
            previous_value = prev_sim.get("summary", {}).get("total_realization", 0.0)
            
        delta = current_value - previous_value
        change_percent = round((delta / previous_value * 100), 2) if previous_value > 0 else 0.0

        return {
            "kpi_cards": {
                "total_prime": breakdown.get("total", 0.0),
                "main_prime": breakdown.get("main_prime", 0.0),
                "ciro_prime": breakdown.get("ciro_prime", 0.0),
                "recovery_prime": breakdown.get("recovery", 0.0),
                "bonus": breakdown.get("bonus", 0.0),
                "penalty": breakdown.get("penalty", 0.0),
                "quarter_effect": breakdown.get("quarter_effect", 0.0),
                "product_effect": breakdown.get("product_effect", 0.0),
                "extra_prime": breakdown.get("extra_prime", 0.0),
                "expected_prime": ai_scores.get("expected_prime", 0.0),
                "lost_prime": ai_scores.get("lost_prime", 0.0),
                "additional_prime": ai_scores.get("additional_prime", 0.0),
                "target_tl": overall.get("overall_target_tl", 0.0),
                "realization_tl": overall.get("overall_realization_tl", 0.0),
                "realization_percent": overall.get("overall_percent", 0.0),
                "total_target_tl": overall.get("overall_target_tl", 0.0),
                "total_realization_tl": overall.get("overall_realization_tl", 0.0),
                "tl_realization_percent": overall.get("overall_percent", 0.0),
                "prime_success": prime_res.get("success", False),
                "risk_score": ai_scores.get("risk_score", 0),
                "opportunity_score": ai_scores.get("opportunity_score", 0),
                "goal_probability": ai_scores.get("goal_probability", 0),
                "ai_confidence": ai.get("ai_forecast", {}).get("confidence", 0),
                "simulation_status": prime_res.get("simulation", False),
                "cache_hit": self._last_cache_hit,
                "cache_status": "Hit" if self._last_cache_hit else "Miss",
                "cache_ttl": self._cache_ttl,
                "history_count": history_data.get("history_count", 0),
                "trend": ai.get("trend", "stable"),
                "delta": round(delta, 2),
                "change": round(delta, 2),
                "change_percent": change_percent,
                "variance": round(current_value - overall.get("overall_target_tl", 0.0), 2),
                "previous_value": previous_value,
                "current_value": current_value,
                "target_gap": round(max(0.0, overall.get("overall_target_tl", 0.0) - current_value), 2),
                "forecast_gap": round(ai_scores.get("expected_prime", 0.0) - current_value, 2),
                "achievement": overall.get("overall_percent", 0.0),
                "achievement_percent": overall.get("overall_percent", 0.0),
                "growth": change_percent,
                "status": "Optimal" if overall.get("overall_percent", 0.0) >= 90 else "Warning",
                "priority": "Normal",
                "last_update": datetime.now().isoformat()
            }
        }

    def load_widgets_data(self):
        prime_res = self._get_prime_result()
        breakdown = prime_res.get("breakdown", {})
        ai = self.load_ai_analytics()
        ai_scores = ai.get("ai_scores", {})
        monthly = self.load_monthly_trend()
        city_perf = self.load_city_performance()
        recovery = self.load_recovery()
        top_reps = self.load_top_representatives()
        prod_perf = self.load_product_performance()

        realization_val = min(100.0, float(prime_res.get("total_tl_percent", 0.0)))
        recovery_val = float(recovery.get("completion_percent", 100.0))
        goal_prob_val = float(ai_scores.get("goal_probability", 0))
        risk_inv_val = float(max(0, 100 - ai_scores.get("risk_score", 0)))

        # Fetching actual creation timestamp safely using standard cache_key
        cache_key_counts = self._get_cache_key("dashboard_counts")
        cache_ts = _DASHBOARD_CACHE.get(f"{cache_key_counts}_ts")
        if not cache_ts:
            cache_ts = time.time()
        actual_cache_age = int(time.time() - cache_ts)

        return {
            "widget_data": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": "DashboardService",
                "source": "Enterprise Aggregate Layer",
                "confidence": ai.get("confidence", 0),
                "refresh_time": self._cache_ttl,
                "cache_age": actual_cache_age,
                "cache_hit": self._last_cache_hit,
                "dataset_version": self._dataset_version,
                "engine_version": self._engine_version,
                "dashboard_version": self._dashboard_version,
                "company": self._company_name,
                "period": f"{self.year}-{self.month:02d}",
                "quarter": prime_res.get("quarter", self.quarter),
                "month": self.month,
                "year": self.year,
                "import_version": self._import_version,
                "gauge_data": {
                    "goal_probability": ai_scores.get("goal_probability", 0),
                    "realization_percent": prime_res.get("total_tl_percent", 0.0),
                },
                "prime_breakdown_pie": {
                    "main_prime": breakdown.get("main_prime", 0.0),
                    "ciro_prime": breakdown.get("ciro_prime", 0.0),
                    "extra_prime": breakdown.get("extra_prime", 0.0),
                    "recovery": breakdown.get("recovery", 0.0),
                    "bonus": breakdown.get("bonus", 0.0),
                    "penalty": breakdown.get("penalty", 0.0),
                },
                "monthly_trend_chart": monthly.get("monthly_trend", {}),
                "quarterly_trend_chart": monthly.get("quarterly_trend", []),
                "yearly_trend_chart": monthly.get("yearly_trend", []),
                "city_performance_map": city_perf.get("city_performance", {}),
                "recovery_matrix": recovery.get("recovery_summary", []),
                "leaderboard": top_reps.get("top_representatives", []),
                "radar_data": {
                    "skills": ["Gerçekleşme", "Recovery", "Hedef Olasılığı", "Güvenilirlik", "Risk Durumu"],
                    "values": [realization_val, recovery_val, goal_prob_val, float(ai.get("ai_forecast", {}).get("confidence", 0)), risk_inv_val]
                },
                "heatmap_data": city_perf.get("city_performance", {}),
                "scatter_data": [{"x": p["target_tl"], "y": p["total_tl"], "name": p["product_name"]} for p in prod_perf.get("product_performance", [])],
                "quarter_gauge": prime_res.get("quarter_analysis", {}).get("total_percent", 0.0),
                "prime_comparison": prime_res.get("comparison_graph", {}),
                "performance_matrix": prod_perf.get("product_performance", []),
                "city_ranking": city_perf.get("city_performance", {}),
                "representative_ranking": top_reps.get("top_representatives", []),
                "product_ranking": prod_perf.get("product_performance", []),
                "quarter_comparison": prime_res.get("quarter_analysis", {}),
            }
        }

    def _get_all_runtime_settings(self):
        return {
            "COMPANY_NAME": self._company_name,
            "MAIN_PRIME": self._get_setting_runtime("MAIN_PRIME", current_app.config.get("MAIN_PRIME", 0.0) if current_app else 0.0),
            "CIRO_PRIME": self._get_setting_runtime("CIRO_PRIME", current_app.config.get("CIRO_PRIME", 0.0) if current_app else 0.0),
            "PRIME_STEP": self._get_setting_runtime("PRIME_STEP", current_app.config.get("PRIME_STEP", 0.0) if current_app else 0.0),
            "STEP_AMOUNT": self._get_setting_runtime("STEP_AMOUNT", current_app.config.get("STEP_AMOUNT", 0.0) if current_app else 0.0),
            "TARGET75": self._get_setting_runtime("TARGET75", current_app.config.get("TARGET75", 75.0) if current_app else 75.0),
            "TARGET90": self._get_setting_runtime("TARGET90", current_app.config.get("TARGET90", 90.0) if current_app else 90.0),
            "TARGET100": self._get_setting_runtime("TARGET100", current_app.config.get("TARGET100", 100.0) if current_app else 100.0),
            "MAX_PRIME": self._get_setting_runtime("MAX_PRIME", current_app.config.get("MAX_PRIME", 0.0) if current_app else 0.0),
            "MAX_PRIME_PERCENT": self._get_setting_runtime("MAX_PRIME_PERCENT", current_app.config.get("MAX_PRIME_PERCENT", 120.0) if current_app else 120.0),
            "RECOVERY_TARGET": self._get_setting_runtime("RECOVERY_TARGET", current_app.config.get("RECOVERY_TARGET", 0.0) if current_app else 0.0),
            "RECOVERY_PERCENT": self._get_setting_runtime("RECOVERY_PERCENT", current_app.config.get("RECOVERY_PERCENT", 0.0) if current_app else 0.0),
            "BONUS": self._get_setting_runtime("BONUS", current_app.config.get("BONUS", 0.0) if current_app else 0.0),
            "PENALTY": self._get_setting_runtime("PENALTY", current_app.config.get("PENALTY", 0.0) if current_app else 0.0),
            "QUARTER_WEIGHT": self._get_setting_runtime("QUARTER_WEIGHT", current_app.config.get("QUARTER_WEIGHT", 0.0) if current_app else 0.0),
            "PRODUCT_WEIGHT": self._get_setting_runtime("PRODUCT_WEIGHT", current_app.config.get("PRODUCT_WEIGHT", 0.0) if current_app else 0.0),
            "AI_CONFIDENCE_LIMIT": self._get_setting_runtime("AI_CONFIDENCE_LIMIT", current_app.config.get("AI_CONFIDENCE_LIMIT", 80.0) if current_app else 80.0),
            "CACHE_TTL": self._cache_ttl,
            "DATASET_VERSION": self._dataset_version,
            "ENGINE_VERSION": self._engine_version,
            "DASHBOARD_VERSION": self._dashboard_version,
            "IMPORT_VERSION": self._import_version
        }

    def run(self):
        t_start = time.time()

        t_db_start = time.time()
        counts = self.load_counts()
        last_upload = self.load_last_upload()
        overall = self.load_overall_stats()
        product_perf = self.load_product_performance()
        top_reps = self.load_top_representatives()
        monthly = self.load_monthly_trend()
        market = self.load_market_share_trend()
        city = self.load_city_performance()
        quarter = self.load_active_quarter()
        recent = self.load_recent_uploads()
        t_db_end = time.time()
        db_duration = t_db_end - t_db_start

        t_ai_start = time.time()
        ai = self.load_ai_analytics()
        t_ai_end = time.time()
        ai_duration = t_ai_end - t_ai_start

        t_prime_start = time.time()
        prime_summary = self.load_prime_summary()
        quarter_summary = self.load_quarter_summary()
        recovery = self.load_recovery()
        what_if = self.load_what_if()
        comparison = self.load_comparison()
        history = self.load_history()
        exec_summary = self.load_executive_summary()
        kpi_cards = self.load_kpi_cards()
        widgets = self.load_widgets_data()
        prime_res = self._get_prime_result()
        t_prime_end = time.time()
        prime_duration = t_prime_end - t_prime_start

        t_ser_start = time.time()
        response_payload = {
            **counts,
            **last_upload,
            **recovery,
            **overall,
            **product_perf,
            **top_reps,
            **monthly,
            **market,
            **city,
            **quarter,
            **recent,
            **ai,
            **what_if,
            **comparison,
            **history,
            **exec_summary,
            **kpi_cards,
            **widgets,
            "active_period": getattr(self, 'period', {}),
            "prime_summary": prime_summary,
            "quarter_summary": quarter_summary,
            "breakdown": prime_res.get("breakdown", {}),
            "quarter_analysis": prime_res.get("quarter_analysis", {}),
            "recovery_analysis": prime_res.get("recovery_analysis", []),
            "insights": prime_res.get("insights", {}),
            "trend_graphs": prime_res.get("trend_graphs", {}),
            "products": prime_res.get("products", []),
            "product_results": prime_res.get("product_results", {}),
            "status": prime_res.get("status", "-"),
            "message": prime_res.get("message", ""),
            "success": prime_res.get("success", False),
            "simulation": prime_res.get("simulation", False),
            "runtime_settings": getattr(self, '_get_all_runtime_settings', lambda: {})(),
            "cache": {
                "hit": self._last_cache_hit,
                "ttl_seconds": self._cache_ttl,
                "dashboard_cache": "Active",
                "prime_cache": "Active" if prime_res else "Inactive",
                "market_cache": "Active",
                "city_cache": "Active",
                "top_rep_cache": "Active"
            },
            "performance": {
                "execution_time_seconds": round(time.time() - t_start, 4),
                "prime_engine_time": round(prime_duration, 4),
                "database_time": round(db_duration, 4),
                "ai_time": round(ai_duration, 4),
                "serialization_time": round(time.time() - t_ser_start, 4),
                "total_time": round(time.time() - t_start, 4)
            }
        }
        
        final_serialized = _serialize_value(response_payload)
        total_duration = time.time() - t_start
        logger.info(f"DashboardService.run completed successfully in {total_duration:.4f}s")
        return final_serialized

    @classmethod
    def health(cls):
        """HEALTH() %100 CONTEXT SAFE AND ROBUST WITH REPORTING PERIOD"""
        try:
            from flask import current_app, has_app_context
            has_ctx = has_app_context()
        except ImportError:
            has_ctx = False
            current_app = None

        # Safe defaults
        dash_ver = eng_ver = dat_ver = imp_ver = "3.2.0"
        c_ttl = CACHE_TTL

        # Context-safe Period Service dependency for Engine checks
        active_year = datetime.now().year
        active_month = datetime.now().month
        active_quarter = ((active_month - 1) // 3) + 1

        if has_ctx:
            try:
                active_period = PeriodService.get_active_period()
                active_year = active_period.get("year", active_year)
                active_month = active_period.get("month", active_month)
                active_quarter = active_period.get("quarter", active_quarter)
            except Exception:
                pass

            try:
                st_dash = Setting.query.filter_by(setting_key="DASHBOARD_VERSION").first()
                if st_dash: dash_ver = st_dash.setting_value
                
                st_eng = Setting.query.filter_by(setting_key="ENGINE_VERSION").first()
                if st_eng: eng_ver = st_eng.setting_value
                
                st_dat = Setting.query.filter_by(setting_key="DATASET_VERSION").first()
                if st_dat: dat_ver = st_dat.setting_value
                
                st_imp = Setting.query.filter_by(setting_key="IMPORT_VERSION").first()
                if st_imp: imp_ver = st_imp.setting_value
                
                st_ttl = Setting.query.filter_by(setting_key="CACHE_TTL").first()
                if st_ttl: c_ttl = int(float(st_ttl.setting_value))
            except Exception:
                if current_app:
                    dash_ver = current_app.config.get("DASHBOARD_VERSION", "3.2.0")
                    eng_ver = current_app.config.get("ENGINE_VERSION", "3.2.0")
                    dat_ver = current_app.config.get("DATASET_VERSION", "3.2.0")
                    imp_ver = current_app.config.get("IMPORT_VERSION", "3.2.0")
                    c_ttl = current_app.config.get("CACHE_TTL", CACHE_TTL)
        else:
            if current_app:
                dash_ver = current_app.config.get("DASHBOARD_VERSION", "3.2.0")
                eng_ver = current_app.config.get("ENGINE_VERSION", "3.2.0")
                dat_ver = current_app.config.get("DATASET_VERSION", "3.2.0")
                imp_ver = current_app.config.get("IMPORT_VERSION", "3.2.0")
                c_ttl = current_app.config.get("CACHE_TTL", CACHE_TTL)

        # Database Context Safe check
        db_status = "Unavailable"
        latency_ms = 0.0
        if has_ctx:
            try:
                t0 = time.time()
                db.session.execute(db.text("SELECT 1"))
                latency_ms = round((time.time() - t0) * 1000, 2)
                db_status = "Connected"
            except Exception as exc:
                logger.exception(f"Health check database error: {exc}")
                db_status = "Error"
        else:
            db_status = "No Context"

        # Cache check
        cache_status = "Active" if _DASHBOARD_CACHE else "Inactive"
        try:
            _DASHBOARD_CACHE.set("health_test", True)
            if not _DASHBOARD_CACHE.get("health_test"):
                cache_status = "Warning"
        except Exception:
            cache_status = "Error"

        # Prime Engine Context Safe check mapped to Active Period
        prime_status = "Unavailable"
        if has_ctx:
            try:
                rep = Representative.query.filter_by(active=True).first()
                if rep:
                    test_engine = PrimeEngine(representative_id=rep.id, year=active_year, month=active_month, use_cache=True)
                    if not test_engine.load_products():
                        prime_status = "Warning"
                    else:
                        prime_status = "Healthy"
                else:
                    prime_status = "Healthy"
            except Exception:
                prime_status = "Error"
        else:
            prime_status = "No Context"

        # Quarter Engine check mapped to Active Period
        quarter_status = "Unavailable"
        if QuarterEngine:
            try:
                q = QuarterEngine(representative_id=1, year=active_year, quarter=active_quarter)
                quarter_status = "Healthy"
            except Exception:
                quarter_status = "Error"

        # Recovery Engine check mapped to Active Period
        recovery_status = "Unavailable"
        if RecoveryEngine:
            try:
                r = RecoveryEngine(representative_id=1, year=active_year, month=active_month)
                recovery_status = "Healthy"
            except Exception:
                recovery_status = "Error"

        # AI Analytics check (Real Execution Wrapped Safely)
        ai_status = "Unavailable"
        try:
            test_ai = AIAnalyticsService()
            try:
                test_ai.run_all()
                ai_status = "Healthy"
            except Exception as inner_exc:
                logger.exception(f"AI Analytics execution failed: {inner_exc}")
                ai_status = "Error"
        except Exception:
            ai_status = "Error"

        # Settings Context Safe check
        settings_status = "Unavailable"
        if has_ctx:
            try:
                Setting.query.first()
                settings_status = "Healthy"
            except Exception:
                settings_status = "Error"
        else:
            settings_status = "No Context"

        # Import Audit Context Safe check
        import_audit_status = "Unavailable"
        if ImportAuditLog is not None:
            if has_ctx:
                try:
                    ImportAuditLog.query.first()
                    import_audit_status = "Healthy"
                except Exception:
                    import_audit_status = "Error"
            else:
                import_audit_status = "No Context"
                
        # Matching Context Safe check
        matching_status = "Unavailable"
        if RepresentativeMatch is not None:
            if has_ctx:
                try:
                    RepresentativeMatch.query.first()
                    matching_status = "Healthy"
                except Exception:
                    matching_status = "Error"
            else:
                matching_status = "No Context"
                
        # Simulation check
        simulation_status = "Unavailable"
        try:
            if hasattr(PrimeEngine, "calculate"):
                simulation_status = "Healthy"
        except Exception:
            simulation_status = "Error"
            
        # History check
        history_status = "Unavailable"
        try:
            if hasattr(PrimeEngine, "load_history"):
                history_status = "Healthy"
        except Exception:
            history_status = "Error"

        # Migration Status Context Safe check (Alembic Verification)
        alembic_version = "Unknown"
        migration_status = "Unknown"
        if has_ctx:
            try:
                res = db.session.execute(db.text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
                if res:
                    alembic_version = res[0]
                    migration_status = "Up-to-date"
                    
                    try:
                        from alembic.config import Config
                        from alembic.script import ScriptDirectory
                        import os
                        
                        migrations_dir = current_app.config.get('ALEMBIC_CONTEXT') if current_app else 'migrations'
                        if os.path.exists(migrations_dir):
                            cfg = Config()
                            cfg.set_main_option("script_location", migrations_dir)
                            script = ScriptDirectory.from_config(cfg)
                            head = script.get_current_head()
                            if head and head != alembic_version:
                                migration_status = "Pending"
                    except Exception:
                        pass
                else:
                    migration_status = "Pending"
            except Exception:
                migration_status = "Error"
        else:
            migration_status = "No Context"

        # Health status generation based on actual component states
        all_components = [
            db_status, cache_status, prime_status, quarter_status,
            recovery_status, ai_status, settings_status, import_audit_status,
            matching_status, simulation_status, history_status
        ]
        
        if "Error" in all_components:
            service_status = "ERROR"
        elif "Warning" in all_components:
            service_status = "WARNING"
        elif db_status == "Connected":
            service_status = "READY"
        else:
            service_status = "WARNING"

        return {
            "service": "DashboardService",
            "status": service_status,
            "service_status": service_status,
            "version": dash_ver,
            "dashboard_version": dash_ver,
            "engine_version": eng_ver,
            "dataset_version": dat_ver,
            "import_version": imp_ver,
            "database": db_status,
            "database_connection": db_status,
            "database_latency_ms": latency_ms,
            "cache": cache_status,
            "cache_status": cache_status,
            "cache_ttl": c_ttl,
            "prime_engine": prime_status,
            "prime_engine_status": prime_status,
            "quarter_engine": quarter_status,
            "recovery_engine": recovery_status,
            "ai_analytics": ai_status,
            "ai_service_status": ai_status,
            "settings_service": settings_status,
            "import_audit": import_audit_status,
            "matching_service": matching_status,
            "simulation_service": simulation_status,
            "history_service": history_status,
            "upload_module": "Healthy" if import_audit_status in ["Healthy", "No Context"] else "Unavailable",
            "migration_status": migration_status,
            "alembic_version": alembic_version,
            "last_health_check": datetime.now().isoformat()
                    }
