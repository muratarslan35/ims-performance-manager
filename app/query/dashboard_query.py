"""V3 Architecture: Dashboard Query Layer (OLAP)
=============================================
Enterprise-grade read-only data access layer for the Dashboard.
Strictly devoid of business logic, DTO instantiation, and DML operations.
Returns heavily optimized, raw SQLAlchemy Rows.
Integrates with AggregateBuilder and DashboardFilterParams.
"""

import hashlib
from typing import Any, Optional, Sequence
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, desc, and_, case
from sqlalchemy.engine.row import Row

from app.extensions import db
from app.models import (
    CompetitionData,
    IMSUpload,
    Product,
    Representative, 
    Target, 
    IMSSummary, ProductionNationalProductResult, ProductionNationalTotal
    , IMSRawData
)
from app.query.base_query import AggregateBuilder
from app.query.filters import DashboardFilterParams, DashboardFilter
from app.services.production_result_service import ProductionResultService
from app.services.official_aggregate_service import OfficialAggregateService, TARGET_TYPE, ACTUAL_TYPE


class DashboardQuery:
    """
    Strict Read-Only Data Access Layer for Dashboard Service.
    Executes heavily optimized group-by queries via AggregateBuilder.
    Returns raw SQLAlchemy Rows to be mapped by the Mapper/Service layer.
    """

    def __init__(self, session=None):
        self.session = session or db.session

    def _latest_competition_upload_id(self, filters: Optional[DashboardFilterParams]) -> Optional[int]:
        """Select the newest completed upload that contains real competition TL data.

        Legacy uploads created before the competition pipeline was hardened may
        be completed while carrying no usable competition rows.  Dashboard
        competition panels must not bind to those empty upload ids when the
        same period already has a verified Excel competition import.
        """
        if not filters or filters.year is None or filters.month is None:
            return None
        return (
            self.session.query(IMSUpload.id)
            .join(CompetitionData, CompetitionData.upload_id == IMSUpload.id)
            .filter(
                IMSUpload.year == filters.year,
                IMSUpload.month == filters.month,
                IMSUpload.status == "COMPLETED",
                CompetitionData.metric_type == "TL",
                CompetitionData.metric_value != 0,
            )
            .group_by(IMSUpload.id, IMSUpload.week_number, IMSUpload.completed_at)
            .order_by(desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id))
            .limit(1)
            .scalar()
        )

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
            filter_callable=lambda q: DashboardFilter.apply(q, filters),
            order_by=default_order,
            limit=limit,
            offset=offset
        )

        return query.all()

    def load_period_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return SimpleNamespace(realization_tl=Decimal("0"), target_tl=Decimal("0"))
        targets = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)
        if filters.representative_id is not None:
            targets = targets.filter(Target.representative_id == filters.representative_id)
        total_target = Decimal("0")
        total_actual = Decimal("0")
        for target in targets.all():
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            total_target += Decimal(str(target.tl_target or 0))
            total_actual += Decimal(str(effective.get("actual_tl") or 0))
        return SimpleNamespace(realization_tl=total_actual, target_tl=total_target)

    def load_national_dashboard_metrics(self, filters: Optional[DashboardFilterParams] = None) -> dict:
        """Use exact official aggregates when present and preserve legacy periods otherwise."""
        if not filters or filters.year is None or filters.month is None:
            return {}
        official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
        actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
        if official and actual_rows:
            production_upload = ProductionResultService.final_upload(filters.year, filters.month)
            production = {}
            if production_upload:
                production = {
                    row.product_id: [Decimal(str(row.actual_tl)), Decimal(str(row.actual_unit))]
                    for row in self.session.query(ProductionNationalProductResult).filter_by(upload_id=production_upload.id).all()
                }
            if production_upload and len(production) != len(official):
                production = {}
                for item in official:
                    values = production.get(item["product_id"], [Decimal(str(item["actual_tl"] or 0)), Decimal(str(item["actual_unit"] or 0))])
                    item["actual_tl"] = float(values[0]); item["actual_unit"] = float(values[1])
            products = []
            for item in official:
                row = {
                    "product_id": item["product_id"], "product_name": item["product_name"],
                    "target_tl": round(float(item["target_tl"] or 0), 2),
                    "actual_tl": round(float(item["actual_tl"] or 0), 2),
                    "unit_target": round(float(item["target_unit"] or 0), 2),
                    "unit_actual": round(float(item["actual_unit"] or 0), 2),
                }
                row["realization_percent"] = round(row["actual_tl"] * 100 / row["target_tl"], 1) if row["target_tl"] else 0.0
                row["unit_realization_percent"] = round(row["unit_actual"] * 100 / row["unit_target"], 1) if row["unit_target"] else 0.0
                products.append(row)
            target = sum(item["target_tl"] for item in products); actual = sum(item["actual_tl"] for item in products)
            unit_target = sum(item["unit_target"] for item in products); unit_actual = sum(item["unit_actual"] for item in products)
            return {
                "source": "Resmi NATIONAL hedef / kabul edilen gerçekleşme kaynağı",
                "target_tl": round(target, 2), "actual_tl": round(actual, 2),
                "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
                "unit_target": round(unit_target, 2), "unit_actual": round(unit_actual, 2),
                "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
                "products": products,
            }

        upload_id = self.session.query(IMSUpload.id).filter(
            IMSUpload.year == filters.year, IMSUpload.month == filters.month,
            IMSUpload.status == "COMPLETED"
        ).order_by(desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id:
            return {}
        balance_rows = self.session.query(Product.id, Product.product_name, IMSRawData.unit, IMSRawData.tl).join(
            Product, Product.id == IMSRawData.product_id
        ).filter(IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_balance_national").all()
        if not balance_rows:
            return {}
        weekly_by_product = {
            row[0]: (float(row[1] or 0), float(row[2] or 0))
            for row in self.session.query(IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl).filter(
                IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_weekly_units"
            ).all()
        }
        target_unit_by_product = dict(self.session.query(
            Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
        ).filter(Target.year == filters.year, Target.month == filters.month).group_by(Target.product_id).all())
        products = []
        for row in balance_rows:
            weekly_unit, weekly_tl = weekly_by_product.get(row[0], (0.0, float(row[3] or 0)))
            products.append({
                "product_id": row[0], "product_name": row[1],
                "target_tl": round(float(row[2] or 0), 2), "actual_tl": round(float(weekly_tl or 0), 2),
                "unit_target": round(float(target_unit_by_product.get(row[0], 0) or 0), 2), "unit_actual": round(float(weekly_unit or 0), 2),
            })
        target = sum(item["target_tl"] for item in products); actual = sum(item["actual_tl"] for item in products)
        for item in products:
            item["realization_percent"] = round(item["actual_tl"] * 100 / item["target_tl"], 1) if item["target_tl"] else 0.0
            item["unit_realization_percent"] = round(item["unit_actual"] * 100 / item["unit_target"], 1) if item["unit_target"] else 0.0
        unit_target = sum(item["unit_target"] for item in products); unit_actual = sum(item["unit_actual"] for item in products)
        return {
            "source": "BAKİYE / TTS HAFTALIK ÇIKIŞLARI · NATIONAL",
            "target_tl": round(target, 2), "actual_tl": round(actual, 2),
            "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
            "unit_target": round(unit_target, 2), "unit_actual": round(unit_actual, 2),
            "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
            "products": products,
        }

    def load_product_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        if filters.representative_id is None:
            official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
            actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
            if official and actual_rows:
                production = None
                production_upload = ProductionResultService.final_upload(filters.year, filters.month)
                if production_upload:
                    rows = self.session.query(ProductionNationalProductResult).filter_by(upload_id=production_upload.id).all()
                    if len(rows) == len(official):
                        production = {row.product_id: Decimal(str(row.actual_tl)) for row in rows}
                rows = []
                for item in official:
                    actual = production.get(item["product_id"], Decimal("0")) if production is not None else Decimal(str(item["actual_tl"] or 0))
                    rows.append(SimpleNamespace(
                        product_id=item["product_id"],
                        product_name=item["product_name"],
                        realization_tl=actual,
                        target_tl=Decimal(str(item["target_tl"] or 0)),
                    ))
                return sorted(rows, key=lambda row: row.realization_tl, reverse=True)
        q = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)
        if filters.representative_id is not None:
            q = q.filter(Target.representative_id == filters.representative_id)
        totals = {}
        products = {p.id: p for p in Product.query.all()}
        for target in q.all():
            bucket = totals.setdefault(target.product_id, [Decimal("0"), Decimal("0")])
            bucket[1] += Decimal(str(target.tl_target or 0))
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(effective.get("actual_tl") or 0))
        rows = [SimpleNamespace(product_id=pid, product_name=products[pid].product_name if pid in products else str(pid), realization_tl=vals[0], target_tl=vals[1]) for pid, vals in totals.items()]
        return sorted(rows, key=lambda row: row.realization_tl, reverse=True)

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

    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        target_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, TARGET_TYPE)
        if target_upload:
            target_rows = self.session.query(IMSRawData).filter(
                IMSRawData.upload_id == target_upload, IMSRawData.sheet_type == TARGET_TYPE, IMSRawData.territory != "NATIONAL"
            ).all()
            if target_rows:
                production_exists = ProductionResultService.final_upload(filters.year, filters.month) is not None
                actual_by_key = {}
                if production_exists:
                    for target in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                        rep = self.session.get(Representative, target.representative_id)
                        if rep is None or not rep.region: continue
                        rk = str(rep.region).strip().split()[0]
                        effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
                        bucket = actual_by_key.setdefault((rk, target.product_id), [Decimal("0"), Decimal("0")])
                        bucket[0] += Decimal(str(effective.get("actual_unit") or 0)); bucket[1] += Decimal(str(effective.get("actual_tl") or 0))
                else:
                    actual_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, ACTUAL_TYPE)
                    if actual_upload:
                        for row in self.session.query(IMSRawData).filter(
                            IMSRawData.upload_id == actual_upload, IMSRawData.sheet_type == ACTUAL_TYPE, IMSRawData.territory != "NATIONAL"
                        ).all():
                            actual_by_key[(str(row.territory), row.product_id)] = [Decimal(str(row.unit or 0)), Decimal(str(row.tl or 0))]
                reps_by_region = {}; city_by_region = {}
                for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                    rk = str(rep.region).strip().split()[0]; reps_by_region.setdefault(rk, set()).add(rep.id)
                    if rep.city and rk not in city_by_region: city_by_region[rk] = rep.city
                buckets = {}
                for target in target_rows:
                    rk = str(target.territory); bucket = buckets.setdefault(rk, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                    au, atl = actual_by_key.get((rk, target.product_id), [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(target.unit or 0)); bucket[1] += au
                    bucket[2] += Decimal(str(target.tl or 0)); bucket[3] += atl
                return [SimpleNamespace(region=rk, city=city_by_region.get(rk), unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(reps_by_region.get(rk, set()))) for rk, v in sorted(buckets.items())]

        if ProductionResultService.final_upload(filters.year, filters.month) is None:
            upload_id = self.session.query(IMSUpload.id).filter(
                IMSUpload.year == filters.year, IMSUpload.month == filters.month, IMSUpload.status == "COMPLETED"
            ).order_by(desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
            if upload_id:
                balance_rows = self.session.query(IMSRawData.territory, Product.id, IMSRawData.unit).join(
                    Product, Product.id == IMSRawData.product_id
                ).filter(IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_balance_region").all()
                if balance_rows:
                    weekly_rows = self.session.query(IMSRawData.territory, IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl).filter(
                        IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_weekly_region"
                    ).all()
                    def region_key(value):
                        value = str(value or "").strip(); first = value.split()[0] if value else ""
                        return first if first.isdigit() else value
                    weekly = {(region_key(r[0]), r[1]): (Decimal(str(r[2] or 0)), Decimal(str(r[3] or 0))) for r in weekly_rows}
                    unit_targets = {(region_key(r[0]), r[1]): Decimal(str(r[2] or 0)) for r in self.session.query(
                        Representative.region, Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
                    ).join(Target, Target.representative_id == Representative.id).filter(
                        Target.year == filters.year, Target.month == filters.month, Representative.region.isnot(None)
                    ).group_by(Representative.region, Target.product_id).all()}
                    representative_ids = {}; city_by_region = {}
                    for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                        rk = region_key(rep.region); representative_ids.setdefault(rk, set()).add(rep.id)
                        if rep.city and rk not in city_by_region: city_by_region[rk] = rep.city
                    buckets = {}
                    for territory, product_id, target_tl in balance_rows:
                        rk = region_key(territory); bucket = buckets.setdefault(rk, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                        au, atl = weekly.get((rk, product_id), (Decimal("0"), Decimal("0")))
                        bucket[0] += unit_targets.get((rk, product_id), Decimal("0")); bucket[1] += au
                        bucket[2] += Decimal(str(target_tl or 0)); bucket[3] += atl
                    return [SimpleNamespace(region=rk, city=city_by_region.get(rk), unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(representative_ids.get(rk, set()))) for rk, v in sorted(buckets.items())]

        targets = self.session.query(Target, Representative).join(Representative, Representative.id == Target.representative_id).filter(
            Target.year == filters.year, Target.month == filters.month, Representative.region.isnot(None)
        ).all()
        buckets = {}
        for target, rep in targets:
            key = (rep.region, rep.city); bucket = buckets.setdefault(key, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), set()])
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(target.unit_target or 0)); bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
            bucket[2] += Decimal(str(target.tl_target or 0)); bucket[3] += Decimal(str(effective.get("actual_tl") or 0)); bucket[4].add(rep.id)
        return [SimpleNamespace(region=k[0], city=k[1], unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(v[4])) for k, v in sorted(buckets.items())]

    def load_competition_overview(self, filters: Optional[DashboardFilterParams] = None) -> Sequence[Row]:
        """Aggregate competition metrics from the latest completed workbook only."""
        latest_upload_id = self._latest_competition_upload_id(filters)
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
        upload_id = self._latest_competition_upload_id(filters)
        if not upload_id: return []
        return self.session.query(CompetitionData.territory,CompetitionData.product_group,CompetitionData.product_name,func.sum(CompetitionData.metric_value).label("sales_tl")).filter(CompetitionData.upload_id==upload_id,CompetitionData.metric_type=="TL",CompetitionData.is_subtotal.is_(False),CompetitionData.is_grand_total.is_(False),~func.upper(CompetitionData.product_name).like("%GRAND%"),~func.upper(CompetitionData.product_name).like("%SUBTOTAL%")).group_by(CompetitionData.territory,CompetitionData.product_group,CompetitionData.product_name).all()

    def load_regional_competition_rows(self, filters: Optional[DashboardFilterParams] = None) -> Sequence[Row]:
        """Return a compact territory/product market dataset for executive analysis."""
        upload_id = self._latest_competition_upload_id(filters)
        if not upload_id:
            return []
        return self.session.query(
            CompetitionData.territory, CompetitionData.product_group,
            CompetitionData.product_name, func.sum(CompetitionData.metric_value).label("sales_tl")
        ).filter(
            CompetitionData.upload_id == upload_id, CompetitionData.metric_type == "TL",
            CompetitionData.is_subtotal.is_(False), CompetitionData.is_grand_total.is_(False),
            CompetitionData.territory.isnot(None), CompetitionData.territory != "NATIONAL",
            ~func.upper(CompetitionData.product_name).like("%GRAND%"),
            ~func.upper(CompetitionData.product_name).like("%SUBTOTAL%")
        ).group_by(
            CompetitionData.territory, CompetitionData.product_group, CompetitionData.product_name
        ).all()

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
