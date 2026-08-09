"""V3 Architecture: Base Query Layer
=================================
Generic Enterprise OLAP Query Builder.
Standardizes SELECT, JOIN, GROUP BY, Pagination, and Eager Loading.
Designed to be reusable across Dashboard, Prime, Quarter, Recovery, and AI engines.
Strictly read-only.
"""

from typing import List, Any, Optional, Tuple, Callable
from sqlalchemy.orm import Query


class AggregateBuilder:
    """
    Generic OLAP Query Builder to strictly prevent DRY violations.
    Standardizes the construction of complex aggregation queries.
    """

    @staticmethod
    def build(
        session: Any,
        select_entities: List[Any],
        group_by_entities: Optional[List[Any]] = None,
        joins: Optional[List[Tuple[Any, Any, bool]]] = None,
        filter_callable: Optional[Callable[[Query], Query]] = None,
        order_by: Optional[Any] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        orm_options: Optional[List[Any]] = None
    ) -> Query:
        """
        Constructs a standardized SQLAlchemy Query for aggregations.
        
        Args:
            session: SQLAlchemy DB session.
            select_entities: Columns and aggregate functions to select.
            group_by_entities: Columns to group by.
            joins: List of tuples (TargetModel, ON Condition, is_outer_join).
            filter_callable: A function/callable that applies filters to the query.
            order_by: SQLAlchemy order_by construct.
            limit: Pagination limit.
            offset: Pagination offset.
            orm_options: Eager loading and defer options.
            
        Returns:
            Configured SQLAlchemy Query object.
        """
        query = session.query(*select_entities)

        if joins:
            for target_model, on_clause, is_outer in joins:
                if is_outer:
                    query = query.outerjoin(target_model, on_clause)
                else:
                    query = query.join(target_model, on_clause)

        if filter_callable:
            query = filter_callable(query)

        if group_by_entities:
            query = query.group_by(*group_by_entities)

        if order_by is not None:
            if isinstance(order_by, (list, tuple)):
                query = query.order_by(*order_by)
            else:
                query = query.order_by(order_by)

        if limit is not None:
            query = query.limit(limit)

        if offset is not None:
            query = query.offset(offset)

        if orm_options:
            query = query.options(*orm_options)

        return query
