from collections import defaultdict
from decimal import Decimal

from sqlalchemy import and_, func, or_

from app.extensions import db
from app.models import Product, Representative, Target
from app.services.annual_realization_service import AnnualRealizationService
from app.services.production_result_service import ProductionResultService
from app.services.official_aggregate_service import OfficialAggregateService, ACTUAL_TYPE


class RegionPerformanceService:
    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6), ("yearly", "Yıllık", None))

    def __init__(self, region_key, year, month):
        self.region_key = str(region_key).strip()
        self.year = int(year)
        self.month = int(month)
        if not self.region_key or self.month < 1 or self.month > 12:
            raise ValueError("Geçersiz bölge veya dönem.")
        # Kadro doluluğu hesaplamayı etkilemez. BOŞ/BOS dahil bölgeye bağlı
        # bütün ticari kadrolar hedef ve gerçekleşmelerde korunur.
        self.representatives = Representative.query.filter(
            or_(
                Representative.region == self.region_key,
                Representative.city == self.region_key,
                Representative.territory == self.region_key,
            ),
        ).order_by(Representative.rep_name.asc()).all()
        if not self.representatives:
            raise ValueError("Bölge bulunamadı.")
        self.rep_ids = [item.id for item in self.representatives]

    @staticmethod
    def shift_month(year, month, delta):
        ordinal = year * 12 + month - 1 + delta
        return ordinal // 12, ordinal % 12 + 1

    def period_months(self, length):
        if length is None:
            return [(self.year, month) for month in range(1, self.month + 1)]
        return [self.shift_month(self.year, self.month, delta) for delta in range(-(length - 1), 1)]

    @staticmethod
    def percent(actual, target):
        actual, target = Decimal(str(actual or 0)), Decimal(str(target or 0))
        return actual * Decimal("100") / target if target else Decimal("0")

    def _target_rows(self, months):
        conditions = [and_(Target.year == year, Target.month == month) for year, month in months]
        return db.session.query(
            Target.year, Target.month, Target.representative_id, Target.product_id,
            func.coalesce(func.sum(Target.tl_target), 0.0),
        ).filter(Target.representative_id.in_(self.rep_ids), or_(*conditions)).group_by(
            Target.year, Target.month, Target.representative_id, Target.product_id
        ).all()

    def _official_period(self, months):
        # Production result stages remain authoritative once present. For pure
        # IMS periods, use the workbook's explicit region aggregate rows.
        if any(ProductionResultService.final_upload(year, month) for year, month in months):
            return None
        product_totals = defaultdict(lambda: {"target_tl": Decimal("0"), "actual_tl": Decimal("0"), "target_unit": Decimal("0"), "actual_unit": Decimal("0")})
        month_totals = {}
        for year, month in months:
            rows = OfficialAggregateService.product_totals(year, month, self.region_key)
            actual_rows = OfficialAggregateService.rows(year, month, self.region_key, ACTUAL_TYPE)
            if not rows or not actual_rows:
                return None
            month_target = month_actual = month_target_unit = month_actual_unit = Decimal("0")
            for row in rows:
                bucket = product_totals[row["product_id"]]
                target_tl = Decimal(str(row["target_tl"] or 0))
                actual_tl = Decimal(str(row["actual_tl"] or 0))
                target_unit = Decimal(str(row["target_unit"] or 0))
                actual_unit = Decimal(str(row["actual_unit"] or 0))
                bucket["product_name"] = row["product_name"]
                bucket["target_tl"] += target_tl
                bucket["actual_tl"] += actual_tl
                bucket["target_unit"] += target_unit
                bucket["actual_unit"] += actual_unit
                month_target += target_tl
                month_actual += actual_tl
                month_target_unit += target_unit
                month_actual_unit += actual_unit
            month_totals[(year, month)] = (month_target, month_actual, month_target_unit, month_actual_unit)
        return {"products": product_totals, "months": month_totals}

    def aggregate(self, months):
        # Targets remain the exact company-provided values. Actual TL is always
        # resolved through the central accepted-source service: P2 > P1 > IMS.
        cells = defaultdict(lambda: {"target": Decimal("0"), "actual": Decimal("0"), "complete": True})
        for year, month, rep_id, product_id, target in self._target_rows(months):
            key = (year, month, rep_id, product_id)
            exact_target = Decimal(str(target or 0))
            cells[key]["target"] += exact_target
            effective = ProductionResultService.effective_product(year, month, rep_id, product_id)
            if not effective["complete"] or effective["actual_tl"] is None:
                cells[key]["complete"] = False
            else:
                cells[key]["actual"] += Decimal(str(effective["actual_tl"]))

        products = {item.id: item for item in Product.query.filter(Product.id.in_({key[3] for key in cells})).all()} if cells else {}
        reps = {item.id: item for item in self.representatives}
        product_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        rep_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        month_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        total_target = total_actual = Decimal("0")
        complete = True
        for (year, month, rep_id, product_id), values in cells.items():
            target, actual, row_complete = values["target"], values["actual"], values["complete"]
            for bucket in (product_totals[product_id], rep_totals[rep_id], month_totals[(year, month)]):
                bucket[0] += target; bucket[1] += actual; bucket[2] = bucket[2] and row_complete
            total_target += target; total_actual += actual; complete = complete and row_complete

        def result_row(vals):
            target, actual, row_complete = vals
            return {"target_tl": target, "actual_tl": actual if row_complete else None, "realization_percent": self.percent(actual, target) if row_complete else None, "gap_tl": (target - actual) if row_complete else None, "complete": row_complete}

        product_rows = [{"product_id": pid, "product_name": products[pid].product_name if pid in products else f"Ürün {pid}", **result_row(vals)} for pid, vals in product_totals.items()]
        product_rows.sort(key=lambda row: (-(row["actual_tl"] or Decimal("0")), row["product_name"]))
        representative_rows = [{"representative_id": rid, "representative_name": reps[rid].rep_name, "city": reps[rid].city or "-", "active": bool(reps[rid].active), "is_vacant": "boş" in (reps[rid].rep_name or "").casefold() or (reps[rid].rep_name or "").strip().upper() == "BOS", **result_row(vals)} for rid, vals in rep_totals.items()]
        representative_rows.sort(key=lambda row: (-(row["realization_percent"] or Decimal("0")), -(row["actual_tl"] or Decimal("0"))))
        monthly_rows = [{"year": year, "month": month, "label": f"{month:02d}/{year}", **result_row(month_totals[(year, month)])} for year, month in months]
        official = self._official_period(months)
        target_unit = actual_unit = None
        if official:
            total_target = sum((row["target_tl"] for row in official["products"].values()), Decimal("0"))
            total_actual = sum((row["actual_tl"] for row in official["products"].values()), Decimal("0"))
            target_unit = sum((row["target_unit"] for row in official["products"].values()), Decimal("0"))
            actual_unit = sum((row["actual_unit"] for row in official["products"].values()), Decimal("0"))
            complete = True
            product_rows = []
            for pid, row in official["products"].items():
                product_rows.append({
                    "product_id": pid,
                    "product_name": row.get("product_name", products[pid].product_name if pid in products else f"Ürün {pid}"),
                    "target_tl": row["target_tl"], "actual_tl": row["actual_tl"],
                    "realization_percent": self.percent(row["actual_tl"], row["target_tl"]),
                    "gap_tl": row["target_tl"] - row["actual_tl"], "complete": True,
                    "target_unit": row["target_unit"], "actual_unit": row["actual_unit"],
                    "unit_realization_percent": self.percent(row["actual_unit"], row["target_unit"]),
                })
            product_rows.sort(key=lambda row: (-row["actual_tl"], row["product_name"]))
            monthly_rows = []
            for year, month in months:
                mt, ma, mtu, mau = official["months"][(year, month)]
                monthly_rows.append({
                    "year": year, "month": month, "label": f"{month:02d}/{year}",
                    "target_tl": mt, "actual_tl": ma, "realization_percent": self.percent(ma, mt),
                    "gap_tl": mt-ma, "complete": True, "target_unit": mtu, "actual_unit": mau,
                    "unit_realization_percent": self.percent(mau, mtu),
                })
        result = {"target_tl": total_target, "actual_tl": total_actual if complete else None, "realization_percent": self.percent(total_actual, total_target) if complete else None, "gap_tl": (total_target-total_actual) if complete else None, "complete": complete, "products": product_rows, "representatives": representative_rows, "months": monthly_rows}
        if official:
            result.update({"target_unit": target_unit, "actual_unit": actual_unit, "unit_realization_percent": self.percent(actual_unit, target_unit)})
        return result

    def report(self):
        periods = {}
        for key, label, length in self.PERIODS:
            months = self.period_months(length)
            periods[key] = {"key": key, "label": label, "month_count": len(months), **self.aggregate(months)}
        primary = next((rep for rep in self.representatives if rep.active), self.representatives[0])
        city_counts = defaultdict(int)
        for rep in self.representatives:
            city_counts[rep.city or ""] += 1
        city = max(city_counts, key=city_counts.get) if city_counts else ""
        active_count = sum(1 for rep in self.representatives if rep.active)
        vacant_count = sum(1 for rep in self.representatives if "boş" in (rep.rep_name or "").casefold() or (rep.rep_name or "").strip().upper() == "BOS")
        display_name = (city or self.region_key).upper()
        return {"region_key": self.region_key, "region_name": display_name, "year": self.year, "month": self.month, "representative_count": len(self.representatives), "active_count": active_count, "vacant_count": vacant_count, "manager": primary.manager or "-", "periods": periods, "annual_realization": AnnualRealizationService.build(self.year, self.rep_ids)}