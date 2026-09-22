"""Read-only quarterly entitlement report built from representative snapshots."""

from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
)
from app.services.prime_engine import PrimeEngine
from app.services.production_result_service import ProductionResultService


class QuarterEntitlementService:
    """Expose monthly entitlement and Q context from published representative data.

    The Q screen is snapshot-only for monthly target/actual values.  Quota-exit
    selections may lift one selected product to at least 100% for that month,
    but they never invent data or fall back to live IMS/production queries when
    a representative snapshot is missing.
    """

    def __init__(self, representative_id, year, quarter, quota_exit_by_month=None):
        self.representative_id = int(representative_id)
        self.year = int(year)
        self.quarter = int(quarter)
        if self.quarter not in (1, 2, 3, 4):
            raise ValueError("Quarter 1 ile 4 arasında olmalıdır.")
        self.months = list(range((self.quarter - 1) * 3 + 1, (self.quarter - 1) * 3 + 4))
        self.engine = PrimeEngine(
            self.representative_id, self.year, self.months[-1], use_cache=False
        )
        # Presence of a month key means the user explicitly chose the value;
        # None means "kota çıkış yok". Missing month keys may use official auto-detection.
        self.quota_exit_by_month = {
            int(month): (int(product_id) if product_id not in (None, "") else None)
            for month, product_id in (quota_exit_by_month or {}).items()
            if int(month) in self.months
        }
        self._snapshot_rows = {}
        self._official_quota = self._official_quota_by_month()

    @staticmethod
    def _month_label(month):
        return (
            "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
        )[month - 1]

    @staticmethod
    def _product_identity(snapshot_row):
        product = snapshot_row.get("product") or {}
        if isinstance(product, dict):
            product_id = product.get("id")
            product_name = product.get("product_name") or product.get("name")
        else:
            product_id = getattr(product, "id", None)
            product_name = getattr(product, "product_name", None)
        product_id = product_id or snapshot_row.get("product_id")
        product_name = product_name or snapshot_row.get("product_name") or f"Ürün {product_id}"
        return (int(product_id) if product_id is not None else None, str(product_name))

    def _product_meta(self):
        result = {}
        for product in self.engine.products:
            rule = self.engine.get_prime_rule(product)
            result[int(product.id)] = {
                "product_name": product.product_name,
                "include_in_total_tl": (
                    bool(rule.include_in_total_tl)
                    if rule else bool(getattr(product, "include_total_tl", False))
                ),
                "include_in_prime": (
                    bool(rule.include_in_prime)
                    if rule else bool(getattr(product, "is_prime_product", False))
                ),
                "required_percent": (
                    float(rule.required_percent)
                    if rule else float(getattr(product, "required_percent", 0) or 0)
                ),
            }
        return result

    def _official_quota_by_month(self):
        detected = ProductionResultService.quota_product_months(
            [(self.year, month) for month in self.months]
        )
        result = {}
        for product_id, periods in detected.items():
            for year, month in periods:
                if int(year) == self.year and int(month) in self.months:
                    result.setdefault(int(month), []).append(int(product_id))
        return result

    def _snapshot_month(self, month):
        workspace = PersistentRepresentativeSnapshotService.get_active(
            self.representative_id, self.year, month
        )
        if not workspace:
            return None
        monthly = (workspace.get("snapshots") or {}).get("monthly")
        if not isinstance(monthly, dict):
            return None
        months = {
            (int(item[0]), int(item[1]))
            for item in (monthly.get("months") or [])
            if isinstance(item, (list, tuple)) and len(item) >= 2
        }
        if months and (self.year, int(month)) not in months:
            return None
        return monthly

    def _selected_quota_product(self, month, available_ids):
        if month in self.quota_exit_by_month:
            selected = self.quota_exit_by_month[month]
            return selected if selected in available_ids else None, False
        official = [
            product_id
            for product_id in self._official_quota.get(month, [])
            if product_id in available_ids
        ]
        return (official[0] if official else None), bool(official)

    def _snapshot_products(self, month):
        monthly = self._snapshot_month(month)
        if monthly is None:
            self._snapshot_rows[month] = None
            return None, None, False

        meta = self._product_meta()
        rows = []
        for snapshot_row in monthly.get("products") or []:
            product_id, product_name = self._product_identity(snapshot_row)
            if product_id is None:
                continue
            config = meta.get(product_id, {})
            target_tl = float(snapshot_row.get("target_tl") or 0)
            actual_tl = float(snapshot_row.get("actual_tl") or 0)
            target_unit = float(snapshot_row.get("target_unit") or 0)
            actual_unit = float(snapshot_row.get("actual_unit") or 0)
            rows.append({
                "product_id": product_id,
                "product_name": config.get("product_name") or product_name,
                "month": month,
                "target_unit": round(target_unit, 2),
                "target_tl": round(target_tl, 2),
                "actual_unit": round(actual_unit, 2),
                "actual_tl": round(actual_tl, 2),
                "percent": round(actual_tl / target_tl * 100.0, 2) if target_tl else 0.0,
                "gap_tl": round(max(0.0, target_tl - actual_tl), 2),
                "required_percent": float(config.get("required_percent") or 0),
                "include_in_total_tl": bool(config.get("include_in_total_tl")),
                "include_in_prime": bool(config.get("include_in_prime")),
                "quota_exit": False,
                "quota_uplift_tl": 0.0,
            })

        available_ids = {row["product_id"] for row in rows}
        selected_id, auto_selected = self._selected_quota_product(month, available_ids)
        if selected_id is not None:
            for row in rows:
                if row["product_id"] != selected_id:
                    continue
                original_actual_tl = row["actual_tl"]
                original_actual_unit = row["actual_unit"]
                row["actual_tl"] = round(max(row["actual_tl"], row["target_tl"]), 2)
                row["actual_unit"] = round(max(row["actual_unit"], row["target_unit"]), 2)
                row["percent"] = (
                    round(row["actual_tl"] / row["target_tl"] * 100.0, 2)
                    if row["target_tl"] else 0.0
                )
                row["gap_tl"] = round(max(0.0, row["target_tl"] - row["actual_tl"]), 2)
                row["quota_exit"] = True
                row["quota_uplift_tl"] = round(row["actual_tl"] - original_actual_tl, 2)
                row["quota_uplift_unit"] = round(row["actual_unit"] - original_actual_unit, 2)
                break

        options = [
            {"id": row["product_id"], "name": row["product_name"]}
            for row in rows
            if row["target_tl"] > 0
        ]
        self._snapshot_rows[month] = rows
        return rows, {
            "selected_id": selected_id,
            "auto_selected": auto_selected,
            "options": options,
        }, True

    def _monthly_row(self, month):
        products, quota, snapshot_available = self._snapshot_products(month)
        if not snapshot_available:
            return {
                "month": month,
                "label": self._month_label(month),
                "target_tl": 0.0,
                "actual_tl": 0.0,
                "total_percent": 0.0,
                "product_success": False,
                "main_prime": 0.0,
                "ciro_prime": 0.0,
                "gross_prime": 0.0,
                "entitlement_type": "Veri yok",
                "blocked_reasons": ["Temsilci snapshot verisi bulunamadı."],
                "has_data": False,
                "snapshot_available": False,
                "products": [],
                "quota_exit": {"selected_id": None, "auto_selected": False, "options": []},
                "quota_uplift_tl": 0.0,
            }

        summary = self.engine.summarize_products(products)
        main_prime = (
            self.engine.calculate_main_prime(summary["total_tl_percent"])
            if summary["prime_eligible"] else 0.0
        )
        ciro_prime = (
            0.0 if summary["prime_eligible"]
            else self.engine.calculate_ciro_prime(summary["total_tl_percent"])
        )
        gross_prime = main_prime or ciro_prime
        if main_prime:
            entitlement_type = "Ana prim"
        elif ciro_prime:
            entitlement_type = "Ciro primi"
        else:
            entitlement_type = "Hakkediş yok"

        quota_uplift_tl = round(sum(row.get("quota_uplift_tl", 0) for row in products), 2)
        return {
            "month": month,
            "label": self._month_label(month),
            "target_tl": summary["total_target"],
            "actual_tl": summary["total_realization"],
            "total_percent": summary["total_tl_percent"],
            "product_success": summary["product_success"],
            "main_prime": main_prime,
            "ciro_prime": ciro_prime,
            "gross_prime": gross_prime,
            "entitlement_type": entitlement_type,
            "blocked_reasons": summary["entitlement"]["blocked_reasons"],
            "has_data": bool(summary["total_target"]),
            "snapshot_available": True,
            "products": products,
            "quota_exit": quota,
            "quota_uplift_tl": quota_uplift_tl,
        }

    def _product_carry(self):
        rows_by_product = {}
        for month in self.months:
            monthly = self._snapshot_rows.get(month)
            if monthly is None:
                # Trigger the same snapshot-only read if report() has not built it yet.
                monthly, _quota, available = self._snapshot_products(month)
                if not available:
                    continue
            for item in monthly or []:
                if not item["include_in_prime"]:
                    continue
                bucket = rows_by_product.setdefault(item["product_id"], {
                    "product": item["product_name"],
                    "is_prime_product": True,
                    "target_tl": 0.0,
                    "actual_tl": 0.0,
                    "target_unit": 0.0,
                    "actual_unit": 0.0,
                })
                bucket["target_tl"] += item["target_tl"]
                bucket["actual_tl"] += item["actual_tl"]
                bucket["target_unit"] += item["target_unit"]
                bucket["actual_unit"] += item["actual_unit"]

        rows = []
        for bucket in rows_by_product.values():
            target_tl = bucket["target_tl"]
            actual_tl = bucket["actual_tl"]
            target_unit = bucket["target_unit"]
            actual_unit = bucket["actual_unit"]
            percent = round(actual_tl / target_tl * 100, 2) if target_tl else 0.0

            def gap(threshold):
                return {
                    "tl": round(max(0.0, target_tl * threshold / 100 - actual_tl), 2),
                    "unit": round(max(0.0, target_unit * threshold / 100 - actual_unit), 2),
                }

            rows.append({
                **bucket,
                "target_tl": round(target_tl, 2),
                "actual_tl": round(actual_tl, 2),
                "target_unit": round(target_unit, 2),
                "actual_unit": round(actual_unit, 2),
                "percent": percent,
                "gap_75": gap(75),
                "gap_90": gap(90),
                "gap_100": gap(100),
            })
        rows.sort(key=lambda row: row["product"])
        return rows

    @staticmethod
    def _q_topup(monthly_paid, cap, *, complete, total_success, product_success):
        """Return only the unpaid Q base entitlement; never reapply monthly steps."""
        if not (complete and total_success and product_success):
            return 0.0
        return round(max(0.0, float(cap) - float(monthly_paid)), 2)

    def report(self):
        monthly = [self._monthly_row(month) for month in self.months]
        total_target = sum(row["target_tl"] for row in monthly)
        total_actual = sum(row["actual_tl"] for row in monthly)
        total_percent = round(total_actual / total_target * 100, 2) if total_target else 0.0
        monthly_paid = round(sum(row["gross_prime"] for row in monthly), 2)
        main_product_rows = [row for row in self._product_carry() if row["is_prime_product"]]
        product_inputs = [
            {
                "product_name": row["product"],
                "percent": row["percent"],
                "include_in_prime": True,
            }
            for row in main_product_rows
        ]
        product_entitlement = self.engine.evaluate_monthly_entitlement(product_inputs)
        required_total = self.engine.get_setting("TOTAL_PERCENT_REQUIRED", 100.0)
        q_cap = round(self.engine.get_setting("MAIN_PRIME", 50000.0) * len(self.months), 2)
        complete = all(row["has_data"] and row.get("snapshot_available", True) for row in monthly)
        q_topup = self._q_topup(
            monthly_paid,
            q_cap,
            complete=complete,
            total_success=total_percent >= required_total,
            product_success=product_entitlement["product_success"],
        )
        if q_topup:
            closing = monthly[-1]
            closing["q_topup"] = q_topup
            closing["gross_prime"] = round(closing["gross_prime"] + q_topup, 2)
            closing["entitlement_type"] = (
                "Q telafi hakkedişi"
                if not closing["main_prime"] and not closing["ciro_prime"]
                else f'{closing["entitlement_type"]} + Q telafi'
            )
        for row in monthly:
            row.setdefault("q_topup", 0.0)
        gross_total = round(monthly_paid + q_topup, 2)
        return {
            "year": self.year,
            "quarter": self.quarter,
            "months": monthly,
            "products": main_product_rows,
            "summary": {
                "target_tl": round(total_target, 2),
                "actual_tl": round(total_actual, 2),
                "remaining_tl": round(max(0.0, total_target - total_actual), 2),
                "total_percent": total_percent,
                "gross_prime": gross_total,
                "monthly_paid": monthly_paid,
                "q_entitlement_cap": q_cap,
                "q_topup": q_topup,
                "q_total_success": complete and total_percent >= required_total,
                "q_product_success": complete and product_entitlement["product_success"],
                "snapshot_complete": complete,
                "quota_uplift_tl": round(sum(row.get("quota_uplift_tl", 0) for row in monthly), 2),
                "main_prime_months": sum(1 for row in monthly if row["main_prime"] > 0),
                "ciro_prime_months": sum(1 for row in monthly if row["ciro_prime"] > 0),
            },
        }
