"""Deterministic managerial insights for region and representative scopes."""

from collections import defaultdict
from decimal import Decimal

from app.models import Product, Representative, Target
from app.services.production_result_service import ProductionResultService


class ScopedAIInsightService:
    """Explain verified performance data without changing source calculations."""

    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6))

    @staticmethod
    def _shift_month(year, month, delta):
        ordinal = int(year) * 12 + int(month) - 1 + delta
        return ordinal // 12, ordinal % 12 + 1

    @classmethod
    def _months(cls, year, month, length):
        return [cls._shift_month(year, month, delta) for delta in range(-(length - 1), 1)]

    @staticmethod
    def _percent(actual, target):
        return round(float(actual or 0) * 100 / float(target), 1) if target else 0.0

    @classmethod
    def representative_periods(cls, representative_id, year, month):
        periods = {}
        for key, label, length in cls.PERIODS:
            months = cls._months(year, month, length)
            product_totals = defaultdict(lambda: {"target": Decimal("0"), "actual": Decimal("0"), "complete": True})
            month_totals = defaultdict(lambda: {"target": Decimal("0"), "actual": Decimal("0"), "complete": True})
            targets = Target.query.filter(
                Target.representative_id == representative_id,
                Target.year.in_({item[0] for item in months}),
            ).all()
            allowed = set(months)
            for target in targets:
                period = (target.year, target.month)
                if period not in allowed:
                    continue
                effective = ProductionResultService.effective_product(
                    target.year, target.month, representative_id, target.product_id
                )
                target_tl = Decimal(str(target.tl_target or 0))
                actual_tl = Decimal(str(effective["actual_tl"] or 0))
                complete = bool(effective["complete"] and effective["actual_tl"] is not None)
                for bucket in (product_totals[target.product_id], month_totals[period]):
                    bucket["target"] += target_tl
                    bucket["actual"] += actual_tl
                    bucket["complete"] = bucket["complete"] and complete

            product_ids = list(product_totals)
            products = {p.id: p for p in Product.query.filter(Product.id.in_(product_ids)).all()} if product_ids else {}
            product_rows = []
            for product_id, values in product_totals.items():
                complete = values["complete"]
                product_rows.append({
                    "product_id": product_id,
                    "product_name": products[product_id].product_name if product_id in products else f"Ürün {product_id}",
                    "target_tl": values["target"],
                    "actual_tl": values["actual"] if complete else None,
                    "realization_percent": cls._percent(values["actual"], values["target"]) if complete else None,
                    "gap_tl": max(values["target"] - values["actual"], Decimal("0")) if complete else None,
                    "complete": complete,
                })
            total_target = sum((v["target"] for v in month_totals.values()), Decimal("0"))
            total_actual = sum((v["actual"] for v in month_totals.values()), Decimal("0"))
            complete = bool(month_totals) and all(v["complete"] for v in month_totals.values())
            periods[key] = {
                "key": key, "label": label, "month_count": len(months),
                "target_tl": total_target,
                "actual_tl": total_actual if complete else None,
                "realization_percent": cls._percent(total_actual, total_target) if complete else None,
                "gap_tl": max(total_target - total_actual, Decimal("0")) if complete else None,
                "complete": complete,
                "products": product_rows,
                "representatives": [],
            }
        return periods

    @classmethod
    def build(cls, *, scope_type, scope_name, periods, market_analysis=None):
        result_periods = {}
        for key, label, _length in cls.PERIODS:
            source = periods.get(key, {})
            products = sorted(
                source.get("products", []),
                key=lambda row: (row.get("realization_percent") is None, row.get("realization_percent") or 0, -(float(row.get("gap_tl") or 0))),
            )
            representatives = sorted(
                source.get("representatives", []),
                key=lambda row: (row.get("realization_percent") is None, row.get("realization_percent") or 0),
            )
            critical_products = [row for row in products if row.get("realization_percent") is not None and row["realization_percent"] < 75][:5]
            watch_products = [row for row in products if row.get("realization_percent") is not None and 75 <= row["realization_percent"] < 100][:5]
            critical_reps = [row for row in representatives if row.get("realization_percent") is not None and row["realization_percent"] < 75][:5]
            percent = source.get("realization_percent")
            insights = []
            actions = []
            if not source.get("complete"):
                insights.append("Seçili kapsamın tüm aylarında kesinleşmiş satış verisi bulunmadığı için sonuç tamamlanmayı bekliyor.")
            elif percent is not None:
                insights.append(f"{label} gerçekleşme %{percent:.1f}; hedef açığı {float(source.get('gap_tl') or 0):,.0f} ₺.")
                if percent >= 100:
                    insights.append("Toplam hedef karşılandı; odağı ürün bazında hedef altında kalan kalemlere yöneltin.")
                elif percent >= 75:
                    insights.append("Hedefe yakın seyir var; açık ürünlerde yoğunlaşma dönem sonucunu belirleyecek.")
                else:
                    insights.append("Kritik hedef açığı bulunuyor; ürün ve saha önceliklerinin yeniden planlanması gerekiyor.")
            if critical_products:
                item = critical_products[0]
                actions.append(f"{item['product_name']} %{item['realization_percent']:.1f} ile ilk ürün önceliği; {float(item.get('gap_tl') or 0):,.0f} ₺ açık izlenmeli.")
            if watch_products:
                item = watch_products[0]
                actions.append(f"{item['product_name']} hedefe yakın (%{item['realization_percent']:.1f}); kısa vadeli saha odağıyla tamamlanabilir.")
            if critical_reps:
                item = critical_reps[0]
                actions.append(f"{item['representative_name']} %{item['realization_percent']:.1f} ile bölge içindeki ilk destek önceliği.")
            result_periods[key] = {
                **source,
                "label": label,
                "critical_products": critical_products,
                "watch_products": watch_products,
                "critical_representatives": critical_reps,
                "insights": insights,
                "actions": actions or ["Kritik eşik altında ürün veya temsilci bulunmuyor; mevcut saha planını koruyun."],
            }

        brick_signals = []
        if scope_type == "representative" and market_analysis:
            for row in market_analysis.get("brick_product_rows", []):
                market = float(row.get("market_unit") or 0)
                company = float(row.get("company_unit") or 0)
                brick_signals.append({
                    "brick": row.get("brick") or "Brick",
                    "product_name": row.get("product_name") or "Ürün",
                    "company_unit": company,
                    "competitor_unit": float(row.get("competitor_unit") or 0),
                    "share_percent": round(company * 100 / market, 1) if market else 0.0,
                })
            brick_signals.sort(key=lambda row: (row["share_percent"], -row["competitor_unit"], row["brick"]))

        return {
            "scope_type": scope_type,
            "scope_name": scope_name,
            "periods": result_periods,
            "brick_signals": brick_signals[:6],
            "method_note": "Hedefler ve kesinleşmiş satışlar P2 > P1 > IMS kaynak önceliğiyle değerlendirilir.",
        }
