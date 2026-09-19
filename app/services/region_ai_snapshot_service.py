"""Snapshot-only management intelligence for region AI panels.

This module never reads IMS, production, target or competition source tables.
It only compares already-published dashboard/region/representative snapshots so
region pages stay responsive and do not fan out into per-representative queries.
"""
from __future__ import annotations


class RegionAISnapshotService:
    @staticmethod
    def previous_period(year, month):
        year, month = int(year), int(month)
        return (year, month - 1) if month > 1 else (year - 1, 12)

    @staticmethod
    def _key(value):
        return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())

    @staticmethod
    def _number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _national_underperformance(cls, report, dashboard_payload):
        national = (dashboard_payload or {}).get("executive_metrics") or {}
        national_products = {}
        for item in national.get("products") or []:
            key = cls._key(item.get("product_name"))
            if key:
                national_products[key] = item

        monthly = (((report or {}).get("periods") or {}).get("monthly") or {})
        result = []
        for region_item in monthly.get("products") or []:
            key = cls._key(region_item.get("product_name"))
            national_item = national_products.get(key)
            if not national_item:
                continue
            national_percent = national_item.get("realization_percent")
            region_percent = region_item.get("realization_percent")
            if national_percent is None or region_percent is None:
                continue
            national_percent = cls._number(national_percent)
            region_percent = cls._number(region_percent)
            if region_percent >= national_percent:
                continue
            result.append({
                "product_name": region_item.get("product_name") or national_item.get("product_name") or "Ürün",
                "national_percent": national_percent,
                "region_percent": region_percent,
                "gap_points": round(national_percent - region_percent, 1),
            })
        result.sort(key=lambda item: (-item["gap_points"], item["region_percent"], item["product_name"]))
        return result

    @classmethod
    def _monthly_markets(cls, workspaces):
        result = []
        for workspace in (workspaces or {}).values():
            monthly = ((workspace or {}).get("snapshots") or {}).get("monthly") or {}
            market = monthly.get("market_analysis") or {}
            if market:
                result.append(market)
        return result

    @classmethod
    def _zero_exit_bricks(cls, workspaces):
        rows = {}
        for market in cls._monthly_markets(workspaces):
            for item in market.get("brick_product_rows") or []:
                target = cls._number(item.get("target_unit"))
                company = cls._number(item.get("company_unit"))
                if target <= 0 or company > 0:
                    continue
                brick = str(item.get("brick") or "").strip()
                product = str(item.get("product_name") or "").strip()
                if not brick or not product:
                    continue
                key = (cls._key(brick), cls._key(product))
                bucket = rows.setdefault(key, {
                    "brick": brick,
                    "product_name": product,
                    "target_unit": 0.0,
                    "company_unit": 0.0,
                    "competitor_unit": 0.0,
                })
                # Shared bricks may appear in more than one representative
                # snapshot. Use the source row once instead of summing it.
                bucket["target_unit"] = max(bucket["target_unit"], target)
                bucket["company_unit"] = max(bucket["company_unit"], company)
                bucket["competitor_unit"] = max(
                    bucket["competitor_unit"], cls._number(item.get("competitor_unit"))
                )
        result = list(rows.values())
        result.sort(
            key=lambda item: (-item["competitor_unit"], -item["target_unit"], item["brick"], item["product_name"])
        )
        return result

    @classmethod
    def _brick_totals(cls, workspaces):
        rows = {}
        for market in cls._monthly_markets(workspaces):
            for item in market.get("brick_rows") or []:
                brick = str(item.get("brick") or "").strip()
                if not brick:
                    continue
                key = cls._key(brick)
                candidate = {
                    "brick": brick,
                    "company_unit": cls._number(item.get("company_unit")),
                    "competitor_unit": cls._number(item.get("competitor_unit")),
                    "market_unit": cls._number(item.get("market_unit")),
                    "share_percent": cls._number(item.get("share_percent")),
                }
                existing = rows.get(key)
                # Duplicate shared-brick rows are the same published fact. If a
                # compatibility snapshot differs, keep the row with the larger
                # market denominator rather than double counting the brick.
                if existing is None or candidate["market_unit"] > existing["market_unit"]:
                    rows[key] = candidate
        return rows

    @classmethod
    def _city_competitor_totals(cls, market_analysis):
        result = {}
        for rival in (market_analysis or {}).get("rival_rows") or []:
            for city in rival.get("cities") or []:
                name = str(city.get("city") or "").strip()
                if not name:
                    continue
                result[name] = result.get(name, 0.0) + cls._number(city.get("unit"))
        return result

    @classmethod
    def _city_pressure_trend(cls, current_market, previous_market):
        current = cls._city_competitor_totals(current_market)
        previous = cls._city_competitor_totals(previous_market)
        rows = []
        for city, current_unit in current.items():
            if current_unit <= 0:
                continue
            previous_unit = previous.get(city, 0.0)
            delta = current_unit - previous_unit
            if delta < 0:
                continue
            if previous_unit > 0:
                change_percent = round(delta * 100.0 / previous_unit, 1)
                signal = "Koruyor" if abs(delta) < 0.5 else "Artıyor"
            else:
                change_percent = None
                signal = "Yeni yoğunluk"
            rows.append({
                "city": city,
                "previous_unit": round(previous_unit, 2),
                "current_unit": round(current_unit, 2),
                "delta_unit": round(delta, 2),
                "change_percent": change_percent,
                "signal": signal,
            })
        rows.sort(key=lambda item: (-item["delta_unit"], -item["current_unit"], item["city"]))
        return rows

    @classmethod
    def _brick_competitor_losses(cls, current_workspaces, previous_workspaces):
        current = cls._brick_totals(current_workspaces)
        previous = cls._brick_totals(previous_workspaces)
        rows = []
        for key, previous_item in previous.items():
            previous_unit = previous_item["competitor_unit"]
            current_item = current.get(key)
            if current_item is None or previous_unit <= 0:
                continue
            current_unit = current_item["competitor_unit"]
            loss = previous_unit - current_unit
            if loss <= 0:
                continue
            rows.append({
                "brick": current_item["brick"],
                "previous_unit": round(previous_unit, 2),
                "current_unit": round(current_unit, 2),
                "loss_unit": round(loss, 2),
                "change_percent": round(loss * 100.0 / previous_unit, 1),
                "company_unit": round(current_item["company_unit"], 2),
                "share_percent": round(current_item["share_percent"], 1),
            })
        rows.sort(key=lambda item: (-item["loss_unit"], -item["change_percent"], item["brick"]))
        return rows

    @classmethod
    def build(
        cls,
        *,
        report,
        market_analysis,
        dashboard_payload,
        previous_market_analysis,
        current_workspaces,
        previous_workspaces,
        year,
        month,
    ):
        previous_year, previous_month = cls.previous_period(year, month)
        return {
            "national_underperformance": cls._national_underperformance(report, dashboard_payload),
            "zero_exit_bricks": cls._zero_exit_bricks(current_workspaces),
            "city_pressure": cls._city_pressure_trend(market_analysis, previous_market_analysis),
            "brick_losses": cls._brick_competitor_losses(current_workspaces, previous_workspaces),
            "previous_period": {
                "year": previous_year,
                "month": previous_month,
                "label": f"{previous_month:02d}/{previous_year}",
            },
            "current_period": {
                "year": int(year),
                "month": int(month),
                "label": f"{int(month):02d}/{int(year)}",
            },
            "source": "PUBLISHED_SNAPSHOTS_ONLY",
        }
