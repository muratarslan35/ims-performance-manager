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

        grouped = defaultdict(lambda: {"tl": 0.0, "unit": 0.0, "shares": [], "rivals": defaultdict(float)})
        for row in competition_rows:
            product = self._product_for_row(row, products)
            if product is None:
                continue
            bucket = grouped[product.id]
            value = float(row.metric_value or 0.0)
            if row.metric_type == "TL":
                bucket["tl"] += value
                if self._key(product.product_name) not in self._key(row.product_name):
                    bucket["rivals"][row.product_name] += value
            elif row.metric_type == "UNIT":
                bucket["unit"] += value
            elif row.metric_type == "MARKET_SHARE":
                bucket["shares"].append(value * 100.0 if 0 <= value <= 1 else value)

        rows = []
        for product in products:
            summary = summaries.get(product.id)
            actual_tl = float(summary.tl if summary else 0.0)
            actual_unit = float(summary.unit if summary else 0.0)
            market = grouped[product.id]
            market_tl = float(market["tl"])
            market_unit = float(market["unit"])
            competitor_tl = max(market_tl - actual_tl, 0.0)
            competitor_unit = max(market_unit - actual_unit, 0.0)
            calculated_share = actual_tl * 100.0 / market_tl if market_tl else 0.0
            reported_share = sum(market["shares"]) / len(market["shares"]) if market["shares"] else 0.0
            rivals = sorted(market["rivals"].items(), key=lambda item: item[1], reverse=True)[:5]
            rows.append(
                {
                    "product": product,
                    "actual_tl": round(actual_tl, 2),
                    "actual_unit": round(actual_unit, 2),
                    "market_tl": round(market_tl, 2),
                    "market_unit": round(market_unit, 2),
                    "competitor_tl": round(competitor_tl, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "share_percent": round(calculated_share, 1),
                    "reported_share_percent": round(reported_share, 1),
                    "rivals": [{"name": name, "tl": round(value, 2)} for name, value in rivals],
                }
            )

        total_actual = sum(item["actual_tl"] for item in rows)
        total_market = sum(item["market_tl"] for item in rows)
        return {
            "rows": rows,
            "chart_rows": [
                {
                    "product_name": item["product"].product_name,
                    "actual_tl": item["actual_tl"],
                    "competitor_tl": item["competitor_tl"],
                }
                for item in rows
            ],
            "upload_id": upload_id,
            "scope": "brick" if brick_keys else "geography" if fallback_keys else "none",
            "bricks": [item.brick for item in assignments],
            "has_competition": bool(competition_rows),
            "totals": {
                "actual_tl": round(total_actual, 2),
                "market_tl": round(total_market, 2),
                "competitor_tl": round(max(total_market - total_actual, 0.0), 2),
                "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
            },
        }
