"""V3 Architecture: Dashboard Query Layer (OLAP)
=============================================
Enterprise-grade read-only data access layer for the Dashboard.
Strictly devoid of business logic, DTO instantiation, and DML operations.
Returns heavily optimized, raw SQLAlchemy Rows.
Integrates with AggregateBuilder and DashboardFilterParams.
"""

import hashlib
from typing import Any, Optional, Sequence

from sqlalchemy import func, desc, and_, case
from sqlalchemy.engine.row import Row

from app.extensions import db
from app.models import (
    CompetitionData,
    IMSUpload,
    Product,
    Representative, 
    Target, 
    IMSSummary
    , IMSRawData
)
from app.query.base_query import AggregateBuilder
from app.query.filters import DashboardFilterParams, DashboardFilter


class DashboardQuery:
    """
    Strict Read-Only Data Access Layer for Dashboard Service.
    Executes heavily optimized group-by queries via AggregateBuilder.
    Returns raw SQLAlchemy Rows to be mapped by the Mapper/Service layer.
    """

    def __init__(self, session=None):
        self.session = session or db.session

    def _generate_cache_signature(
        self, 
        query_name: str, 
        filters: Optional[DashboardFilterParams], 
        limit: Optional[int], 
        offset: Optional[int]
    ) -> str:
        """
        Standardized cache key generator mechanism for V3 Cache Layer integration.
        Provides a deterministic signature string representing the exact query state.
        DashboardCache layer will use this hook to set/get Redis keys.
        """
        signature_parts = [f"q:{query_name}"]
        
        if filters:
            for key, value in sorted(filters.__dict__.items()):
                if value is not None:
                    signature_parts.append(f"{key}={value}")
                    
        if limit is not None:
            signature_parts.append(f"l:{limit}")
        if offset is not None:
            signature_parts.append(f"o:{offset}")
            
        raw_signature = "|".join(signature_parts)
        return hashlib.md5(raw_signature.encode('utf-8')).hexdigest()

    def load_top_representatives(
        self, 
        filters: Optional[DashboardFilterParams] = None, 
        limit: Optional[int] = 10, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> Sequence[Row]:
        """
        Retrieves top performing representatives based on total realization.
        Returns raw SQLAlchemy Rows to avoid ORM instantiation overhead.
        """
        default_order = order_by if order_by is not None else desc("total_tl")
        
        joins = [
            (Representative, IMSSummary.representative_id == Representative.id, False),
            (Target, 
                and_(
                    Target.representative_id == Representative.id,
                    Target.product_id == IMSSummary.product_id,
                    Target.year == IMSSummary.year,
                    Target.month == IMSSummary.month,
                ), 
                True
            )
        ]

        select_cols = [
            Representative.id,
            Representative.rep_name,
            Representative.city,
            func.sum(IMSSummary.tl).label("total_tl"),
            func.sum(IMSSummary.bonus_amount).label("bonus"),
            func.sum(Target.tl_target).label("target_tl")
        ]

        group_cols = [
            Representative.id, 
            Representative.rep_name, 
            Representative.city
        ]

        # Standardized Cache Hook integration ready for implementation
        # cache_key = self._generate_cache_signature("top_reps", filters, limit, offset)

        query = AggregateBuilder.build(
            session=self.session,
            select_entities=select_cols,
            group_by_entities=group_cols,
            joins=joins,
            filter_callable=lambda q: DashboardFilter.apply(q, filters).filter(~Representative.rep_code.like("UNASSIGNED%")),
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        return query.all()

    def load_period_performance(self, filters: Optional[DashboardFilterParams] = None) -> Optional[Row]:
        """Returns the unjoined period totals used by the global dashboard."""
        query = self.session.query(
            func.coalesce(func.sum(IMSSummary.tl), 0.0).label("realization_tl"),
            func.coalesce(func.sum(IMSSummary.target_tl), 0.0).label("target_tl"),
        )
        return DashboardFilter.apply(query, filters).one()

    def load_national_dashboard_metrics(self, filters: Optional[DashboardFilterParams] = None) -> dict:
        """Return reconciled National totals captured from the source workbook."""
        if not filters or filters.year is None or filters.month is None:
            return {}
        upload_id = self.session.query(IMSUpload.id).filter(
            IMSUpload.year == filters.year, IMSUpload.month == filters.month,
            IMSUpload.status == "COMPLETED"
        ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id:
            return {}
        balance_rows = self.session.query(
            Product.id, Product.product_name, IMSRawData.unit, IMSRawData.tl
        ).join(Product, Product.id == IMSRawData.product_id).filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.sheet_type == "dashboard_balance_national"
        ).all()
        if not balance_rows:
            return {}
        unit_by_product = dict(self.session.query(
            IMSRawData.product_id, IMSRawData.unit
        ).filter(IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_weekly_units").all())
        products = [{
            "product_id": row[0], "product_name": row[1],
            "target_tl": round(float(row[2] or 0), 2),
            "actual_tl": round(float(row[3] or 0), 2),
            "unit_actual": round(float(unit_by_product.get(row[0], 0) or 0), 2),
        } for row in balance_rows]
        target = sum(item["target_tl"] for item in products)
        actual = sum(item["actual_tl"] for item in products)
        for item in products:
            item["realization_percent"] = round(item["actual_tl"] * 100 / item["target_tl"], 1) if item["target_tl"] else 0.0
        return {
            "source": "BAKİYE / TTS HAFTALIK ÇIKIŞLARI · NATIONAL",
            "target_tl": round(target, 2), "actual_tl": round(actual, 2),
            "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
            "unit_actual": round(sum(item["unit_actual"] for item in products), 2),
            "products": products,
        }

    def load_product_performance(
        self, filters: Optional[DashboardFilterParams] = None
    ) -> Sequence[Row]:
        """Returns product-level totals without multiplying target rows in a join."""
        query = (
            self.session.query(
                Product.id.label("product_id"),
                Product.product_name.label("product_name"),
                func.coalesce(func.sum(IMSSummary.tl), 0.0).label("realization_tl"),
                func.coalesce(func.sum(IMSSummary.target_tl), 0.0).label("target_tl"),
            )
            .join(Product, Product.id == IMSSummary.product_id)
        )
        return (
            DashboardFilter.apply(query, filters)
            .group_by(Product.id, Product.product_name)
            .order_by(desc("realization_tl"))
            .all()
        )

    def load_city_performance(
        self, 
        filters: Optional[DashboardFilterParams] = None, 
        limit: Optional[int] = None, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> Sequence[Row]:
        """
        Retrieves territory performance aggregated by Representative City.
        Returns raw SQLAlchemy Rows.
        """
        default_order = order_by if order_by is not None else desc("total_tl")

        joins = [
            (Representative, IMSSummary.representative_id == Representative.id, False),
            (Target, 
                and_(
                    Target.representative_id == Representative.id,
                    Target.year == IMSSummary.year,
                    Target.month == IMSSummary.month
                ), 
                True
            )
        ]

        select_cols = [
            Representative.city,
            func.sum(IMSSummary.tl).label("total_tl"),
            func.sum(Target.tl_target).label("target_tl"),
            func.count(Representative.id.distinct()).label("rep_count")
        ]

        group_cols = [Representative.city]

        # Apply specific city presence constraint via lambda wrapper around the generic filter
        def _apply_city_filters(q):
            q = DashboardFilter.apply(q, filters)
            return q.filter(Representative.city.isnot(None))

        query = AggregateBuilder.build(
            session=self.session,
            select_entities=select_cols,
            group_by_entities=group_cols,
            joins=joins,
            filter_callable=_apply_city_filters,
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        return query.all()

    def load_market_share_trend(
        self, 
        filters: Optional[DashboardFilterParams] = None, 
        limit: Optional[int] = 12, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> Sequence[Row]:
        """
        Retrieves the chronological progression of average market share.
        Returns raw SQLAlchemy Rows.
        """
        # Market-share is supplied by the dedicated competition PP sheets;
        # IMSSummary intentionally contains no PP value for brick sales.
        query = self.session.query(
            CompetitionData.year,
            CompetitionData.month,
            func.avg(CompetitionData.metric_value).label("avg_share"),
        ).filter(
            CompetitionData.metric_type == "MARKET_SHARE",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
        )
        if filters and filters.year is not None:
            query = query.filter(CompetitionData.year == filters.year)
        if filters and filters.month is not None:
            query = query.filter(CompetitionData.month == filters.month)
        return (
            query.group_by(CompetitionData.year, CompetitionData.month)
            .order_by(order_by or desc(CompetitionData.year), desc(CompetitionData.month))
            .limit(limit)
            .offset(offset or 0)
            .all()
        )

    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None) -> Sequence[Row]:
        """Non-duplicated target/IMS realization by Excel region code."""
        query = self.session.query(Representative.region.label("region"), Representative.city.label("city"), func.coalesce(func.sum(Target.unit_target), 0.0).label("unit_target"), func.coalesce(func.sum(IMSSummary.unit), 0.0).label("unit_actual"), func.coalesce(func.sum(Target.tl_target), 0.0).label("tl_target"), func.coalesce(func.sum(IMSSummary.tl), 0.0).label("tl_actual"), func.count(Representative.id.distinct()).label("representative_count")).join(Representative, Representative.id == Target.representative_id).outerjoin(IMSSummary, and_(IMSSummary.representative_id == Target.representative_id, IMSSummary.product_id == Target.product_id, IMSSummary.year == Target.year, IMSSummary.month == Target.month)).filter(Representative.region.isnot(None))
        if filters and filters.year is not None: query = query.filter(Target.year == filters.year)
        if filters and filters.month is not None: query = query.filter(Target.month == filters.month)
        return query.group_by(Representative.region, Representative.city).order_by(Representative.region.asc()).all()

    def load_competition_overview(self, filters: Optional[DashboardFilterParams] = None) -> Sequence[Row]:
        """Aggregate competition metrics from the latest completed workbook only."""
        if not filters or filters.year is None or filters.month is None:
            return []
        latest_upload_id = (
            self.session.query(IMSUpload.id)
            .filter(IMSUpload.year == filters.year, IMSUpload.month == filters.month, IMSUpload.status == "COMPLETED")
            .order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        )
        if not latest_upload_id:
            return []
        return (
            self.session.query(
                CompetitionData.product_group.label("product_group"),
                func.coalesce(func.sum(case((CompetitionData.metric_type == "TL", CompetitionData.metric_value), else_=0.0)), 0.0).label("market_tl"),
                func.avg(case((CompetitionData.metric_type == "MARKET_SHARE", CompetitionData.metric_value), else_=None)).label("market_share"),
            )
            .filter(CompetitionData.upload_id == latest_upload_id, CompetitionData.is_subtotal.is_(False), CompetitionData.is_grand_total.is_(False), CompetitionData.metric_type.in_(("TL", "MARKET_SHARE")))
            .group_by(CompetitionData.product_group).order_by(desc("market_tl")).all()
        )

    def load_competitor_product_rows(self, filters: Optional[DashboardFilterParams] = None) -> Sequence[Row]:
        if not filters or filters.year is None or filters.month is None: return []
        upload_id=self.session.query(IMSUpload.id).filter(IMSUpload.year==filters.year,IMSUpload.month==filters.month,IMSUpload.status=="COMPLETED").order_by(desc(IMSUpload.completed_at),desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id: return []
        return self.session.query(CompetitionData.territory,CompetitionData.product_group,CompetitionData.product_name,func.sum(CompetitionData.metric_value).label("sales_tl")).filter(CompetitionData.upload_id==upload_id,CompetitionData.metric_type=="TL",CompetitionData.is_subtotal.is_(False),CompetitionData.is_grand_total.is_(False),~func.upper(CompetitionData.product_name).like("%GRAND%"),~func.upper(CompetitionData.product_name).like("%SUBTOTAL%")).group_by(CompetitionData.territory,CompetitionData.product_group,CompetitionData.product_name).all()

    def load_history(
        self, 
        filters: Optional[DashboardFilterParams] = None, 
        limit: Optional[int] = 6, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> Sequence[Row]:
        """
        Retrieves chronological progression of overall sales performance and bonuses.
        Returns raw SQLAlchemy Rows.
        """
        default_order = order_by if order_by is not None else [
            desc(IMSSummary.year), 
            desc(IMSSummary.month)
        ]

        select_cols = [
            IMSSummary.year,
            IMSSummary.month,
            func.sum(IMSSummary.tl).label("total_tl"),
            func.sum(IMSSummary.bonus_amount).label("bonus")
        ]

        group_cols = [IMSSummary.year, IMSSummary.month]

        query = AggregateBuilder.build(
            session=self.session,
            select_entities=select_cols,
            group_by_entities=group_cols,
            filter_callable=lambda q: DashboardFilter.apply(q, filters),
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        return query.all()
