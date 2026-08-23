"""Deterministic managerial insights for region and representative scopes."""

from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService


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
        # The batch service resolves the six-month source set once and reuses it
        # for the overlapping 1/3/6-month windows.  It preserves the canonical
        # P2 > P1 > IMS product-level precedence without the former N+1 fan-out.
        return RepresentativePeriodSnapshotService.build(representative_id, year, month)

    @classmethod
    def build(cls, *, scope_type, scope_name, periods, market_analysis=None, competitive_intelligence=None):
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
                gap_tl = float(source.get("gap_tl") or 0)
                gap_text = (
                    f"hedef üzeri gerçekleşme {abs(gap_tl):,.0f} ₺"
                    if gap_tl < 0 else f"hedef açığı {gap_tl:,.0f} ₺"
                )
                insights.append(f"{label} gerçekleşme %{percent:.1f}; {gap_text}.")
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
            "competitive_intelligence": competitive_intelligence or {},
            "method_note": "Hedefler ve kesinleşmiş satışlar P2 > P1 > IMS kaynak önceliğiyle değerlendirilir.",
        }
