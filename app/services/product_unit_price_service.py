"""Period-aware product unit prices.

A price edited during a calendar month becomes effective on the first day of
next month. The price used by an IMS period is therefore immutable for the
whole month and historical calculations never follow the mutable Product.unit_price.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.extensions import db
from app.models import Product


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
            text("SELECT 1 FROM product_unit_price_history WHERE product_id=:product_id LIMIT 1"),
            {"product_id": int(product_id)},
        ).first()
        if exists:
            return
        year, month = cls.START_PERIOD
        db.session.execute(
            text(
                "INSERT INTO product_unit_price_history "
                "(product_id, effective_year, effective_month, unit_price) "
                "VALUES (:product_id, :year, :month, :price)"
            ),
            {"product_id": int(product_id), "year": year, "month": month, "price": float(old_price or 0)},
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
            text(
                "SELECT id FROM product_unit_price_history "
                "WHERE product_id=:product_id AND effective_year=:year AND effective_month=:month"
            ),
            {"product_id": int(product_id), "year": year, "month": month},
        ).first()
        if existing:
            db.session.execute(
                text("UPDATE product_unit_price_history SET unit_price=:price WHERE id=:id"),
                {"price": new_price, "id": int(existing[0])},
            )
        else:
            db.session.execute(
                text(
                    "INSERT INTO product_unit_price_history "
                    "(product_id, effective_year, effective_month, unit_price) "
                    "VALUES (:product_id, :year, :month, :price)"
                ),
                {"product_id": int(product_id), "year": year, "month": month, "price": new_price},
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
        placeholders = ",".join(str(item) for item in ids)
        rows = db.session.execute(
            text(
                "SELECT product_id, effective_year, effective_month, unit_price "
                "FROM product_unit_price_history "
                f"WHERE product_id IN ({placeholders}) "
                "AND (effective_year < :year OR (effective_year = :year AND effective_month <= :month)) "
                "ORDER BY product_id, effective_year DESC, effective_month DESC"
            ),
            {"year": year, "month": month},
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
