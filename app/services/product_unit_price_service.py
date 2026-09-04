"""Period-aware product unit prices.

A price edited while an IMS business month is active becomes effective from the
next IMS month. The active month keeps the price it started with even if later
weekly IMS files arrive after a master-price edit. Historical calculations never
follow the mutable ``Product.unit_price``.
"""
from datetime import datetime

from sqlalchemy import and_, func, or_, select

from app.extensions import db
from app.models import Product


product_unit_price_history = db.Table(
    "product_unit_price_history",
    db.Column("id", db.Integer, primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    db.Column("effective_year", db.Integer, nullable=False),
    db.Column("effective_month", db.Integer, nullable=False),
    db.Column("unit_price", db.Float, nullable=False),
    db.Column("created_at", db.DateTime, nullable=False, default=datetime.utcnow),
    db.UniqueConstraint("product_id", "effective_year", "effective_month", name="uq_product_price_period"),
    db.Index("ix_product_price_history_lookup", "product_id", "effective_year", "effective_month"),
    extend_existing=True,
)


class ProductUnitPriceService:
    START_PERIOD = (2026, 4)

    @staticmethod
    def _next_period(year, month):
        year, month = int(year), int(month)
        return (year + 1, 1) if month == 12 else (year, month + 1)

    @classmethod
    def current_period(cls):
        """Use the application's active IMS business period, not wall-clock month."""
        from app.services.period_service import PeriodService

        period = PeriodService.get_active_period()
        return int(period["year"]), int(period["month"])

    @classmethod
    def next_effective_period(cls):
        return cls._next_period(*cls.current_period())

    @classmethod
    def period_price_expression(cls, year, month):
        """SQL expression resolving the latest period price, falling back to master."""
        year, month = int(year), int(month)
        latest = (
            select(product_unit_price_history.c.unit_price)
            .where(
                product_unit_price_history.c.product_id == Product.id,
                or_(
                    product_unit_price_history.c.effective_year < year,
                    and_(
                        product_unit_price_history.c.effective_year == year,
                        product_unit_price_history.c.effective_month <= month,
                    ),
                ),
            )
            .order_by(
                product_unit_price_history.c.effective_year.desc(),
                product_unit_price_history.c.effective_month.desc(),
            )
            .limit(1)
            .correlate(Product)
            .scalar_subquery()
        )
        return func.coalesce(latest, Product.unit_price)

    @classmethod
    def _ensure_baseline(cls, product_id, old_price):
        exists = db.session.execute(
            select(product_unit_price_history.c.id)
            .where(product_unit_price_history.c.product_id == int(product_id))
            .limit(1)
        ).first()
        if exists:
            return
        year, month = cls.START_PERIOD
        db.session.execute(
            product_unit_price_history.insert().values(
                product_id=int(product_id),
                effective_year=year,
                effective_month=month,
                unit_price=float(old_price or 0),
            )
        )

    @classmethod
    def schedule_price_change(cls, product_id, old_price, new_price):
        """Record a master-price edit for the month after the active IMS month."""
        old_price, new_price = float(old_price or 0), float(new_price or 0)
        if old_price == new_price:
            return None
        cls._ensure_baseline(product_id, old_price)
        year, month = cls.next_effective_period()
        existing = db.session.execute(
            select(product_unit_price_history.c.id).where(
                product_unit_price_history.c.product_id == int(product_id),
                product_unit_price_history.c.effective_year == year,
                product_unit_price_history.c.effective_month == month,
            )
        ).first()
        if existing:
            db.session.execute(
                product_unit_price_history.update()
                .where(product_unit_price_history.c.id == int(existing[0]))
                .values(unit_price=new_price)
            )
        else:
            db.session.execute(
                product_unit_price_history.insert().values(
                    product_id=int(product_id),
                    effective_year=year,
                    effective_month=month,
                    unit_price=new_price,
                )
            )
        return year, month

    @classmethod
    def price_map(cls, product_ids, year, month):
        """Return the price effective for the requested IMS month in one query."""
        ids = sorted({int(item) for item in product_ids if item is not None})
        if not ids:
            return {}
        expression = cls.period_price_expression(year, month)
        return {
            int(product_id): float(unit_price or 0)
            for product_id, unit_price in db.session.query(Product.id, expression)
            .filter(Product.id.in_(ids))
            .all()
        }

    @classmethod
    def price_for_period(cls, product_id, year, month):
        return cls.price_map([product_id], year, month).get(int(product_id), 0.0)
