"""
V3 Architecture: Dashboard Query Layer (OLAP)
=============================================
Enterprise-grade read-only data access layer for the Dashboard.
Contains ONLY SQLAlchemy queries. Strictly devoid of business logic,
formatting, dictionary construction, and DML (INSERT/UPDATE/DELETE/COMMIT).
Returns strongly typed Dataclasses and SQLAlchemy Rows.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import decimal

from sqlalchemy import func, desc, asc
from sqlalchemy.orm import Query
from sqlalchemy.sql.elements import BinaryExpression

from app.extensions import db
from app.models import (
    Product, 
    Representative, 
    Target, 
    IMSSummary
)


# =============================================================================
# DATA TRANSFER OBJECTS (DTOs)
# =============================================================================

@dataclass
class TopRepresentativeRow:
    rep_id: int
    rep_name: str
    city: str
    total_tl: float
    bonus: float
    target_tl: float


@dataclass
class CityPerformanceRow:
    city: str
    total_tl: float
    target_tl: float
    rep_count: int


@dataclass
class MarketShareTrendRow:
    year: int
    month: int
    avg_share: float


@dataclass
class HistoryRow:
    year: int
    month: int
    total_tl: float
    bonus: float


# =============================================================================
# QUERY LAYER
# =============================================================================

class DashboardQuery:
    """
    Read-Only Online Analytical Processing (OLAP) Query Layer.
    Executes heavily optimized group-by queries, utilizes outer joins,
    and prevents N+1 using specific column selections and eager loading strategies.
    """

    @staticmethod
    def apply_filters(query: Query, filters: Dict[str, Any]) -> Query:
        """
        Unified filtering mechanism for all Dashboard OLAP queries.
        Safely applies filters only if they are present in the dictionary.
        Uses EXISTS (.has()) for related model filtering to avoid JOIN pollution.
        """
        if not filters:
            return query

        # IMSSummary / Time Filters
        if "year" in filters:
            query = query.filter(IMSSummary.year == filters["year"])
        if "month" in filters:
            query = query.filter(IMSSummary.month == filters["month"])
        if "quarter" in filters:
            query = query.filter(IMSSummary.quarter == filters["quarter"])
        if "week_number" in filters and hasattr(IMSSummary, "week_number"):
            query = query.filter(IMSSummary.week_number == filters["week_number"])

        # Identifiers
        if "representative_id" in filters:
            query = query.filter(IMSSummary.representative_id == filters["representative_id"])
        if "product_id" in filters:
            query = query.filter(IMSSummary.product_id == filters["product_id"])

        # Representative Filters (Requires Representative to be Joined or explicitly filtered via IMSSummary relation)
        if any(k in filters for k in ["region", "manager", "city", "territory"]):
            # If Representative is not in the select entities, we use an EXISTS subquery
            # to filter IMSSummary without breaking GROUP BY cardinality.
            rep_conditions = []
            if "region" in filters:
                rep_conditions.append(Representative.region == filters["region"])
            if "manager" in filters:
                rep_conditions.append(Representative.manager == filters["manager"])
            if "city" in filters:
                rep_conditions.append(Representative.city == filters["city"])
            if "territory" in filters:
                rep_conditions.append(Representative.territory == filters["territory"])
            
            query = query.filter(IMSSummary.representative.has(db.and_(*rep_conditions)))

        # Product Filters
        if "is_prime_product" in filters:
            query = query.filter(
                IMSSummary.product.has(Product.is_prime_product == filters["is_prime_product"])
            )

        return query

    def _build_aggregate_query(
        self,
        select_entities: List[Any],
        group_by_entities: List[Any],
        joins: Optional[List[Tuple[Any, BinaryExpression, bool]]] = None,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[Any] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> Query:
        """
        Common Aggregate Builder to prevent DRY violations across OLAP queries.
        Constructs standardized GROUP BY queries with dynamic joins, filtering, and pagination.
        
        Args:
            select_entities: Columns and aggregate functions to select.
            group_by_entities: Columns to group by.
            joins: List of tuples (TargetModel, ON Condition, is_outer_join).
            filters: Dictionary of filters passed to apply_filters.
            order_by: SQLAlchemy order_by construct.
            limit: Pagination limit.
            offset: Pagination offset.
        """
        query = db.session.query(*select_entities)

        # Dynamic Joins
        if joins:
            for model, condition, is_outer in joins:
                if is_outer:
                    query = query.outerjoin(model, condition)
                else:
                    query = query.join(model, condition)

        # Unified Filters
        if filters:
            query = self.apply_filters(query, filters)

        # Aggregation
        if group_by_entities:
            query = query.group_by(*group_by_entities)

        # Sorting & Pagination
        if order_by is not None:
            if isinstance(order_by, (list, tuple)):
                query = query.order_by(*order_by)
            else:
                query = query.order_by(order_by)

        if limit is not None:
            query = query.limit(limit)

        if offset is not None:
            query = query.offset(offset)

        return query

    def load_top_representatives(
        self, 
        filters: Optional[Dict[str, Any]] = None, 
        limit: Optional[int] = 10, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> List[TopRepresentativeRow]:
        """
        Calculates and retrieves top performing representatives.
        Returns Dataclass array for strict typing.
        """
        default_order = order_by if order_by is not None else desc("total_tl")
        
        joins = [
            (Representative, IMSSummary.representative_id == Representative.id, False),
            (Target, 
                db.and_(
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

        group_cols = [Representative.id, Representative.rep_name, Representative.city]

        query = self._build_aggregate_query(
            select_entities=select_cols,
            group_by_entities=group_cols,
            joins=joins,
            filters=filters,
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        rows = query.all()
        return [
            TopRepresentativeRow(
                rep_id=row[0],
                rep_name=row[1] or "",
                city=row[2] or "",
                total_tl=float(row[3] or 0.0),
                bonus=float(row[4] or 0.0),
                target_tl=float(row[5] or 0.0)
            )
            for row in rows
        ]

    def load_city_performance(
        self, 
        filters: Optional[Dict[str, Any]] = None, 
        limit: Optional[int] = None, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> List[CityPerformanceRow]:
        """
        Calculates territory performance aggregated by Representative City.
        """
        default_order = order_by if order_by is not None else desc("total_tl")

        joins = [
            (Representative, IMSSummary.representative_id == Representative.id, False),
            (Target, 
                db.and_(
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

        # Base query configuration
        query = self._build_aggregate_query(
            select_entities=select_cols,
            group_by_entities=group_cols,
            joins=joins,
            filters=filters,
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        # Extra filter explicitly required for city performance logically
        query = query.filter(Representative.city.isnot(None))

        rows = query.all()
        return [
            CityPerformanceRow(
                city=row[0],
                total_tl=float(row[1] or 0.0),
                target_tl=float(row[2] or 0.0),
                rep_count=int(row[3] or 0)
            )
            for row in rows
        ]

    def load_market_share_trend(
        self, 
        filters: Optional[Dict[str, Any]] = None, 
        limit: Optional[int] = 12, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> List[MarketShareTrendRow]:
        """
        Calculates the chronological progression of average market share.
        """
        default_order = order_by if order_by is not None else [desc(IMSSummary.year), desc(IMSSummary.month)]

        select_cols = [
            IMSSummary.year,
            IMSSummary.month,
            func.avg(IMSSummary.market_share).label("avg_share")
        ]

        group_cols = [IMSSummary.year, IMSSummary.month]

        query = self._build_aggregate_query(
            select_entities=select_cols,
            group_by_entities=group_cols,
            filters=filters,
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        rows = query.all()
        return [
            MarketShareTrendRow(
                year=row[0],
                month=row[1],
                avg_share=float(row[2] or 0.0)
            )
            for row in rows
        ]

    def load_history(
        self, 
        filters: Optional[Dict[str, Any]] = None, 
        limit: Optional[int] = 6, 
        offset: Optional[int] = None, 
        order_by: Optional[Any] = None
    ) -> List[HistoryRow]:
        """
        Calculates the chronological progression of overall totals and bonuses.
        Replaces legacy raw SQL executions with highly optimized ORM constructs.
        """
        default_order = order_by if order_by is not None else [desc(IMSSummary.year), desc(IMSSummary.month)]

        select_cols = [
            IMSSummary.year,
            IMSSummary.month,
            func.sum(IMSSummary.tl).label("total_tl"),
            func.sum(IMSSummary.bonus_amount).label("bonus")
        ]

        group_cols = [IMSSummary.year, IMSSummary.month]

        query = self._build_aggregate_query(
            select_entities=select_cols,
            group_by_entities=group_cols,
            filters=filters,
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        rows = query.all()
        return [
            HistoryRow(
                year=row[0],
                month=row[1],
                total_tl=float(row[2] or 0.0),
                bonus=float(row[3] or 0.0)
            )
            for row in rows
        ]
