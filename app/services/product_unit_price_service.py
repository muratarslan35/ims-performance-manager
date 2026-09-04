"""Period-aware product unit prices.

A price edited during a calendar month becomes effective on the first day of
next month. The price used by an IMS period is immutable for the whole month,
and historical calculations never follow the mutable Product.unit_price.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

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
    TZ = ZoneInfo("Europe/Istanbul")

    @staticmethod
    def _next_period(year, month):
        year, month = int(year), int(month)
        return (year + 1, 1) if month == 12 else (year, month + 1)

    @classmethod
    def current_period(cls):
        now = datetime.now(cls.TZ)
        return now.year, now.month

    @classmethod
    def next_effective_period(cls):
        return cls._next_period(*cls.current_period())

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
        """Record a master price edit for next month without touching this month."""
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
        """Return the last price effective on or before the requested IMS month."""
        ids = sorted({int(item) for item in product_ids if item is not None})
        if not ids:
            return {}
        year, month = int(year), int(month)
        fallback = {
            int(product_id): float(unit_price or 0)
            for product_id, unit_price in db.session.query(Product.id, Product.unit_price).filter(Product.id.in_(ids)).all()
        }
        rows = db.session.execute(
            select(
                product_unit_price_history.c.product_id,
                product_unit_price_history.c.effective_year,
                product_unit_price_history.c.effective_month,
                product_unit_price_history.c.unit_price,
            )
            .where(
                product_unit_price_history.c.product_id.in_(ids),
                or_(
                    product_unit_price_history.c.effective_year < year,
                    and_(
                        product_unit_price_history.c.effective_year == year,
                        product_unit_price_history.c.effective_month <= month,
                    ),
                ),
            )
            .order_by(
                product_unit_price_history.c.product_id,
                product_unit_price_history.c.effective_year.desc(),
                product_unit_price_history.c.effective_month.desc(),
            )
        ).all()
        seen = set()
        for product_id, _effective_year, _effective_month, unit_price in rows:
            product_id = int(product_id)
            if product_id in seen:
                continue
            fallback[product_id] = float(unit_price or 0)
            seen.add(product_id)
        return fallback

    @classmethod
    def price_for_period(cls, product_id, year, month):
        return cls.price_map([product_id], year, month).get(int(product_id), 0.0)
