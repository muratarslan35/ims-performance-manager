"""Read-only, upload-scoped competitor analysis for a complete sales region."""

from collections import defaultdict

from sqlalchemy import desc, func

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product, ProductionRegionProductResult, Target
from app.services.alias_service import AliasService
from app.services.production_result_service import ProductionResultService


class RegionMarketService:
    PRODUCT_ORDER = ("TRAVAZOL", "MONUROL", "ACNEMIX", "MIXOVUL", "STIDERM", "BRIMODER", "FENTIVAG")

    def __init__(self, region_key, representative_ids, year, month):
        self.region_key = str(region_key or "").strip()
        self.representative_ids = tuple(sorted({int(item) for item in representative_ids}))
        self.year = int(year)
        self.month = int(month)

    @staticmethod
    def _key(value):
        return "".join(char for char in AliasService.normalize(value) if char.isalnum())

    def _latest_upload_id(self):
        return db.session.query(IMSUpload.id).filter(
            IMSUpload.year == self.year,
            IMSUpload.month == self.month,
            IMSUpload.status == "COMPLETED",
        ).order_by(
            desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
        ).limit(1).scalar()

    def _products(self):
        products = Product.query.order_by(Product.display_order.asc(), Product.product_name.asc()).all()
        ordered = []
        for expected in self.PRODUCT_ORDER:
            product = next((item for item in products if expected in self._key(item.product_name)), None)
            if product is not None and product not in ordered:
                ordered.append(product)
        return ordered

    def _product_for(self, product_group, product_name, products):
        group_key, product_key = self._key(product_group), self._key(product_name)
        for product in products:
            candidates = {
                self._key(product.product_name), self._key(product.product_code),
                self._key(product.ims_name), self._key(product.competitor_group),
            } - {""}
            if any(key in group_key or key in product_key for key in candidates):
                return product
        return None

    def _is_company(self, product_name, product, stored_company, stored_competitor):
        if stored_competitor:
            return False
        if stored_company:
            return True
        name_key = self._key(product_name)
        own_keys = {
            self._key(product.product_name), self._key(product.product_code), self._key(product.ims_name)
        } - {""}
        return any(key in name_key or name_key in key for key in own_keys)

    def _competition_rows(self, upload_id):
        if not upload_id:
            return []
        prefix = f"{self.region_key}%"
        base = db.session.query(
            CompetitionData.product_group,
            CompetitionData.product_name,
            CompetitionData.subterritory,
            CompetitionData.is_company_product,
            CompetitionData.is_competitor,
            func.coalesce(func.sum(CompetitionData.metric_value), 0.0),
        ).filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.territory.like(prefix),
        )
        monthly = base.filter(
            func.upper(CompetitionData.sheet_name).like("%AYLIK%"),
            func.upper(CompetitionData.sheet_name).like("%REKABET%"),
            func.upper(CompetitionData.sheet_name).like("%KUTU%"),
        ).group_by(
            CompetitionData.product_group, CompetitionData.product_name,
            CompetitionData.subterritory, CompetitionData.is_company_product,
            CompetitionData.is_competitor,
        ).all()
        if monthly:
            return monthly
        return base.group_by(
            CompetitionData.product_group, CompetitionData.product_name,
            CompetitionData.subterritory, CompetitionData.is_company_product,
            CompetitionData.is_competitor,
        ).all()

    def _target_units(self):
        if not self.representative_ids:
            return {}
        return {
            product_id: float(value or 0)
            for product_id, value in db.session.query(
                Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
            ).filter(
                Target.year == self.year, Target.month == self.month,
                Target.representative_id.in_(self.representative_ids),
            ).group_by(Target.product_id).all()
        }

    def _official_products(self, production_upload_id):
        if not production_upload_id:
            return {}
        return {
            row.product_id: row
            for row in ProductionRegionProductResult.query.filter_by(
                upload_id=production_upload_id, region_code=self.region_key
            ).all()
        }

    def _build(self, upload_id, production_upload_id):
        products = self._products()
        targets = self._target_units()
        official = self._official_products(production_upload_id)
        product_buckets = defaultdict(lambda: {"company": 0.0, "competitor": 0.0, "rivals": defaultdict(float)})
        brick_buckets = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})

        for group, name, brick, stored_company, stored_competitor, value in self._competition_rows(upload_id):
            product = self._product_for(group, name, products)
            if product is None:
                continue
            amount = float(value or 0)
            is_company = self._is_company(name, product, stored_company, stored_competitor)
            side = "company" if is_company else "competitor"
            product_buckets[product.id][side] += amount
            brick_buckets[str(brick or "Brick bilgisi yok").strip()][side] += amount
            if not is_company:
                product_buckets[product.id]["rivals"][str(name or "Rakip ürün").strip()] += amount

        rows = []
        for product in products:
            bucket = product_buckets[product.id]
            official_row = official.get(product.id)
            company = float(official_row.actual_unit) if official_row else bucket["company"]
            target = float(official_row.target_unit) if official_row else float(targets.get(product.id, 0))
            competitor = bucket["competitor"]
            market = company + competitor
            share = company * 100.0 / market if market else 0.0
            realization = company * 100.0 / target if target else 0.0
            rivals = [
                {"name": name, "unit": round(unit, 2), "market_share_percent": round(unit * 100.0 / market, 1) if market else 0.0}
                for name, unit in sorted(bucket["rivals"].items(), key=lambda item: (-item[1], item[0]))
            ]
            rows.append({
                "product_id": product.id, "product_name": product.product_name,
                "target_unit": round(target, 2), "company_unit": round(company, 2),
                "competitor_unit": round(competitor, 2), "market_unit": round(market, 2),
                "share_percent": round(share, 1), "realization_percent": round(realization, 1),
                "attention": "strong" if share >= 50 else "warning" if share >= 30 else "critical",
                "rivals": rivals,
            })

        bricks = []
        for brick, bucket in brick_buckets.items():
            market = bucket["company"] + bucket["competitor"]
            bricks.append({
                "brick": brick, "company_unit": round(bucket["company"], 2),
                "competitor_unit": round(bucket["competitor"], 2), "market_unit": round(market, 2),
                "share_percent": round(bucket["company"] * 100.0 / market, 1) if market else 0.0,
            })
        bricks.sort(key=lambda item: (-item["competitor_unit"], item["brick"]))
        total_company = sum(item["company_unit"] for item in rows)
        total_competitor = sum(item["competitor_unit"] for item in rows)
        total_market = total_company + total_competitor
        return {
            "rows": rows, "top_bricks": bricks[:10], "upload_id": upload_id,
            "source": "PRODUCTION_AND_IMS_COMPETITION" if official else "IMS_COMPETITION",
            "has_data": any(item["market_unit"] > 0 for item in rows),
            "totals": {
                "company_unit": round(total_company, 2), "competitor_unit": round(total_competitor, 2),
                "market_unit": round(total_market, 2),
                "share_percent": round(total_company * 100.0 / total_market, 1) if total_market else 0.0,
            },
        }

    def build(self):
        upload_id = self._latest_upload_id()
        production_upload = ProductionResultService.final_upload(self.year, self.month)
        production_upload_id = production_upload.id if production_upload else None
        key = f"region-market:{self.region_key}:{self.year}:{self.month}:{upload_id or 0}:{production_upload_id or 0}"
        return RepresentativeAnalysisCache.get_or_compute(
            key, lambda: self._build(upload_id, production_upload_id), ttl_seconds=60
        )
