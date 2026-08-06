"""Professional and high-performance Competition API & Analytics Layer.

Designed with clean architecture separating queries, services, serializers, and routes.
Production refactored for strict security, telemetry isolation, and PEP8 compliance.
"""

import logging
import time
from functools import wraps
from typing import Dict, Any, List, Optional, Tuple, Callable
from flask import Blueprint, request, jsonify, Response, g
from sqlalchemy import func, distinct, desc, asc, case, tuple_
from app.extensions import db
from app.models import CompetitionData, IMSUpload

logger = logging.getLogger(__name__)

competition_bp = Blueprint("competition_api", __name__, url_prefix="/api/competition")


# ==========================================
# 0. DECORATORS & RESPONSE HELPERS
# ==========================================

def optional_cache(timeout: int = 300) -> Callable:
    """Decorator hook for future caching integration (Flask-Caching / Redis)."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # TODO: cache_key = f.__name__; cached = cache.get(cache_key); if cached: return cached
            response = f(*args, **kwargs)
            # TODO: cache.set(cache_key, response, timeout=timeout)
            return response
        return wrapper
    return decorator


def handle_endpoint_timing(endpoint_name: str) -> Callable:
    """Reusable decorator for precise execution timing, metric logging, and centralized error handling."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Tuple[Response, int]:
            start_time = time.time()
            client_ip = request.remote_addr or "unknown"
            filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
            upload_id = filters.get("upload_id")
            
            try:
                result = f(*args, **kwargs)
                if isinstance(result, tuple):
                    resp, status_code = result
                else:
                    resp, status_code = result, 200

                exec_time = round(time.time() - start_time, 4)
                record_count = 0
                sql_duration = getattr(g, "sql_duration", 0.0)

                if hasattr(resp, "get_json"):
                    payload = resp.get_json()
                    if isinstance(payload, dict):
                        record_count = payload.get("count", 0)

                logger.info(
                    "Endpoint: %s | Filters: %s | Upload ID: %s | Count: %d | SQL Duration: %.4fs | Execution Time: %.4fs | Client IP: %s",
                    endpoint_name, filters, upload_id, record_count, sql_duration, exec_time, client_ip
                )
                return resp, status_code

            except ValueError as ve:
                exec_time = round(time.time() - start_time, 4)
                logger.warning("ValueError in %s: %s (Time: %.4fs)", endpoint_name, ve, exec_time)
                return CompetitionAnalyticsService.error_response(str(ve), ve.__class__.__name__, 400)
            except LookupError as le:
                exec_time = round(time.time() - start_time, 4)
                logger.warning("LookupError in %s: %s (Time: %.4fs)", endpoint_name, le, exec_time)
                return CompetitionAnalyticsService.error_response(str(le), le.__class__.__name__, 404)
            except Exception as exc:
                exec_time = round(time.time() - start_time, 4)
                logger.error("Unexpected error in %s: %s (Time: %.4fs)", endpoint_name, exc, exc_info=True)
                return CompetitionAnalyticsService.error_response(str(exc), exc.__class__.__name__, 500)
        return wrapper
    return decorator


# ==========================================
# 1. QUERY BUILDER & REPOSITORY LAYER
# ==========================================

