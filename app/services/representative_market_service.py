"""Representative-scoped company and competitor market analysis."""

from collections import defaultdict

from sqlalchemy import func

from app.extensions import db
from app.models import CompetitionData, IMSSummary, Product, RepresentativeBrickAssignment, Target
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

    def _competition_rows(self, brick_keys, fallback_keys, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = db.session.query(func.max(CompetitionData.upload_id)).filter(
            CompetitionData.year == year,
            CompetitionData.month == month,
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
        return self._is_company_product_name(row.product_name, product)

    def _is_company_product_name(self, product_name, product):
        product_key = self._key(product_name)
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
        previous_year = self.year if self.month > 1 else self.year - 1
        previous_month = self.month - 1 if self.month > 1 else 12
        previous_upload_id, previous_competition_rows = self._competition_rows(
            brick_keys, fallback_keys, previous_year, previous_month
        )
        summaries = {
            item.product_id: item
            for item in IMSSummary.query.filter_by(
                representative_id=self.representative.id,
                year=self.year,
                month=self.month,
            ).all()
        }
        previous_summaries = {
            item.product_id: item
            for item in IMSSummary.query.filter_by(
                representative_id=self.representative.id,
                year=previous_year,
                month=previous_month,
            ).all()
        }
        targets = {
            item.product_id: item
            for item in Target.query.filter_by(
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
                "products": defaultdict(
                    lambda: {
                        "company_unit": 0.0,
                        "market_unit": 0.0,
                        "market_products": defaultdict(float),
                    }
                ),
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
            product_bucket["market_products"][str(row.product_name or "Ürün adı yok").strip()] += value
            if is_company:
                brick_bucket["company_unit"] += value
                product_bucket["company_unit"] += value

        previous_grouped = defaultdict(float)
        for row in previous_competition_rows:
            if row.metric_type != "UNIT":
                continue
            product = self._product_for_row(row, products)
            if product is not None:
                previous_grouped[product.id] += float(row.metric_value or 0.0)

        rows = []
        for product in products:
            summary = summaries.get(product.id)
            actual_unit = float(summary.unit if summary else 0.0)
            market = grouped[product.id]
            market_unit = float(market["unit"])
            competitor_unit = max(market_unit - actual_unit, 0.0)
            previous_summary = previous_summaries.get(product.id)
            previous_actual_unit = float(previous_summary.unit or 0.0) if previous_summary else 0.0
            previous_market_unit = float(previous_grouped[product.id])
            previous_competitor_unit = max(previous_market_unit - previous_actual_unit, 0.0)
            has_previous = previous_summary is not None or previous_market_unit > 0
            actual_change_unit = actual_unit - previous_actual_unit
            competitor_change_unit = competitor_unit - previous_competitor_unit
            actual_change_percent = actual_change_unit * 100.0 / previous_actual_unit if previous_actual_unit else None
            target_unit = float(targets.get(product.id).unit_target or 0.0) if targets.get(product.id) else 0.0
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
                    "has_previous": has_previous,
                    "previous_actual_unit": round(previous_actual_unit, 2),
                    "actual_change_unit": round(actual_change_unit, 2),
                    "actual_change_percent": round(actual_change_percent, 1) if actual_change_percent is not None else None,
                    "previous_competitor_unit": round(previous_competitor_unit, 2),
                    "competitor_change_unit": round(competitor_change_unit, 2),
                    "target_unit": round(target_unit, 2),
                    "realization_percent": round(actual_unit * 100.0 / target_unit, 1) if target_unit else 0.0,
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
        products_by_name = {product.product_name: product for product in products}
        brick_product_rows = []
        for brick, brick_data in brick_groups.items():
            for product_name, product_data in brick_data["products"].items():
                product = products_by_name.get(product_name)
                target = targets.get(product.id) if product else None
                target_unit = float(target.unit_target or 0.0) if target else 0.0
                company_unit = float(product_data["company_unit"])
                market_unit = float(product_data["market_unit"])
                competitor_unit = max(market_unit - company_unit, 0.0)
                market_products = []
                for market_product_name, market_product_unit in product_data["market_products"].items():
                    is_company = self._is_company_product_name(market_product_name, product) if product else False
                    market_products.append({
                        "name": market_product_name,
                        "unit": round(float(market_product_unit), 2),
                        "is_company": is_company,
                        "share_percent": round(float(market_product_unit) * 100.0 / market_unit, 1) if market_unit else 0.0,
                        "realization_percent": round(float(market_product_unit) * 100.0 / target_unit, 1) if is_company and target_unit else None,
                    })
                market_products.sort(key=lambda item: (not item["is_company"], -item["unit"], item["name"]))
                brick_product_rows.append({
                    "brick": brick,
                    "product_name": product_name,
                    "company_unit": round(company_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "target_unit": round(target_unit, 2),
                    "realization_percent": round(company_unit * 100.0 / target_unit, 1) if target_unit else 0.0,
                    "share_percent": round(company_unit * 100.0 / market_unit, 1) if market_unit else 0.0,
                    "market_products": market_products,
                })
        brick_product_rows.sort(key=lambda item: (item["brick"], item["product_name"]))
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
            "brick_product_rows": brick_product_rows,
            "upload_id": upload_id,
            "previous_upload_id": previous_upload_id,
            "previous_period": {"year": previous_year, "month": previous_month},
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
