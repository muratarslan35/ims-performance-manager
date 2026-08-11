"""Representative-scoped company and competitor market analysis."""

from collections import defaultdict

from sqlalchemy import func

from app.extensions import db
from app.models import CompetitionData, IMSSummary, Product, RepresentativeBrickAssignment
from app.services.alias_service import AliasService


class RepresentativeMarketService:
    """Build a seven-product market view without leaking another rep's bricks."""

    PRODUCT_ORDER = (
        "TRAVAZOL",
        "MONUROL",
        "ACNEMIX",
        "MIXOVUL",
        "STIDERM",
        "BRIMODER",
        "FENTIVAG",
    )

    def __init__(self, representative, year, month):
        self.representative = representative
        self.year = int(year)
        self.month = int(month)

    @staticmethod
    def _key(value):
        return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())

    def _products(self):
        products = Product.query.filter_by(is_active=True).order_by(
            Product.display_order.asc(), Product.product_name.asc()
        ).all()
        by_key = {self._key(product.product_name): product for product in products}
        ordered = []
        for name in self.PRODUCT_ORDER:
            product = next(
                (
                    item
                    for key, item in by_key.items()
                    if name in key or key in name
                ),
                None,
            )
            if product is not None and product not in ordered:
                ordered.append(product)
        for product in products:
            if product not in ordered and len(ordered) < 7:
                ordered.append(product)
        return ordered[:7]

    def _scope(self):
        assignments = RepresentativeBrickAssignment.query.filter_by(
            representative_id=self.representative.id,
            year=self.year,
            month=self.month,
        ).all()
        brick_keys = {self._key(item.brick) for item in assignments if self._key(item.brick)}
        fallback_keys = {
            self._key(value)
            for value in (
                self.representative.territory,
                self.representative.city,
                self.representative.region,
            )
            if self._key(value)
        }
        return assignments, brick_keys, fallback_keys

    def _competition_rows(self, brick_keys, fallback_keys):
        upload_id = db.session.query(func.max(CompetitionData.upload_id)).filter(
            CompetitionData.year == self.year,
            CompetitionData.month == self.month,
        ).scalar()
        if upload_id is None:
            return None, []

        rows = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.metric_type.in_(("TL", "UNIT", "MARKET_SHARE")),
        ).all()
        scope_keys = brick_keys or fallback_keys
        if not scope_keys:
            return upload_id, []
        scoped = [
            row
            for row in rows
            if self._key(row.subterritory) in scope_keys or self._key(row.territory) in scope_keys
        ]
        return upload_id, scoped

    def _product_for_row(self, row, products):
        group_key = self._key(row.product_group)
        product_key = self._key(row.product_name)
        for product in products:
            candidates = {
                self._key(product.product_name),
                self._key(product.product_code),
                self._key(product.ims_name),
                self._key(product.competitor_group),
            } - {""}
            if any(key in group_key or key in product_key for key in candidates):
                return product
        return None

    def _is_company_product(self, row, product):
        product_key = self._key(row.product_name)
        own_keys = {
            self._key(product.product_name),
            self._key(product.product_code),
            self._key(product.ims_name),
        } - {""}
        return any(key in product_key or product_key in key for key in own_keys)

    def build(self):
        products = self._products()
        assignments, brick_keys, fallback_keys = self._scope()
        upload_id, competition_rows = self._competition_rows(brick_keys, fallback_keys)
        summaries = {
            item.product_id: item
            for item in IMSSummary.query.filter_by(
                representative_id=self.representative.id,
                year=self.year,
                month=self.month,
            ).all()
        }

        grouped = defaultdict(lambda: {"unit": 0.0, "rivals": defaultdict(float)})
        brick_groups = defaultdict(
            lambda: {
                "company_unit": 0.0,
                "market_unit": 0.0,
                "products": defaultdict(lambda: {"company_unit": 0.0, "market_unit": 0.0}),
            }
        )
        for row in competition_rows:
            if row.metric_type != "UNIT":
                continue
            product = self._product_for_row(row, products)
            if product is None:
                continue
            bucket = grouped[product.id]
            value = float(row.metric_value or 0.0)
            bucket["unit"] += value
            is_company = self._is_company_product(row, product)
            if not is_company:
                bucket["rivals"][row.product_name] += value

            brick = str(row.subterritory or row.territory or "Brick bilgisi yok").strip()
            brick_bucket = brick_groups[brick]
            brick_bucket["market_unit"] += value
            product_bucket = brick_bucket["products"][product.product_name]
            product_bucket["market_unit"] += value
            if is_company:
                brick_bucket["company_unit"] += value
                product_bucket["company_unit"] += value

        rows = []
        for product in products:
            summary = summaries.get(product.id)
            actual_unit = float(summary.unit if summary else 0.0)
            market = grouped[product.id]
            market_unit = float(market["unit"])
            competitor_unit = max(market_unit - actual_unit, 0.0)
            calculated_share = actual_unit * 100.0 / market_unit if market_unit else 0.0
            rivals = sorted(market["rivals"].items(), key=lambda item: item[1], reverse=True)[:5]
            rows.append(
                {
                    "product": product,
                    "actual_unit": round(actual_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "share_percent": round(calculated_share, 1),
                    "gap_unit": round(competitor_unit - actual_unit, 2),
                    "attention": "critical" if competitor_unit > actual_unit * 1.5 and competitor_unit > 0 else "warning" if competitor_unit > actual_unit else "strong",
                    "rivals": [{"name": name, "unit": round(value, 2)} for name, value in rivals],
                }
            )

        total_actual = sum(item["actual_unit"] for item in rows)
        total_market = sum(item["market_unit"] for item in rows)
        average_competitor = (
            sum(max(item["market_unit"] - item["company_unit"], 0.0) for item in brick_groups.values())
            / len(brick_groups)
            if brick_groups else 0.0
        )
        brick_rows = []
        for brick, item in brick_groups.items():
            company_unit = item["company_unit"]
            market_unit = item["market_unit"]
            competitor_unit = max(market_unit - company_unit, 0.0)
            delta_unit = competitor_unit - company_unit
            if competitor_unit >= average_competitor * 1.5 and competitor_unit > company_unit and competitor_unit > 0:
                attention, label, arrow = "critical", "Öncelikli bölge", "↑"
            elif competitor_unit > average_competitor or competitor_unit > company_unit:
                attention, label, arrow = "warning", "Takip edilmeli", "↗"
            else:
                attention, label, arrow = "strong", "Güçlü / dengeli", "→"
            threats = []
            for product_name, product_data in item["products"].items():
                rival_units = max(product_data["market_unit"] - product_data["company_unit"], 0.0)
                if rival_units > product_data["company_unit"]:
                    threats.append(
                        {
                            "product_name": product_name,
                            "competitor_unit": round(rival_units, 2),
                            "gap_unit": round(rival_units - product_data["company_unit"], 2),
                        }
                    )
            threats.sort(key=lambda threat: threat["gap_unit"], reverse=True)
            brick_rows.append(
                {
                    "brick": brick,
                    "company_unit": round(company_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "share_percent": round(company_unit * 100.0 / market_unit, 1) if market_unit else 0.0,
                    "delta_unit": round(delta_unit, 2),
                    "attention": attention,
                    "attention_label": label,
                    "arrow": arrow,
                    "threats": threats[:3],
                }
            )
        priority = {"critical": 0, "warning": 1, "strong": 2}
        brick_rows.sort(key=lambda item: (priority[item["attention"]], -item["competitor_unit"]))
        return {
            "rows": rows,
            "chart_rows": [
                {
                    "product_name": item["product"].product_name,
                    "actual_unit": item["actual_unit"],
                    "competitor_unit": item["competitor_unit"],
                }
                for item in rows
            ],
            "brick_rows": brick_rows,
            "upload_id": upload_id,
            "scope": "brick" if brick_keys else "geography" if fallback_keys else "none",
            "bricks": [item.brick for item in assignments],
            "has_competition": bool(competition_rows),
            "totals": {
                "actual_unit": round(total_actual, 2),
                "market_unit": round(total_market, 2),
                "competitor_unit": round(max(total_market - total_actual, 0.0), 2),
                "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
            },
        }
