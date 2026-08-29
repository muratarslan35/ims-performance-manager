from collections import defaultdict
from decimal import Decimal

from sqlalchemy import and_, func, or_, desc

from app.extensions import db
from app.models import IMSRawData, IMSUpload, Product, ProductionRegionProductResult, Representative, Target
from app.services.annual_realization_service import AnnualRealizationService
from app.services.official_aggregate_service import OfficialAggregateService, TARGET_TYPE, ACTUAL_TYPE
from app.services.production_result_service import ProductionResultService


class RegionPerformanceService:
    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6), ("yearly", "Yıllık", None))

    def __init__(self, region_key, year, month):
        self.region_key = str(region_key).strip()
        self.year = int(year)
        self.month = int(month)
        if not self.region_key or self.month < 1 or self.month > 12:
            raise ValueError("Geçersiz bölge veya dönem.")
        master_representatives = Representative.query.filter(
            or_(
                Representative.region == self.region_key,
                Representative.city == self.region_key,
                Representative.territory == self.region_key,
            ),
        ).order_by(Representative.rep_name.asc()).all()
        if not master_representatives:
            raise ValueError("Bölge bulunamadı.")

        # Representative master history intentionally retains people who moved
        # between teams. The current month's Target rows form the active IMS
        # roster snapshot after a replace import. Use that scope for region
        # detail/market calculations whenever it is available.
        master_ids = [item.id for item in master_representatives]
        period_rep_ids = {
            int(row[0])
            for row in db.session.query(Target.representative_id).filter(
                Target.year == self.year,
                Target.month == self.month,
                Target.representative_id.in_(master_ids),
            ).distinct().all()
            if row[0] is not None
        }
        self.representatives = (
            [item for item in master_representatives if item.id in period_rep_ids]
            if period_rep_ids else master_representatives
        )
        self.rep_ids = [item.id for item in self.representatives]

    @staticmethod
    def shift_month(year, month, delta):
        ordinal = year * 12 + month - 1 + delta
        return ordinal // 12, ordinal % 12 + 1

    def _latest_completed_period(self):
        row = db.session.query(IMSUpload.year, IMSUpload.month).filter(
            IMSUpload.status == "COMPLETED",
            IMSUpload.year == self.year,
        ).order_by(
            IMSUpload.month.desc(), IMSUpload.week_number.desc(),
            IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
        ).first()
        return (int(row[0]), int(row[1])) if row else (self.year, self.month)

    def period_months(self, length):
        if length == 1:
            return [(self.year, self.month)]
        anchor_year, anchor_month = self._latest_completed_period()
        if length is None:
            return [(anchor_year, month) for month in range(1, anchor_month + 1)]
        return [self.shift_month(anchor_year, anchor_month, delta) for delta in range(-(length - 1), 1)]

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

    def _official_ims_region_month(self, year, month):
        """Return the workbook-authoritative region target and actual metrics.

        P2/P1 production remains first. For IMS, prefer persisted official
        region target/actual aggregates. Some cumulative IMS workbooks expose
        region target + remaining balance but no separate weekly region actual;
        in that case actual is exactly target minus remaining balance from the
        same official region row. This keeps region authority and avoids summing
        representative rows whose scope can differ from the official subtotal.
        """
        production_upload = ProductionResultService.final_upload(year, month)
        if production_upload is not None:
            production_rows = ProductionRegionProductResult.query.filter_by(
                upload_id=production_upload.id, region_code=self.region_key
            ).all()
            if production_rows:
                return {
                    row.product_id: [
                        Decimal(str(row.target_tl or 0)),
                        Decimal(str(row.actual_tl or 0)),
                        True,
                    ]
                    for row in production_rows
                }

        official_targets = OfficialAggregateService.rows(year, month, self.region_key, TARGET_TYPE)
        if official_targets:
            official_actuals = {
                row.product_id: row
                for row in OfficialAggregateService.rows(year, month, self.region_key, ACTUAL_TYPE)
            }
            upload_id = OfficialAggregateService.latest_upload_id(year, month, TARGET_TYPE)
            balances = {}
            if upload_id:
                balances = {
                    product_id: Decimal(str(balance_tl or 0))
                    for product_id, balance_tl in db.session.query(
                        IMSRawData.product_id, IMSRawData.tl
                    ).filter(
                        IMSRawData.upload_id == upload_id,
                        IMSRawData.sheet_type == "dashboard_balance_region",
                        IMSRawData.territory == self.region_key,
                    ).all()
                }
            result = {}
            for target in official_targets:
                target_tl = Decimal(str(target.tl or 0))
                actual_row = official_actuals.get(target.product_id)
                if actual_row is not None:
                    result[target.product_id] = [
                        target_tl, Decimal(str(actual_row.tl or 0)), True
                    ]
                elif target.product_id in balances:
                    result[target.product_id] = [
                        target_tl, target_tl - balances[target.product_id], True
                    ]
                else:
                    result[target.product_id] = [target_tl, Decimal("0"), False]
            return result

        # Legacy compatibility for imports created before official aggregates.
        upload_id = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == year,
            IMSUpload.month == month,
            IMSUpload.status == "COMPLETED",
        ).order_by(desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id:
            return {}
        prefix = f"{self.region_key}%"
        balance = db.session.query(
            IMSRawData.product_id, IMSRawData.unit
        ).filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.sheet_type == "dashboard_balance_region",
            IMSRawData.territory.like(prefix),
        ).all()
        if not balance:
            return {}
        weekly = {
            row[0]: (Decimal(str(row[1] or 0)), True)
            for row in db.session.query(
                IMSRawData.product_id, IMSRawData.tl
            ).filter(
                IMSRawData.upload_id == upload_id,
                IMSRawData.sheet_type == "dashboard_weekly_region",
                IMSRawData.territory.like(prefix),
            ).all()
        }
        return {
            product_id: [
                Decimal(str(target_tl or 0)),
                weekly.get(product_id, (Decimal("0"), False))[0],
                weekly.get(product_id, (Decimal("0"), False))[1],
            ]
            for product_id, target_tl in balance
        }

    def aggregate(self, months):
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

        reps = {item.id: item for item in self.representatives}
        rep_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        person_month_product = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        for (year, month, rep_id, product_id), values in cells.items():
            target, actual, row_complete = values["target"], values["actual"], values["complete"]
            rep_bucket = rep_totals[rep_id]
            rep_bucket[0] += target
            rep_bucket[1] += actual
            rep_bucket[2] = rep_bucket[2] and row_complete
            bucket = person_month_product[(year, month, product_id)]
            bucket[0] += target
            bucket[1] += actual
            bucket[2] = bucket[2] and row_complete

        product_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        month_totals = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        source_by_month = {}
        all_product_ids = set()
        for year, month in months:
            official = self._official_ims_region_month(year, month)
            if official:
                month_source = {(year, month, pid): vals for pid, vals in official.items()}
                source_by_month[(year, month)] = "OFFICIAL_REGION_SUBTOTAL"
            else:
                month_source = {
                    key: vals for key, vals in person_month_product.items()
                    if key[0] == year and key[1] == month
                }
                source_by_month[(year, month)] = "REPRESENTATIVE_AGGREGATE"
            for (_, _, product_id), vals in month_source.items():
                target, actual, row_complete = vals
                all_product_ids.add(product_id)
                for bucket in (product_totals[product_id], month_totals[(year, month)]):
                    bucket[0] += target
                    bucket[1] += actual
                    bucket[2] = bucket[2] and row_complete

        products = {
            item.id: item
            for item in Product.query.filter(Product.id.in_(all_product_ids)).all()
        } if all_product_ids else {}
        total_target = sum((vals[0] for vals in month_totals.values()), Decimal("0"))
        total_actual = sum((vals[1] for vals in month_totals.values()), Decimal("0"))
        complete = all(vals[2] for vals in month_totals.values()) if month_totals else False

        def result_row(vals):
            target, actual, row_complete = vals
            return {
                "target_tl": target,
                "actual_tl": actual if row_complete else None,
                "realization_percent": self.percent(actual, target) if row_complete else None,
                "gap_tl": (target - actual) if row_complete else None,
                "complete": row_complete,
            }

        product_rows = [
            {
                "product_id": pid,
                "product_name": products[pid].product_name if pid in products else f"Ürün {pid}",
                **result_row(vals),
            }
            for pid, vals in product_totals.items()
        ]
        product_rows.sort(key=lambda row: (-(row["actual_tl"] or Decimal("0")), row["product_name"]))
        representative_rows = [
            {
                "representative_id": rid,
                "representative_name": reps[rid].rep_name,
                "city": reps[rid].city or "-",
                "active": bool(reps[rid].active),
                "is_vacant": "boş" in (reps[rid].rep_name or "").casefold() or (reps[rid].rep_name or "").strip().upper() == "BOS",
                **result_row(vals),
            }
            for rid, vals in rep_totals.items()
        ]
        representative_rows.sort(key=lambda row: (-(row["realization_percent"] or Decimal("0")), -(row["actual_tl"] or Decimal("0"))))
        monthly_rows = [
            {
                "year": year, "month": month, "label": f"{month:02d}/{year}",
                "source": source_by_month.get((year, month)),
                **result_row(month_totals[(year, month)]),
            }
            for year, month in months
        ]
        return {
            "target_tl": total_target,
            "actual_tl": total_actual if complete else None,
            "realization_percent": self.percent(total_actual, total_target) if complete else None,
            "gap_tl": (total_target-total_actual) if complete else None,
            "complete": complete,
            "products": product_rows,
            "representatives": representative_rows,
            "months": monthly_rows,
            "source_by_month": source_by_month,
        }

    def _annual_region_realization(self):
        """Build the 12-month chart from the same region authority as monthly KPI.

        Each month first uses the official region subtotal selected by
        ``_official_ims_region_month`` (including P2/P1 precedence). Only months
        without an official region source fall back to the legacy representative
        annual series, preserving historical compatibility without allowing a
        representative aggregate to override an available official subtotal.
        """
        legacy_rows = {
            int(row["month"]): row
            for row in AnnualRealizationService.build(self.year, self.rep_ids)
        }
        rows = []
        for month, label in enumerate(AnnualRealizationService.MONTHS, start=1):
            official = self._official_ims_region_month(self.year, month)
            if official:
                target = sum((values[0] for values in official.values()), Decimal("0"))
                complete = all(values[2] for values in official.values())
                actual = sum((values[1] for values in official.values()), Decimal("0")) if complete else None
                percent = self.percent(actual, target) if complete and target else None
                rows.append({
                    "month": month,
                    "label": label,
                    "target_tl": round(float(target), 2),
                    "actual_tl": round(float(actual), 2) if actual is not None else 0.0,
                    "percent": round(float(percent), 1) if percent is not None else None,
                    "has_data": bool(target),
                    "source": "OFFICIAL_REGION_SUBTOTAL",
                })
                continue

            legacy = legacy_rows[month]
            rows.append({**legacy, "source": "REPRESENTATIVE_AGGREGATE"})
        return rows

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
        vacant_count = sum(
            1 for rep in self.representatives
            if "boş" in (rep.rep_name or "").casefold() or (rep.rep_name or "").strip().upper() == "BOS"
        )
        display_name = (city or self.region_key).upper()
        return {
            "region_key": self.region_key,
            "region_name": display_name,
            "year": self.year,
            "month": self.month,
            "representative_count": len(self.representatives),
            "active_count": active_count,
            "vacant_count": vacant_count,
            "manager": primary.manager or "-",
            "periods": periods,
            "annual_realization": self._annual_region_realization(),
        }
