"""V3 Architecture: Query Filters Layer
====================================
Unified, type-safe filtering mechanism for all OLAP queries.
Uses dataclasses for strict typing and IDE autocomplete.
Applies EXISTS (.has()) for related model filtering to avoid JOIN cardinality pollution.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Query

from app.models import IMSSummary, Representative, Product


@dataclass
class DashboardFilterParams:
    """Type-safe structure for Dashboard OLAP query filters."""
    year: Optional[int] = None
    month: Optional[int] = None
    quarter: Optional[int] = None
    week_number: Optional[int] = None
    representative_id: Optional[int] = None
    product_id: Optional[int] = None
    manager: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    territory: Optional[str] = None
    is_prime_product: Optional[bool] = None


class TimeFilter:
    """Applies time-based filters to the query."""
    
    @staticmethod
    def apply(query: Query, params: DashboardFilterParams) -> Query:
        if params.year is not None:
            query = query.filter(IMSSummary.year == params.year)
        if params.month is not None:
            query = query.filter(IMSSummary.month == params.month)
        if params.quarter is not None:
            query = query.filter(IMSSummary.quarter == params.quarter)
        if params.week_number is not None and hasattr(IMSSummary, "week_number"):
            query = query.filter(IMSSummary.week_number == params.week_number)
        return query


class RepresentativeFilter:
    """Applies representative and organizational hierarchical filters to the query."""
    
    @staticmethod
    def apply(query: Query, params: DashboardFilterParams) -> Query:
        if params.representative_id is not None:
            query = query.filter(IMSSummary.representative_id == params.representative_id)

        rep_conditions = []
        if params.manager is not None:
            rep_conditions.append(Representative.manager == params.manager)
        if params.region is not None:
            rep_conditions.append(Representative.region == params.region)
        if params.city is not None:
            rep_conditions.append(Representative.city == params.city)
        if params.territory is not None:
            rep_conditions.append(Representative.territory == params.territory)

        if rep_conditions:
            query = query.filter(IMSSummary.representative.has(and_(*rep_conditions)))
            
        return query


class ProductFilter:
    """Applies product specific and contextual filters to the query."""
    
    @staticmethod
    def apply(query: Query, params: DashboardFilterParams) -> Query:
        if params.product_id is not None:
            query = query.filter(IMSSummary.product_id == params.product_id)

        if params.is_prime_product is not None:
            query = query.filter(
                IMSSummary.product.has(Product.is_prime_product == params.is_prime_product)
            )
            
        return query


class DashboardFilter:
    """Unified Orchestrator for all Dashboard OLAP filtering strategies."""
    
    @staticmethod
    def apply(query: Query, params: Optional[DashboardFilterParams]) -> Query:
        if not params:
            return query
        
        query = TimeFilter.apply(query, params)
        query = RepresentativeFilter.apply(query, params)
        query = ProductFilter.apply(query, params)
        return query
