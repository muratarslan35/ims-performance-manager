from pathlib import Path


def patch_dashboard():
    path = Path("app/query/dashboard_query.py")
    source = path.read_text(encoding="utf-8")
    anchor = "from app.services.production_result_service import ProductionResultService\n"
    import_line = "from app.services.official_aggregate_service import OfficialAggregateService, ACTUAL_TYPE\n"
    if import_line not in source:
        if anchor not in source:
            raise RuntimeError("dashboard import anchor missing")
        source = source.replace(anchor, anchor + import_line, 1)

    marker = "        upload_id = self.session.query(IMSUpload.id).filter(\n"
    block = '''        official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
        official_actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
        if official and official_actual_rows:
            if ProductionResultService.final_upload(filters.year, filters.month):
                actuals = {}
                for target_row in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                    effective = ProductionResultService.effective_product(filters.year, filters.month, target_row.representative_id, target_row.product_id)
                    bucket = actuals.setdefault(target_row.product_id, [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(effective.get("actual_tl") or 0))
                    bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
                for item in official:
                    values = actuals.get(item["product_id"], [Decimal("0"), Decimal("0")])
                    item["actual_tl"] = float(values[0])
                    item["actual_unit"] = float(values[1])
            products = [{
                "product_id": item["product_id"], "product_name": item["product_name"],
                "target_tl": round(float(item["target_tl"] or 0), 2),
                "actual_tl": round(float(item["actual_tl"] or 0), 2),
                "unit_target": round(float(item["target_unit"] or 0), 2),
                "unit_actual": round(float(item["actual_unit"] or 0), 2),
            } for item in official]
            for item in products:
                item["realization_percent"] = round(item["actual_tl"] * 100 / item["target_tl"], 1) if item["target_tl"] else 0.0
                item["unit_realization_percent"] = round(item["unit_actual"] * 100 / item["unit_target"], 1) if item["unit_target"] else 0.0
            target = sum(item["target_tl"] for item in products)
            actual = sum(item["actual_tl"] for item in products)
            unit_target = sum(item["unit_target"] for item in products)
            unit_actual = sum(item["unit_actual"] for item in products)
            return {
                "source": "Resmi NATIONAL hedef / kabul edilen gerçekleşme kaynağı",
                "target_tl": round(target, 2), "actual_tl": round(actual, 2),
                "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
                "unit_target": round(unit_target, 2), "unit_actual": round(unit_actual, 2),
                "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
                "products": products,
            }

'''
    if 'OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")' not in source:
        if marker not in source:
            raise RuntimeError("dashboard method anchor missing")
        source = source.replace(marker, block + marker, 1)
    path.write_text(source, encoding="utf-8")


def patch_region():
    path = Path("app/services/region_performance_service.py")
    source = path.read_text(encoding="utf-8")
    anchor = "from app.services.production_result_service import ProductionResultService\n"
    import_line = "from app.services.official_aggregate_service import OfficialAggregateService, ACTUAL_TYPE\n"
    if import_line not in source:
        if anchor not in source:
            raise RuntimeError("region import anchor missing")
        source = source.replace(anchor, anchor + import_line, 1)

    aggregate_anchor = "    def aggregate(self, months):\n"
    helper = '''    def _official_period(self, months):
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

'''
    if "    def _official_period(self, months):" not in source:
        if aggregate_anchor not in source:
            raise RuntimeError("region aggregate anchor missing")
        source = source.replace(aggregate_anchor, helper + aggregate_anchor, 1)

    old = '''        product_rows = [{"product_id": pid, "product_name": products[pid].product_name if pid in products else f"Ürün {pid}", **result_row(vals)} for pid, vals in product_totals.items()]
        product_rows.sort(key=lambda row: (-(row["actual_tl"] or Decimal("0")), row["product_name"]))
        representative_rows = [{"representative_id": rid, "representative_name": reps[rid].rep_name, "city": reps[rid].city or "-", "active": bool(reps[rid].active), "is_vacant": "boş" in (reps[rid].rep_name or "").casefold() or (reps[rid].rep_name or "").strip().upper() == "BOS", **result_row(vals)} for rid, vals in rep_totals.items()]
        representative_rows.sort(key=lambda row: (-(row["realization_percent"] or Decimal("0")), -(row["actual_tl"] or Decimal("0"))))
        monthly_rows = [{"year": year, "month": month, "label": f"{month:02d}/{year}", **result_row(month_totals[(year, month)])} for year, month in months]
        return {"target_tl": total_target, "actual_tl": total_actual if complete else None, "realization_percent": self.percent(total_actual, total_target) if complete else None, "gap_tl": (total_target-total_actual) if complete else None, "complete": complete, "products": product_rows, "representatives": representative_rows, "months": monthly_rows}
'''
    new = '''        product_rows = [{"product_id": pid, "product_name": products[pid].product_name if pid in products else f"Ürün {pid}", **result_row(vals)} for pid, vals in product_totals.items()]
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
'''
    if "official = self._official_period(months)" not in source:
        if old not in source:
            raise RuntimeError("region return block anchor missing")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    patch_dashboard()
    patch_region()
