from collections import defaultdict

from sqlalchemy import and_, func, or_

from app.extensions import db
from app.models import IMSSummary, Product, Representative, Target


class RegionPerformanceService:
    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6), ("yearly", "Yıllık", None))

    def __init__(self, region_key, year, month):
        self.region_key = str(region_key).strip()
        self.year = int(year)
        self.month = int(month)
        if not self.region_key or self.month < 1 or self.month > 12:
            raise ValueError("Geçersiz bölge veya dönem.")
        self.representatives = Representative.query.filter(
            Representative.active.is_(True),
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
        return round(actual * 100 / target, 1) if target else 0.0

    def _target_rows(self, months):
        conditions = [and_(Target.year == year, Target.month == month) for year, month in months]
        return db.session.query(
            Target.year, Target.month, Target.representative_id, Target.product_id,
            func.coalesce(func.sum(Target.tl_target), 0.0),
        ).filter(Target.representative_id.in_(self.rep_ids), or_(*conditions)).group_by(
            Target.year, Target.month, Target.representative_id, Target.product_id
        ).all()

    def _actual_rows(self, months):
        conditions = [and_(IMSSummary.year == year, IMSSummary.month == month) for year, month in months]
        return db.session.query(
            IMSSummary.year, IMSSummary.month, IMSSummary.representative_id, IMSSummary.product_id,
            func.coalesce(func.sum(IMSSummary.tl), 0.0),
        ).filter(IMSSummary.representative_id.in_(self.rep_ids), or_(*conditions)).group_by(
            IMSSummary.year, IMSSummary.month, IMSSummary.representative_id, IMSSummary.product_id
        ).all()

    def aggregate(self, months):
        cells = defaultdict(lambda: {"target": 0.0, "actual": 0.0})
        for year, month, rep_id, product_id, target in self._target_rows(months):
            cells[(year, month, rep_id, product_id)]["target"] += float(target or 0)
        for year, month, rep_id, product_id, actual in self._actual_rows(months):
            cells[(year, month, rep_id, product_id)]["actual"] += float(actual or 0)

        products = {item.id: item for item in Product.query.filter(Product.id.in_({key[3] for key in cells})).all()} if cells else {}
        reps = {item.id: item for item in self.representatives}
        product_totals, rep_totals, month_totals = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
        total_target = total_actual = 0.0
        for (year, month, rep_id, product_id), values in cells.items():
            target, actual = values["target"], values["actual"]
            product_totals[product_id][0] += target; product_totals[product_id][1] += actual
            rep_totals[rep_id][0] += target; rep_totals[rep_id][1] += actual
            month_totals[(year, month)][0] += target; month_totals[(year, month)][1] += actual
            total_target += target; total_actual += actual

        product_rows = [{"product_id": pid, "product_name": products[pid].product_name if pid in products else f"Ürün {pid}", "target_tl": round(vals[0], 2), "actual_tl": round(vals[1], 2), "realization_percent": self.percent(vals[1], vals[0]), "gap_tl": round(vals[0] - vals[1], 2)} for pid, vals in product_totals.items()]
        product_rows.sort(key=lambda row: (-row["actual_tl"], row["product_name"]))
        representative_rows = [{"representative_id": rid, "representative_name": reps[rid].rep_name, "city": reps[rid].city or "-", "target_tl": round(vals[0], 2), "actual_tl": round(vals[1], 2), "realization_percent": self.percent(vals[1], vals[0]), "gap_tl": round(vals[0] - vals[1], 2)} for rid, vals in rep_totals.items()]
        representative_rows.sort(key=lambda row: (-row["realization_percent"], -row["actual_tl"]))
        monthly_rows = [{"year": year, "month": month, "label": f"{month:02d}/{year}", "target_tl": round(month_totals[(year, month)][0], 2), "actual_tl": round(month_totals[(year, month)][1], 2), "realization_percent": self.percent(month_totals[(year, month)][1], month_totals[(year, month)][0]), "gap_tl": round(month_totals[(year, month)][0] - month_totals[(year, month)][1], 2)} for year, month in months]
        return {"target_tl": round(total_target, 2), "actual_tl": round(total_actual, 2), "realization_percent": self.percent(total_actual, total_target), "gap_tl": round(total_target - total_actual, 2), "products": product_rows, "representatives": representative_rows, "months": monthly_rows}

    def report(self):
        periods = {}
        for key, label, length in self.PERIODS:
            months = self.period_months(length)
            periods[key] = {"key": key, "label": label, "month_count": len(months), **self.aggregate(months)}
        primary = self.representatives[0]
        city_counts = defaultdict(int)
        for rep in self.representatives:
            city_counts[rep.city or ""] += 1
        city = max(city_counts, key=city_counts.get) if city_counts else ""
        return {"region_key": self.region_key, "region_name": " ".join(part for part in [self.region_key, city] if part and part != self.region_key), "year": self.year, "month": self.month, "representative_count": len(self.representatives), "manager": primary.manager or "-", "periods": periods}
