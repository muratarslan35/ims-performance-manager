V3 Architecture: Dashboard Query Layer (OLAP)
=============================================
Enterprise-grade read-only data access layer for the Dashboard.
Strictly devoid of business logic, DTO instantiation, and DML operations.
Returns heavily optimized, raw SQLAlchemy Rows.
Integrates with AggregateBuilder and DashboardFilterParams.
"""

import hashlib
from typing import Any, Optional, Sequence

from sqlalchemy import func, desc, and_
from sqlalchemy.engine.row import Row

from app.extensions import db
from app.models import (
    Representative, 
    Target, 
    IMSSummary
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
                    Target.year == IMSSummary.year
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
            filter_callable=lambda q: DashboardFilter.apply(q, filters),
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        return query.all()

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
        default_order = order_by if order_by is not None else [
            desc(IMSSummary.year), 
            desc(IMSSummary.month)
        ]

        select_cols = [
            IMSSummary.year,
            IMSSummary.month,
            func.avg(IMSSummary.market_share).label("avg_share")
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
