"""Executive Türkiye market cockpit assembled from already-built region snapshots.

This service intentionally performs no database queries. It consumes the durable
ACTIVE region snapshot generation plus the existing national MarketAnalysisService
payload and converts those canonical read models into a general-manager view.
No target, production, IMS or competition precedence is recalculated here.
"""
from __future__ import annotations

from collections import defaultdict


class ExecutiveMarketCockpitService:
    PERIODS = (
        ("monthly", "1 Aylık"),
        ("quarterly", "3 Aylık"),
        ("half_year", "6 Aylık"),
        ("yearly", "12 Aylık"),
    )
    PERIOD_LABELS = dict(PERIODS)

    @staticmethod
    def _number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _key(value):
        return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

    @classmethod
    def _product_market_map(cls, market):
        return {
            cls._key(row.get("company_product")): row
            for row in (market or {}).get("groups", [])
            if row.get("company_product")
        }

    @classmethod
    def _regional_ai_insights(cls, period_key, region_cards):
        """Create deterministic region management insights from the same snapshot metrics.

        This is deliberately a read-model interpretation layer: it does not query the
        database, predict missing values, or change target/actual/share calculations.
        """
        period_label = cls.PERIOD_LABELS.get(period_key, period_key)
        insights = []
        for row in region_cards:
            realization = row.get("realization_percent")
            share = cls._number(row.get("share_percent"))
            gap = cls._number(row.get("unit_share_gap_to_national"))
            if realization is None:
                signal = "Veri bekleniyor"
                tone = "neutral"
                action = "Seçili dönem gerçekleşmesi tamamlandığında bölgesel yorum otomatik güncellenecek."
            elif realization >= 100 and gap >= 0:
                signal = "Hedef üstü · pay avantajlı"
                tone = "strong"
                action = "Mevcut üstünlüğü korurken yüksek payın sürdürülebilirliğini rakip baskısıyla birlikte takip et."
            elif realization >= 90 and gap >= 0:
                signal = "Güçlü performans"
                tone = "strong"
                action = "Hedef kapanışını koru; Türkiye ortalamasının üzerindeki kutu payını savun."
            elif realization < 75 and gap < 0:
                signal = "Öncelikli toparlanma"
                tone = "risk"
                action = "Hem realizasyon hem kutu payı zayıf; ürün ve brick detayında kayıp alanları önceliklendir."
            elif realization < 90 and gap >= 0:
                signal = "Pay güçlü · hedef geride"
                tone = "watch"
                action = "Pazar payı avantajını satış gerçekleşmesine çevirecek ürün/brick aksiyonlarına odaklan."
            elif realization >= 90 and gap < 0:
                signal = "Hedef güçlü · pay gelişebilir"
                tone = "watch"
                action = "Realizasyon korunurken Türkiye kutu payına göre geride kalan rekabet alanlarını büyüt."
            else:
                signal = "Dengeli takip"
                tone = "neutral"
                action = "Realizasyon ve rekabet payını birlikte izle; belirgin sapmada ürün/brick detayına in."

            insight_text = (
                f"{period_label} realizasyon %{realization:.1f}; " if realization is not None else f"{period_label} realizasyon —; "
            )
            insight_text += (
                f"güncel IMS rekabet haftasında kutu pazar payı %{share:.1f}; "
                f"Türkiye ağırlıklı kutu payına göre {gap:+.1f} puan."
            )
            insights.append({
                "region_key": row.get("region_key"),
                "region_name": row.get("region_name"),
                "signal": signal,
                "tone": tone,
                "metrics": insight_text,
                "action": action,
            })
        insights.sort(key=lambda item: str(item.get("region_key") or ""))
        return insights

    @classmethod
    def _aggregate_period(cls, period_key, snapshots, market):
        target = 0.0
        actual = 0.0
        complete = True
        product_buckets = defaultdict(lambda: {
            "product_id": None,
            "product_name": "",
            "target_tl": 0.0,
            "actual_tl": 0.0,
            "complete": True,
        })
        region_cards = []

        for region_key, snapshot in snapshots.items():
            report = (snapshot or {}).get("report") or {}
            region_market = (snapshot or {}).get("market_analysis") or {}
            period = (report.get("periods") or {}).get(period_key) or {}
            region_target = cls._number(period.get("target_tl"))
            region_actual_raw = period.get("actual_tl")
            region_complete = bool(period.get("complete")) and region_actual_raw is not None
            region_actual = cls._number(region_actual_raw) if region_complete else 0.0
            target += region_target
            actual += region_actual
            complete = complete and region_complete

            totals = region_market.get("totals") or {}
            region_share = cls._number(
                totals.get("precise_share_percent", totals.get("share_percent"))
            )
            region_cards.append({
                "region_key": str(region_key),
                "region_name": report.get("region_name") or str(region_key),
                "target_tl": round(region_target, 2),
                "actual_tl": round(region_actual, 2) if region_complete else None,
                "realization_percent": cls._number(period.get("realization_percent")) if region_complete else None,
                "market_unit": cls._number(totals.get("market_unit")),
                "competitor_unit": cls._number(totals.get("competitor_unit")),
                "company_unit": cls._number(totals.get("effective_company_unit", totals.get("company_unit"))),
                "share_percent": round(region_share, 1),
            })

            for product in period.get("products") or []:
                pid = product.get("product_id")
                name = product.get("product_name") or f"Ürün {pid}"
                bucket = product_buckets[(pid, name)]
                bucket["product_id"] = pid
                bucket["product_name"] = name
                bucket["target_tl"] += cls._number(product.get("target_tl"))
                if product.get("complete") and product.get("actual_tl") is not None:
                    bucket["actual_tl"] += cls._number(product.get("actual_tl"))
                else:
                    bucket["complete"] = False

        # Region market share is unit-based in RegionMarketService. Compare it
        # only with the weighted national unit share derived from those same
        # regional snapshots; never mix it with the national TL share.
        national_market_unit = sum(row["market_unit"] for row in region_cards)
        national_company_unit = sum(row["company_unit"] for row in region_cards)
        national_unit_share = (
            national_company_unit * 100.0 / national_market_unit
            if national_market_unit else 0.0
        )
        for row in region_cards:
            row["unit_share_gap_to_national"] = round(
                row["share_percent"] - national_unit_share, 1
            )

        market_by_product = cls._product_market_map(market)
        products = []
        for bucket in product_buckets.values():
            target_tl = bucket["target_tl"]
            actual_tl = bucket["actual_tl"] if bucket["complete"] else None
            realization = (actual_tl * 100.0 / target_tl) if actual_tl is not None and target_tl else None
            market_row = market_by_product.get(cls._key(bucket["product_name"])) or {}
            share = market_row.get("company_share_percent")
            share_value = cls._number(share) if share is not None else None
            high_realization = realization is not None and realization >= 90
            high_share = share_value is not None and share_value >= 30
            if high_realization and high_share:
                quadrant, tone = "Güçlü / Büyüyen", "strong"
            elif high_realization:
                quadrant, tone = "Satış güçlü · pay savunulmalı", "defend"
            elif high_share:
                quadrant, tone = "Pazar güçlü · hedef potansiyeli", "potential"
            else:
                quadrant, tone = "Kritik odak", "critical"
            products.append({
                **bucket,
                "target_tl": round(target_tl, 2),
                "actual_tl": round(actual_tl, 2) if actual_tl is not None else None,
                "realization_percent": round(realization, 1) if realization is not None else None,
                "share_percent": round(share_value, 1) if share_value is not None else None,
                "market_tl": cls._number(market_row.get("market_sales_tl")) if market_row else None,
                "quadrant": quadrant,
                "tone": tone,
            })
        products.sort(key=lambda row: (-(row.get("actual_tl") or 0), row["product_name"]))

        region_cards.sort(key=lambda row: (-(row.get("realization_percent") or -1), row["region_key"]))
        realization = actual * 100.0 / target if complete and target else None

        opportunities = sorted(
            [row for row in region_cards if row.get("realization_percent") is not None],
            key=lambda row: (
                -(row.get("realization_percent") or 0),
                -(row.get("share_percent") or 0),
                row["region_key"],
            ),
        )[:5]
        risks = sorted(
            [row for row in region_cards if row.get("realization_percent") is not None],
            key=lambda row: (
                row.get("realization_percent") or 0,
                row.get("share_percent") or 0,
                row["region_key"],
            ),
        )[:5]

        return {
            "key": period_key,
            "target_tl": round(target, 2),
            "actual_tl": round(actual, 2) if complete else None,
            "realization_percent": round(realization, 1) if realization is not None else None,
            "gap_tl": round(target - actual, 2) if complete else None,
            "complete": complete,
            "national_unit_share_percent": round(national_unit_share, 1),
            "regions": region_cards,
            "products": products,
            "opportunities": opportunities,
            "risks": risks,
            "ai_insights": cls._regional_ai_insights(period_key, region_cards),
        }

    @classmethod
    def _rival_pressure(cls, snapshots):
        rivals = defaultdict(lambda: {
            "name": "",
            "product_name": "",
            "unit": 0.0,
            "regions": set(),
            "strongest_region": "",
            "strongest_region_unit": 0.0,
        })
        for region_key, snapshot in snapshots.items():
            report = (snapshot or {}).get("report") or {}
            region_name = report.get("region_name") or str(region_key)
            market = (snapshot or {}).get("market_analysis") or {}
            for row in market.get("rival_rows") or []:
                key = (cls._key(row.get("name")), cls._key(row.get("product_name")))
                bucket = rivals[key]
                unit = cls._number(row.get("unit"))
                bucket["name"] = row.get("name") or "Rakip ürün"
                bucket["product_name"] = row.get("product_name") or "-"
                bucket["unit"] += unit
                bucket["regions"].add(str(region_key))
                if unit > bucket["strongest_region_unit"]:
                    bucket["strongest_region_unit"] = unit
                    bucket["strongest_region"] = f"{region_key} {region_name}"
        result = []
        for bucket in rivals.values():
            result.append({
                **bucket,
                "unit": round(bucket["unit"], 2),
                "region_count": len(bucket["regions"]),
                "regions": None,
                "strongest_region_unit": round(bucket["strongest_region_unit"], 2),
            })
        result.sort(key=lambda row: (-row["unit"], row["name"]))
        return result[:5]

    @classmethod
    def _annual_trend(cls, snapshots):
        months = defaultdict(lambda: {"target_tl": 0.0, "actual_tl": 0.0, "has_data": False})
        labels = {}
        for snapshot in snapshots.values():
            report = (snapshot or {}).get("report") or {}
            for row in report.get("annual_realization") or []:
                month = int(row.get("month") or 0)
                if not month:
                    continue
                labels[month] = row.get("label") or str(month)
                if row.get("has_data"):
                    months[month]["has_data"] = True
                    months[month]["target_tl"] += cls._number(row.get("target_tl"))
                    months[month]["actual_tl"] += cls._number(row.get("actual_tl"))
        trend = []
        for month in range(1, 13):
            item = months[month]
            target = item["target_tl"]
            actual = item["actual_tl"]
            trend.append({
                "month": month,
                "label": labels.get(month, str(month)),
                "has_data": item["has_data"],
                "realization_percent": round(actual * 100.0 / target, 1) if item["has_data"] and target else None,
            })
        return trend

    @classmethod
    def build(cls, market, snapshots, region_rows=None):
        snapshots = snapshots or {}
        periods = {
            key: cls._aggregate_period(key, snapshots, market)
            for key, _ in cls.PERIODS
        }
        monthly = periods.get("monthly") or {}
        groups = (market or {}).get("groups") or []
        highest_share_product = max(
            [row for row in groups if row.get("company_share_percent") is not None],
            key=lambda row: cls._number(row.get("company_share_percent")),
            default=None,
        )
        highest_realization_product = max(
            [row for row in (monthly.get("products") or []) if row.get("realization_percent") is not None],
            key=lambda row: cls._number(row.get("realization_percent")),
            default=None,
        )
        best_region = (monthly.get("regions") or [None])[0]
        rival_pressure = cls._rival_pressure(snapshots)

        summary = []
        if monthly.get("realization_percent") is not None:
            summary.append(f"Türkiye aylık realizasyonu %{monthly['realization_percent']:.1f}.")
        if highest_share_product:
            summary.append(
                f"En yüksek güncel pazar payı {highest_share_product.get('company_product')} ürününde "
                f"%{cls._number(highest_share_product.get('company_share_percent')):.1f}."
            )
        if highest_realization_product:
            summary.append(
                f"En yüksek ürün realizasyonu {highest_realization_product.get('product_name')} ürününde "
                f"%{cls._number(highest_realization_product.get('realization_percent')):.1f}."
            )
        if best_region:
            summary.append(
                f"Aylık realizasyonda öne çıkan bölge {best_region.get('region_key')} {best_region.get('region_name')} "
                f"(%{cls._number(best_region.get('realization_percent')):.1f})."
            )
        if rival_pressure:
            top = rival_pressure[0]
            summary.append(
                f"En yüksek rakip kutu baskısı {top.get('name')} ürününde; Türkiye toplamı "
                f"{top.get('unit'):,.0f} kutu."
            )

        return {
            "ready": bool(snapshots),
            "region_count": len(snapshots),
            "period_options": [{"key": key, "label": label} for key, label in cls.PERIODS],
            "periods": periods,
            "market": market or {},
            "rival_pressure": rival_pressure,
            "annual_trend": cls._annual_trend(snapshots),
            "summary": summary,
            "source_week": (market or {}).get("source_week") or (market or {}).get("latest_week"),
        }
