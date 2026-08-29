"""Read-only, upload-scoped competitor analysis for a complete sales region."""

from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR

from sqlalchemy import desc, func

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product, ProductionRegionProductResult, Target
from app.services.alias_service import AliasService
from app.services.production_result_service import ProductionResultService


class RegionMarketService:
    PRODUCT_ORDER = ("TRAVAZOL", "MONUROL", "ACNEMIX", "MIXOVUL", "STIDERM", "BRIMODER", "FENTIVAG")
    PROVINCES = (
        "ADANA", "ADIYAMAN", "AFYONKARAHISAR", "AGRI", "AKSARAY", "AMASYA", "ANKARA", "ANTALYA",
        "ARDAHAN", "ARTVIN", "AYDIN", "BALIKESIR", "BARTIN", "BATMAN", "BAYBURT", "BILECIK",
        "BINGOL", "BITLIS", "BOLU", "BURDUR", "BURSA", "CANAKKALE", "CANKIRI", "CORUM", "DENIZLI",
        "DIYARBAKIR", "DUZCE", "EDIRNE", "ELAZIG", "ERZINCAN", "ERZURUM", "ESKISEHIR", "GAZIANTEP",
        "GIRESUN", "GUMUSHANE", "HAKKARI", "HATAY", "IGDIR", "ISPARTA", "ISTANBUL", "IZMIR",
        "KAHRAMANMARAS", "KARABUK", "KARAMAN", "KARS", "KASTAMONU", "KAYSERI", "KILIS", "KIRIKKALE",
        "KIRKLARELI", "KIRSEHIR", "KOCAELI", "KONYA", "KUTAHYA", "MALATYA", "MANISA", "MARDIN",
        "MERSIN", "MUGLA", "MUS", "NEVSEHIR", "NIGDE", "ORDU", "OSMANIYE", "RIZE", "SAKARYA",
        "SAMSUN", "SANLIURFA", "SIIRT", "SINOP", "SIRNAK", "SIVAS", "TEKIRDAG", "TOKAT", "TRABZON",
        "TUNCELI", "USAK", "VAN", "YALOVA", "YOZGAT", "ZONGULDAK",
    )
    PROVINCE_ALIASES = {"ANK": "ANKARA", "IST": "ISTANBUL", "IZM": "IZMIR", "KADIKOY": "ISTANBUL", "AFYON": "AFYONKARAHISAR"}

    def __init__(self, region_key, representative_ids, year, month):
        self.region_key = str(region_key or "").strip()
        self.representative_ids = tuple(sorted({int(item) for item in representative_ids}))
        self.year = int(year)
        self.month = int(month)

    @staticmethod
    def _key(value):
        return "".join(char for char in AliasService.normalize(value) if char.isalnum())

    @staticmethod
    def _allocate_tenth_shares(components):
        """Return 0.1-point display shares that close to exactly 100.0.

        The precise IMS PP remains in ``precise_*`` fields. This presentation
        allocation only resolves the unavoidable decimal rounding remainder.
        """
        normalized = [(key, max(Decimal(str(value or 0)), Decimal("0"))) for key, value in components]
        total = sum((value for _, value in normalized), Decimal("0"))
        if total <= 0:
            return {key: 0.0 for key, _ in normalized}
        exact_tenths = [(key, value * Decimal("1000") / total) for key, value in normalized]
        allocated = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact_tenths}
        remaining = 1000 - sum(allocated.values())
        ranked = sorted(
            enumerate(exact_tenths),
            key=lambda item: (-(item[1][1] - Decimal(allocated[item[1][0]])), item[0]),
        )
        for _, (key, _) in ranked[:remaining]:
            allocated[key] += 1
        return {key: points / 10.0 for key, points in allocated.items()}

    def _latest_upload_id(self):
        return db.session.query(IMSUpload.id).filter(
            IMSUpload.year == self.year,
            IMSUpload.month == self.month,
            IMSUpload.status == "COMPLETED",
        ).order_by(
            desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
        ).limit(1).scalar()

    def _available_periods(self):
        return [
            {"year": int(year), "month": int(month), "label": f"{int(month):02d}/{int(year)}"}
            for year, month in db.session.query(
                CompetitionData.year, CompetitionData.month
            ).join(IMSUpload, IMSUpload.id == CompetitionData.upload_id).filter(
                IMSUpload.status == "COMPLETED",
                CompetitionData.metric_type == "UNIT",
                CompetitionData.territory.like(f"{self.region_key}%"),
            ).distinct().order_by(CompetitionData.year.desc(), CompetitionData.month.desc()).all()
        ]

    def _province_for_brick(self, brick):
        normalized = AliasService.normalize(brick)
        first = normalized.split()[0] if normalized.split() else ""
        if first in self.PROVINCE_ALIASES:
            return self.PROVINCE_ALIASES[first]
        return next((province for province in self.PROVINCES if normalized.startswith(province)), None)

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
            if any(key in group_key or group_key in key for key in candidates):
                return product
        for product in products:
            candidates = {
                self._key(product.product_name), self._key(product.product_code), self._key(product.ims_name),
            } - {""}
            if any(key in product_key or product_key in key for key in candidates):
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

    @staticmethod
    def _is_total_name(name):
        key = AliasService.normalize(name)
        return "SUBTOTAL" in key or "GRAND TOTAL" in key or key.endswith(" TOTAL")

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

    def _region_market_share_rows(self, upload_id, products):
        """Read workbook-authoritative region PP from TTS REKABET PP.

        Region subtotal rows use ``territory == subterritory`` and are already
        persisted as exact percentage-point values. They are preferable to a
        second dashboard-side percentage calculation.
        """
        if not upload_id:
            return {}
        prefix = f"{self.region_key}%"
        rows = db.session.query(
            CompetitionData.product_group,
            CompetitionData.product_name,
            CompetitionData.is_company_product,
            CompetitionData.is_competitor,
            CompetitionData.metric_value,
        ).filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.metric_type == "MARKET_SHARE",
            CompetitionData.territory.like(prefix),
            CompetitionData.subterritory == CompetitionData.territory,
            func.upper(CompetitionData.sheet_name).like("%REKABET%"),
            func.upper(CompetitionData.sheet_name).like("%PP%"),
        ).all()
        buckets = defaultdict(lambda: {"company": None, "rivals": {}})
        for group, name, stored_company, stored_competitor, value in rows:
            if self._is_total_name(name):
                continue
            product = self._product_for(group, name, products)
            if product is None:
                continue
            percent = float(value or 0)
            if self._is_company(name, product, stored_company, stored_competitor):
                buckets[product.id]["company"] = percent
            else:
                buckets[product.id]["rivals"][self._key(name)] = percent
        return buckets

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
        pp_buckets = self._region_market_share_rows(upload_id, products)
        product_buckets = defaultdict(lambda: {
            "company": 0.0, "company_seen": False,
            "competitor": 0.0, "rivals": defaultdict(float),
        })
        brick_buckets = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        city_group_market = defaultdict(float)
        rival_city = defaultdict(lambda: defaultdict(float))
        rival_product = {}

        for group, name, brick, stored_company, stored_competitor, value in self._competition_rows(upload_id):
            product = self._product_for(group, name, products)
            if product is None or self._is_total_name(name):
                continue
            amount = float(value or 0)
            is_company = self._is_company(name, product, stored_company, stored_competitor)
            side = "company" if is_company else "competitor"
            product_buckets[product.id][side] += amount
            if is_company:
                product_buckets[product.id]["company_seen"] = True
            brick_buckets[str(brick or "Brick bilgisi yok").strip()][side] += amount
            city = self._province_for_brick(brick)
            if city:
                city_group_market[(product.id, city)] += amount
            if not is_company:
                rival_name = str(name or "Rakip ürün").strip()
                product_buckets[product.id]["rivals"][rival_name] += amount
                rival_product[rival_name] = product
                if city:
                    rival_city[rival_name][city] += amount

        rows = []
        display_shares_by_rival = {}
        for product in products:
            bucket = product_buckets[product.id]
            official_row = official.get(product.id)
            company = float(official_row.actual_unit) if official_row else bucket["company"]
            target = float(official_row.target_unit) if official_row else float(targets.get(product.id, 0))
            competitor = bucket["competitor"]

            # Realization keeps P2 > P1 > IMS. Market denominator remains one
            # coherent IMS competition source and never mixes P1/P2 with rivals.
            market_company = bucket["company"] if bucket["company_seen"] else company
            market = market_company + competitor
            derived_company_share = market_company * 100.0 / market if market else 0.0
            realization = company * 100.0 / target if target else 0.0

            pp_bucket = pp_buckets.get(product.id, {})
            precise_company_share = (
                float(pp_bucket.get("company"))
                if pp_bucket.get("company") is not None
                else derived_company_share
            )
            ordered_rivals = sorted(bucket["rivals"].items(), key=lambda item: (-item[1], item[0]))
            precise_rivals = []
            for name, unit in ordered_rivals:
                derived = unit * 100.0 / market if market else 0.0
                source_pp = (pp_bucket.get("rivals") or {}).get(self._key(name))
                precise_rivals.append((name, unit, float(source_pp) if source_pp is not None else derived))

            allocations = self._allocate_tenth_shares(
                [("__company__", precise_company_share)] + [(name, pp) for name, _, pp in precise_rivals]
            )
            rivals = []
            for name, unit, precise_rival_share in precise_rivals:
                display_share = allocations.get(name, round(precise_rival_share, 1))
                display_shares_by_rival[(product.id, name)] = display_share
                rivals.append({
                    "name": name,
                    "unit": round(unit, 2),
                    "market_share_percent": display_share,
                    "precise_market_share_percent": round(precise_rival_share, 6),
                })
            pp_complete = pp_bucket.get("company") is not None and all(
                (pp_bucket.get("rivals") or {}).get(self._key(name)) is not None
                for name, _ in ordered_rivals
            )
            rows.append({
                "product_id": product.id, "product_name": product.product_name,
                "target_unit": round(target, 2), "company_unit": round(company, 2),
                "market_company_unit": round(market_company, 2),
                "competitor_unit": round(competitor, 2), "market_unit": round(market, 2),
                "share_percent": allocations.get("__company__", round(precise_company_share, 1)),
                "precise_share_percent": round(precise_company_share, 6),
                "display_share_total": round(sum(allocations.values()), 1) if market else 0.0,
                "market_share_source": "IMS_TTS_REKABET_PP" if pp_complete else "IMS_COMPETITION_UNITS",
                "realization_percent": round(realization, 1),
                "attention": "strong" if precise_company_share >= 50 else "warning" if precise_company_share >= 30 else "critical",
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

        total_company = sum(item["market_company_unit"] for item in rows)
        total_effective_company = sum(item["company_unit"] for item in rows)
        total_competitor = sum(item["competitor_unit"] for item in rows)
        total_market = total_company + total_competitor
        row_by_product = {item["product_id"]: item for item in rows}
        rival_rows = []
        for rival_name, cities in rival_city.items():
            product = rival_product[rival_name]
            region_market = row_by_product.get(product.id, {}).get("market_unit", 0.0)
            total_unit = sum(cities.values())
            derived_rival_share = total_unit * 100.0 / region_market if region_market else 0.0
            precise_rival_share = next(
                (
                    rival["precise_market_share_percent"]
                    for rival in row_by_product.get(product.id, {}).get("rivals", [])
                    if rival["name"] == rival_name
                ),
                derived_rival_share,
            )
            city_rows = [
                {
                    "city": city, "unit": round(unit, 2),
                    "market_unit": round(city_group_market[(product.id, city)], 2),
                    "share_percent": round(unit * 100.0 / city_group_market[(product.id, city)], 1)
                    if city_group_market[(product.id, city)] else 0.0,
                }
                for city, unit in sorted(cities.items(), key=lambda item: (-item[1], item[0]))
            ]
            rival_rows.append({
                "name": rival_name, "product_id": product.id, "product_name": product.product_name,
                "unit": round(total_unit, 2),
                "share_percent": display_shares_by_rival.get((product.id, rival_name), round(precise_rival_share, 1)),
                "precise_share_percent": round(float(precise_rival_share), 6),
                "cities": city_rows,
            })
        rival_rows.sort(key=lambda item: (-item["unit"], item["name"]))
        rival_groups = []
        rival_sequence = 0
        for product in products:
            group_rivals = [item for item in rival_rows if item["product_id"] == product.id]
            for rival in group_rivals:
                rival["pane_key"] = f"{product.id}-{rival_sequence}"
                rival_sequence += 1
            rival_groups.append({
                "product_id": product.id,
                "product_name": product.product_name,
                "rivals": group_rivals,
                "total_unit": round(sum(item["unit"] for item in group_rivals), 2),
            })
        default_group = next((item for item in rival_groups if item["rivals"]), rival_groups[0] if rival_groups else None)
        default_rival_key = default_group["rivals"][0]["pane_key"] if default_group and default_group["rivals"] else None
        precise_total_share = total_company * 100.0 / total_market if total_market else 0.0
        return {
            "rows": rows, "top_bricks": bricks[:10], "rival_rows": rival_rows,
            "rival_groups": rival_groups,
            "default_rival_group_id": default_group["product_id"] if default_group else None,
            "default_rival_key": default_rival_key,
            "available_periods": self._available_periods(), "upload_id": upload_id,
            "source": "PRODUCTION_AND_IMS_COMPETITION" if official else "IMS_COMPETITION",
            "market_share_source": "IMS_TTS_REKABET_PP_WITH_UNIT_FALLBACK" if pp_buckets else "IMS_COMPETITION_UNITS",
            "has_data": any(item["market_unit"] > 0 for item in rows),
            "totals": {
                "company_unit": round(total_company, 2),
                "effective_company_unit": round(total_effective_company, 2),
                "competitor_unit": round(total_competitor, 2),
                "market_unit": round(total_market, 2),
                "share_percent": round(precise_total_share, 1),
                "precise_share_percent": round(precise_total_share, 6),
            },
        }

    def build(self):
        upload_id = self._latest_upload_id()
        production_upload = ProductionResultService.final_upload(self.year, self.month)
        production_upload_id = production_upload.id if production_upload else None
        key = f"region-market:{self.region_key}:{self.year}:{self.month}:{upload_id or 0}:{production_upload_id or 0}:pp-v1"
        return RepresentativeAnalysisCache.get_or_compute(
            key, lambda: self._build(upload_id, production_upload_id), ttl_seconds=60
        )
