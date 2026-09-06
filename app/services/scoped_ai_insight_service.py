"""Deterministic managerial insights for region and representative scopes."""

from collections import defaultdict

from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService


class ScopedAIInsightService:
    """Explain verified performance data without changing source calculations."""

    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6))
    PERIOD_LABELS = {
        "monthly": "Aylık",
        "quarterly": "3 Aylık",
        "half_year": "6 Aylık",
        "yearly": "YILLIK YTD",
        "q1": "Q1",
        "q2": "Q2",
        "q3": "Q3",
        "q4": "Q4",
    }
    SYNTHETIC_MARKET_TOKENS = (
        "EKIP 4",
        "EKİP 4",
        "EKIP4",
        "EKİP4",
        "TOPLAM PAZAR",
        "TOTAL MARKET",
        "GRAND TOTAL",
        "SUBTOTAL",
    )

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
        # for the overlapping 1/3/6-month windows. It preserves canonical
        # P2 > P1 > IMS product-level precedence without N+1 fan-out.
        return RepresentativePeriodSnapshotService.build(representative_id, year, month)

    @classmethod
    def _is_synthetic_market_row(cls, row):
        values = (
            row.get("brick"), row.get("product"), row.get("group"), row.get("side"),
            row.get("name"), row.get("territory"),
        )
        haystack = " ".join(str(value or "").upper() for value in values)
        return any(token in haystack for token in cls.SYNTHETIC_MARKET_TOKENS)

    @classmethod
    def _sanitize_competitive_intelligence(cls, payload):
        source = payload or {}
        result = dict(source)
        for key in ("weekly_alerts", "monthly_trends", "own_gaps"):
            result[key] = [
                row for row in source.get(key, [])
                if not cls._is_synthetic_market_row(row)
            ]
        return result

    @classmethod
    def _province_rows(cls, representatives):
        buckets = defaultdict(lambda: {
            "target_tl": 0.0,
            "actual_tl": 0.0,
            "representative_count": 0,
            "complete": True,
        })
        for row in representatives:
            city = str(row.get("city") or "").strip()
            if not city:
                continue
            bucket = buckets[city]
            bucket["target_tl"] += float(row.get("target_tl") or 0)
            actual = row.get("actual_tl")
            row_complete = row.get("complete", actual is not None)
            if not row_complete or actual is None:
                bucket["complete"] = False
            else:
                bucket["actual_tl"] += float(actual or 0)
            bucket["representative_count"] += 1

        result = []
        for city, bucket in buckets.items():
            target = bucket["target_tl"]
            actual = bucket["actual_tl"]
            complete = bucket["complete"]
            percent = cls._percent(actual, target) if complete and target else None
            gap = target - actual if complete else None
            result.append({
                "city": city,
                "target_tl": target,
                "actual_tl": actual if complete else None,
                "realization_percent": percent,
                "gap_tl": gap,
                "representative_count": bucket["representative_count"],
                "complete": complete,
            })
        return sorted(
            result,
            key=lambda item: (
                item["realization_percent"] is None,
                item["realization_percent"] if item["realization_percent"] is not None else 9999,
                -(item["gap_tl"] or 0),
                item["city"],
            ),
        )

    @classmethod
    def build(cls, *, scope_type, scope_name, periods, market_analysis=None, competitive_intelligence=None):
        result_periods = {}
        for key, source in periods.items():
            label = source.get("label") or cls.PERIOD_LABELS.get(key, key)
            products = sorted(
                source.get("products", []),
                key=lambda row: (
                    row.get("realization_percent") is None,
                    row.get("realization_percent") or 0,
                    -(float(row.get("gap_tl") or 0)),
                ),
            )
            representatives = sorted(
                source.get("representatives", []),
                key=lambda row: (
                    row.get("realization_percent") is None,
                    row.get("realization_percent") or 0,
                ),
            )
            critical_products = [
                row for row in products
                if row.get("realization_percent") is not None and row["realization_percent"] < 75
            ][:5]
            watch_products = [
                row for row in products
                if row.get("realization_percent") is not None and 75 <= row["realization_percent"] < 100
            ][:5]
            critical_reps = [
                row for row in representatives
                if row.get("realization_percent") is not None and row["realization_percent"] < 75
            ][:5]
            province_rows = cls._province_rows(representatives) if scope_type == "region" else []
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
                insights.append(f"{label} gerçekleşme %{float(percent):.1f}; {gap_text}.")
                if percent >= 100:
                    insights.append("Toplam hedef karşılandı; odağı ürün bazında hedef altında kalan kalemlere yöneltin.")
                elif percent >= 75:
                    insights.append("Hedefe yakın seyir var; açık ürünlerde yoğunlaşma dönem sonucunu belirleyecek.")
                else:
                    insights.append("Kritik hedef açığı bulunuyor; ürün ve saha önceliklerinin yeniden planlanması gerekiyor.")

            if province_rows:
                weakest = next((item for item in province_rows if item["realization_percent"] is not None), None)
                strongest = next(
                    (item for item in reversed(province_rows) if item["realization_percent"] is not None),
                    None,
                )
                if weakest:
                    insights.append(
                        f"İl bazında en düşük gerçekleşme {weakest['city']} %{weakest['realization_percent']:.1f}; "
                        f"{max(float(weakest['gap_tl'] or 0), 0):,.0f} ₺ hedef açığı bulunuyor."
                    )
                    if weakest["realization_percent"] < 100:
                        actions.append(
                            f"{weakest['city']} ilinde {weakest['representative_count']} temsilcinin ürün açıklarını birlikte inceleyin."
                        )
                if strongest and strongest is not weakest:
                    insights.append(
                        f"En yüksek il gerçekleşmesi {strongest['city']} %{strongest['realization_percent']:.1f}; "
                        "iyi uygulamalar düşük performanslı illerle karşılaştırılabilir."
                    )

            if critical_products:
                item = critical_products[0]
                actions.append(
                    f"{item['product_name']} %{float(item['realization_percent']):.1f} ile ilk ürün önceliği; "
                    f"{float(item.get('gap_tl') or 0):,.0f} ₺ açık izlenmeli."
                )
            if watch_products:
                item = watch_products[0]
                actions.append(
                    f"{item['product_name']} hedefe yakın (%{float(item['realization_percent']):.1f}); "
                    "kısa vadeli saha odağıyla tamamlanabilir."
                )
            if critical_reps:
                item = critical_reps[0]
                actions.append(
                    f"{item['representative_name']} %{float(item['realization_percent']):.1f} ile bölge içindeki ilk destek önceliği."
                )

            result_periods[key] = {
                **source,
                "label": label,
                "critical_products": critical_products,
                "watch_products": watch_products,
                "critical_representatives": critical_reps,
                "province_rows": province_rows[:8],
                "insights": insights,
                "actions": actions or ["Kritik eşik altında ürün veya temsilci bulunmuyor; mevcut saha planını koruyun."],
            }

        brick_signals = []
        if scope_type == "representative" and market_analysis:
            for row in market_analysis.get("brick_product_rows", []):
                if cls._is_synthetic_market_row(row):
                    continue
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

        competitive = cls._sanitize_competitive_intelligence(competitive_intelligence)
        return {
            "scope_type": scope_type,
            "scope_name": scope_name,
            "periods": result_periods,
            "brick_signals": brick_signals[:6],
            "competitive_intelligence": competitive,
            "method_note": (
                "Hedefler ve kesinleşmiş satışlar P2 > P1 > IMS kaynak önceliğiyle değerlendirilir; "
                "rekabet sinyallerinde yalnız gerçek ürün/brick satırları ve ardışık IMS karşılaştırmaları kullanılır."
            ),
        }