class CompetitionQueryBuilder:
    """Encapsulates SQLAlchemy aggregation and filtering queries for competition data."""

    @staticmethod
    def _build_metric_case(metric_type: str) -> Any:
        """Helper to create metric sum case clauses without duplication."""
        return func.sum(case((CompetitionData.metric_type == metric_type, CompetitionData.metric_value), else_=0))

    @staticmethod
    def _get_sort_map() -> Dict[str, Any]:
        """Helper to provide consistent sorting columns map."""
        return {
            "product_name": CompetitionData.product_name,
            "total_units": CompetitionQueryBuilder._build_metric_case('UNIT'),
            "total_tl": CompetitionQueryBuilder._build_metric_case('TL'),
            "avg_value": func.avg(CompetitionData.metric_value)
        }

    @staticmethod
    def apply_filters(query: Any, filters: Dict[str, Any]) -> Any:
        """Apply optional standard filters dynamically."""
        if filters.get("year") is not None:
            query = query.filter(CompetitionData.year == filters["year"])
        if filters.get("month") is not None:
            query = query.filter(CompetitionData.month == filters["month"])
        if filters.get("week_number") is not None:
            query = query.filter(CompetitionData.week_number == filters["week_number"])
        if filters.get("upload_id") is not None:
            query = query.filter(CompetitionData.upload_id == filters["upload_id"])
        if filters.get("territory"):
            query = query.filter(CompetitionData.territory == filters["territory"])
        if filters.get("subterritory"):
            query = query.filter(CompetitionData.subterritory == filters["subterritory"])
        if filters.get("product_group"):
            query = query.filter(CompetitionData.product_group == filters["product_group"])
        if filters.get("product_name"):
            query = query.filter(CompetitionData.product_name == filters["product_name"])
        if filters.get("metric_type"):
            query = query.filter(CompetitionData.metric_type == filters["metric_type"])
        return query

    @classmethod
    def get_summary_metrics(cls, filters: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
        """Fetch summary statistics filtered by optional parameters with precise SQL timing."""
        start_time = time.time()
        
        row = db.session.query(
            func.count(CompetitionData.id),
            func.count(func.distinct(CompetitionData.upload_id)),
            func.count(func.distinct(CompetitionData.product_name)),
            func.count(func.distinct(CompetitionData.product_group)),
            func.count(func.distinct(CompetitionData.territory)),
            func.count(func.distinct(CompetitionData.subterritory))
        )
        row = cls.apply_filters(row, filters).first()

        last_import_date = None
        last_upload_id = None

        try:
            if hasattr(IMSUpload, "competition_imported") and hasattr(IMSUpload, "competition_imported_at"):
                upload_q = db.session.query(IMSUpload).filter(IMSUpload.competition_imported.is_(True))
                if filters.get("upload_id") is not None:
                    upload_q = upload_q.filter(IMSUpload.id == filters["upload_id"])
                last_upload = upload_q.order_by(desc(IMSUpload.competition_imported_at)).first()
                if last_upload:
                    last_upload_id = last_upload.id
                    if last_upload.competition_imported_at:
                        last_import_date = last_upload.competition_imported_at.isoformat()
                    elif hasattr(last_upload, "uploaded_at") and last_upload.uploaded_at:
                        last_import_date = last_upload.uploaded_at.isoformat()
        except Exception as exc:
            logger.warning("Could not query IMSUpload competition metadata: %s", exc)

        if not last_import_date and hasattr(CompetitionData, "created_at"):
            created_q = cls.apply_filters(db.session.query(func.max(CompetitionData.created_at)), filters)
            fallback_created = created_q.scalar()
            if fallback_created:
                last_import_date = fallback_created.isoformat()

        if not last_upload_id:
            upload_id_q = cls.apply_filters(db.session.query(func.max(CompetitionData.upload_id)), filters)
            fallback_upload = upload_id_q.scalar()
            if fallback_upload:
                last_upload_id = fallback_upload

        sql_duration = time.time() - start_time

        summary = {
            "total_records": row[0] or 0,
            "total_uploads": row[1] or 0,
            "total_products": row[2] or 0,
            "total_product_groups": row[3] or 0,
            "total_territories": row[4] or 0,
            "total_subterritories": row[5] or 0,
            "last_import_date": last_import_date,
            "last_upload_id": last_upload_id
        }
        return summary, round(sql_duration, 4)

    @classmethod
    def get_products_aggregation(cls, filters: Dict[str, Any], sort_by: str, sort_order: str, page: int, per_page: int) -> Tuple[List[Any], int, float]:
        """Aggregate product statistics with tuple_ support and deterministic ordering."""
        start_time = time.time()

        query = db.session.query(
            CompetitionData.product_name,
            CompetitionData.product_group,
            cls._build_metric_case('UNIT').label('total_units'),
            cls._build_metric_case('TL').label('total_tl'),
            func.avg(CompetitionData.metric_value).label('avg_value'),
            func.min(CompetitionData.metric_value).label('min_value'),
            func.max(CompetitionData.metric_value).label('max_value')
        )

        query = cls.apply_filters(query, filters)
        query = query.group_by(CompetitionData.product_name, CompetitionData.product_group)

        sort_column_map = cls._get_sort_map()
        sort_col = sort_column_map.get(sort_by, CompetitionData.product_name)
        
        normalized_order = sort_order.strip().lower()
        if normalized_order not in ("asc", "desc"):
            normalized_order = "asc"
            
        if normalized_order == 'desc':
            query = query.order_by(desc(sort_col), desc(CompetitionData.product_name))
        else:
            query = query.order_by(asc(sort_col), asc(CompetitionData.product_name))

        count_query = db.session.query(func.count(distinct(tuple_(CompetitionData.product_name, CompetitionData.product_group))))
        count_query = cls.apply_filters(count_query, filters)
        total_count = count_query.scalar() or 0

        pagination_query = query.offset((page - 1) * per_page).limit(per_page)
        results = pagination_query.all()

        sql_duration = time.time() - start_time
        return results, total_count, round(sql_duration, 4)

    @classmethod
    def get_groups_aggregation(cls, filters: Dict[str, Any]) -> Tuple[List[Any], float]:
        """Aggregate data grouped by product groups with deterministic sorting."""
        start_time = time.time()
        query = db.session.query(
            CompetitionData.product_group,
            func.count(func.distinct(CompetitionData.product_name)).label('product_count'),
            func.sum(CompetitionData.metric_value).label('total_value')
        )
        query = cls.apply_filters(query, filters)
        query = query.group_by(CompetitionData.product_group).order_by(desc('total_value'), asc(CompetitionData.product_group))
        results = query.all()
        sql_duration = time.time() - start_time
        return results, round(sql_duration, 4)

    @classmethod
    def get_territories_aggregation(cls, filters: Dict[str, Any]) -> Tuple[List[Any], float]:
        """Aggregate data grouped by territories and subterritories with deterministic sorting."""
        start_time = time.time()
        query = db.session.query(
            CompetitionData.territory,
            CompetitionData.subterritory,
            cls._build_metric_case('UNIT').label('total_units'),
            cls._build_metric_case('TL').label('total_tl'),
            func.count(func.distinct(CompetitionData.product_name)).label('product_count')
        )
        query = cls.apply_filters(query, filters)
        query = query.group_by(CompetitionData.territory, CompetitionData.subterritory).order_by(asc(CompetitionData.territory), asc(CompetitionData.subterritory))
        results = query.all()
        sql_duration = time.time() - start_time
        return results, round(sql_duration, 4)

    @classmethod
    def get_trend_aggregation(cls, filters: Dict[str, Any]) -> Tuple[List[Any], float]:
        """Aggregate monthly trend data with deterministic chronological ordering."""
        start_time = time.time()
        query = db.session.query(
            CompetitionData.year,
            CompetitionData.month,
            cls._build_metric_case('UNIT').label('total_units'),
            cls._build_metric_case('TL').label('total_tl')
        )
        query = cls.apply_filters(query, filters)
        query = query.group_by(CompetitionData.year, CompetitionData.month).order_by(asc(CompetitionData.year), asc(CompetitionData.month))
        results = query.all()
        sql_duration = time.time() - start_time
        return results, round(sql_duration, 4)

    @classmethod
    def get_market_aggregation(cls, filters: Dict[str, Any]) -> Tuple[List[Any], float]:
        """Extract market reference data (PAZAR sheet records) with deterministic sorting."""
        start_time = time.time()
        query = db.session.query(CompetitionData).filter(CompetitionData.sheet_name == "PAZAR")
        query = cls.apply_filters(query, filters)
        query = query.order_by(asc(CompetitionData.product_name), asc(CompetitionData.id))
        results = query.all()
        sql_duration = time.time() - start_time
        return results, round(sql_duration, 4)

    @classmethod
    def get_distinct_filter_options(cls, upload_id: Optional[int] = None) -> Tuple[Dict[str, List[Any]], float]:
        """Fetch distinct filter options utilizing a unified helper method."""
        start_time = time.time()

        def _get_distinct_col(column_attr: Any) -> List[Any]:
            col_q = db.session.query(distinct(column_attr))
            if upload_id is not None:
                col_q = col_q.filter(CompetitionData.upload_id == upload_id)
            return [r[0] for r in col_q.order_by(column_attr).all()]

        options = {
            "products": _get_distinct_col(CompetitionData.product_name),
            "product_groups": _get_distinct_col(CompetitionData.product_group),
            "territories": _get_distinct_col(CompetitionData.territory),
            "subterritories": _get_distinct_col(CompetitionData.subterritory),
            "years": _get_distinct_col(CompetitionData.year),
            "months": _get_distinct_col(CompetitionData.month),
            "metric_types": _get_distinct_col(CompetitionData.metric_type)
        }
        sql_duration = time.time() - start_time
        return options, round(sql_duration, 4)


# ==========================================
# 2. SERIALIZER / FORMATTER LAYER
# ==========================================

class CompetitionSerializer:
    """Formats query outputs into frontend-friendly JSON structures."""

    @staticmethod
    def serialize_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
        return summary

    @staticmethod
    def serialize_products(results: List[Any]) -> List[Dict[str, Any]]:
        return [{
            "product_name": row.product_name,
            "product_group": row.product_group,
            "total_units": float(row.total_units or 0.0),
            "total_tl": float(row.total_tl or 0.0),
            "avg_value": float(row.avg_value or 0.0),
            "min_value": float(row.min_value or 0.0),
            "max_value": float(row.max_value or 0.0)
        } for row in results]

    @staticmethod
    def serialize_groups(results: List[Any]) -> List[Dict[str, Any]]:
        return [{
            "product_group": row.product_group,
            "product_count": row.product_count,
            "total_value": float(row.total_value or 0.0)
        } for row in results]

    @staticmethod
    def serialize_territories(results: List[Any]) -> List[Dict[str, Any]]:
        return [{
            "territory": row.territory,
            "subterritory": row.subterritory,
            "total_units": float(row.total_units or 0.0),
            "total_tl": float(row.total_tl or 0.0),
            "product_count": row.product_count
        } for row in results]

    @staticmethod
    def serialize_trend(results: List[Any]) -> List[Dict[str, Any]]:
        return [{
            "year": row.year,
            "month": row.month,
            "period": f"{row.year}-{row.month:02d}",
            "total_units": float(row.total_units or 0.0),
            "total_tl": float(row.total_tl or 0.0)
        } for row in results]

    @staticmethod
    def serialize_market(results: List[Any]) -> List[Dict[str, Any]]:
        return [{
            "id": row.id,
            "sheet_name": row.sheet_name,
            "product_name": row.product_name,
            "territory": row.territory,
            "metric_type": row.metric_type,
            "metric_value": float(row.metric_value or 0.0)
        } for row in results]


# ==========================================
# 3. SERVICE LAYER
# ==========================================

class CompetitionAnalyticsService:
    """Orchestrates query execution and request parameter validation."""

    @staticmethod
    def extract_filters_from_request(req_args: Any) -> Dict[str, Any]:
        filters: Dict[str, Any] = {}
        for key in ["year", "month", "week_number", "upload_id"]:
            if req_args.get(key):
                try:
                    filters[key] = int(req_args.get(key))
                except ValueError:
                    raise ValueError(f"Invalid numeric parameter format for '{key}'.")
        for key in ["territory", "subterritory", "product_group", "product_name", "metric_type"]:
            if req_args.get(key):
                filters[key] = req_args.get(key)
        return filters

    @staticmethod
    def extract_pagination_from_request(req_args: Any) -> Tuple[int, int]:
        """Extract and validate pagination parameters with strict bounds."""
        try:
            page = int(req_args.get("page", 1))
        except (ValueError, TypeError):
            raise ValueError("Invalid parameter format for 'page'. Must be an integer.")

        if page < 1:
            raise ValueError("Parameter 'page' must be greater than or equal to 1.")

        try:
            per_page = int(req_args.get("per_page", 20))
        except (ValueError, TypeError):
            raise ValueError("Invalid parameter format for 'per_page'. Must be an integer.")

        if per_page < 1:
            per_page = 1
        elif per_page > 100:
            per_page = 100

        return page, per_page

    @staticmethod
    def success_response(data: List[Any], count: int, filters: Dict[str, Any], extra: Optional[Dict[str, Any]] = None, sql_duration: float = 0.0) -> Tuple[Response, int]:
        """Centralized helper for standard success responses storing internal SQL duration in flask.g."""
        g.sql_duration = sql_duration
        payload = {
            "success": True,
            "count": count,
            "filters": filters,
            "data": data
        }
        if extra:
            payload.update(extra)
        return jsonify(payload), 200

    @staticmethod
    def error_response(message: str, error_type: str, status_code: int) -> Tuple[Response, int]:
        """Centralized helper for standard error responses."""
        return jsonify({
            "success": False,
            "message": message,
            "details": None,
            "error_type": error_type
        }), status_code


# ==========================================
# 4. ROUTE / CONTROLLER LAYER
# ==========================================

@competition_bp.route("/summary", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_summary")
def get_summary() -> Tuple[Response, int]:
    """Get overarching competition summary metrics."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    summary_data, sql_duration = CompetitionQueryBuilder.get_summary_metrics(filters)
    data = CompetitionSerializer.serialize_summary(summary_data)
    return CompetitionAnalyticsService.success_response([data], 1, filters, sql_duration=sql_duration)


@competition_bp.route("/products", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_products")
def get_products() -> Tuple[Response, int]:
    """Get aggregated product statistics with filtering, sorting, and pagination."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    page, per_page = CompetitionAnalyticsService.extract_pagination_from_request(request.args)

    sort_by = request.args.get("sort_by", "product_name")
    if sort_by not in ("product_name", "total_units", "total_tl", "avg_value"):
        raise ValueError(f"Invalid sort_by column '{sort_by}'. Allowed values: product_name, total_units, total_tl, avg_value.")
        
    sort_order = request.args.get("sort_order", "asc")

    results, total_count, sql_duration = CompetitionQueryBuilder.get_products_aggregation(
        filters, sort_by, sort_order, page, per_page
    )
    data = CompetitionSerializer.serialize_products(results)

    return CompetitionAnalyticsService.success_response(
        data, 
        total_count, 
        filters, 
        {"page": page, "per_page": per_page},
        sql_duration=sql_duration
    )


@competition_bp.route("/groups", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_groups")
def get_groups() -> Tuple[Response, int]:
    """Get product group aggregated metrics."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    results, sql_duration = CompetitionQueryBuilder.get_groups_aggregation(filters)
    data = CompetitionSerializer.serialize_groups(results)

    return CompetitionAnalyticsService.success_response(data, len(data), filters, sql_duration=sql_duration)


@competition_bp.route("/territories", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_territories")
def get_territories() -> Tuple[Response, int]:
    """Get territory and subterritory aggregated metrics."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    results, sql_duration = CompetitionQueryBuilder.get_territories_aggregation(filters)
    data = CompetitionSerializer.serialize_territories(results)

    return CompetitionAnalyticsService.success_response(data, len(data), filters, sql_duration=sql_duration)


@competition_bp.route("/trend", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_trend")
def get_trend() -> Tuple[Response, int]:
    """Get monthly trend analytics for charts."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    results, sql_duration = CompetitionQueryBuilder.get_trend_aggregation(filters)
    data = CompetitionSerializer.serialize_trend(results)

    return CompetitionAnalyticsService.success_response(data, len(data), filters, sql_duration=sql_duration)


@competition_bp.route("/market", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_market")
def get_market() -> Tuple[Response, int]:
    """Get market reference records (PAZAR sheet)."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    results, sql_duration = CompetitionQueryBuilder.get_market_aggregation(filters)
    data = CompetitionSerializer.serialize_market(results)

    return CompetitionAnalyticsService.success_response(data, len(data), filters, sql_duration=sql_duration)


@competition_bp.route("/filter-options", methods=["GET"])
@optional_cache(timeout=300)
@handle_endpoint_timing("get_filter_options")
def get_filter_options() -> Tuple[Response, int]:
    """Get distinct filter options for dashboard dropdowns."""
    filters = CompetitionAnalyticsService.extract_filters_from_request(request.args)
    upload_id = filters.get("upload_id")
    options, sql_duration = CompetitionQueryBuilder.get_distinct_filter_options(upload_id=upload_id)

    return CompetitionAnalyticsService.success_response([options], 1, filters, sql_duration=sql_duration)
