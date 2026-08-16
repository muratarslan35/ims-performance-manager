from pathlib import Path
import re


def replace_function(text, name, next_name, replacement):
    pattern = rf"    def {name}\(.*?(?=    def {next_name}\()"
    updated, count = re.subn(pattern, replacement.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"Could not replace {name}: {count}")
    return updated


def patch_importer():
    path = Path("app/services/ims_import_service.py")
    text = path.read_text()
    anchor = "        db.session.flush()\n\n    def clear_week(self, year, week_number):"
    if "persist_official_aggregates(self, year, month)" not in text:
        repl = (
            "        from app.services.official_aggregate_service import persist_official_aggregates\n"
            "        persist_official_aggregates(self, year, month)\n"
            "        db.session.flush()\n\n"
            "    def clear_week(self, year, week_number):"
        )
        if anchor not in text:
            raise SystemExit("Importer anchor not found")
        text = text.replace(anchor, repl, 1)
    path.write_text(text)


def patch_dashboard():
    path = Path("app/query/dashboard_query.py")
    text = path.read_text()
    import_anchor = "from app.services.production_result_service import ProductionResultService\n"
    import_line = "from app.services.official_aggregate_service import OfficialAggregateService, TARGET_TYPE, ACTUAL_TYPE\n"
    if import_line not in text:
        text = text.replace(import_anchor, import_anchor + import_line, 1)

    national = '''    def load_national_dashboard_metrics(self, filters: Optional[DashboardFilterParams] = None) -> dict:
        """Return official company targets with the accepted actual-sales source."""
        if not filters or filters.year is None or filters.month is None:
            return {}
        official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
        actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
        if official and actual_rows:
            if ProductionResultService.final_upload(filters.year, filters.month):
                production = {}
                for target in self.session.query(Target).filter(
                    Target.year == filters.year, Target.month == filters.month
                ).all():
                    effective = ProductionResultService.effective_product(
                        filters.year, filters.month, target.representative_id, target.product_id
                    )
                    bucket = production.setdefault(target.product_id, [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(effective.get("actual_tl") or 0))
                    bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
                for item in official:
                    values = production.get(item["product_id"], [Decimal("0"), Decimal("0")])
                    item["actual_tl"] = float(values[0])
                    item["actual_unit"] = float(values[1])
            products = []
            for item in official:
                row = {
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "target_tl": round(float(item["target_tl"] or 0), 2),
                    "actual_tl": round(float(item["actual_tl"] or 0), 2),
                    "unit_target": round(float(item["target_unit"] or 0), 2),
                    "unit_actual": round(float(item["actual_unit"] or 0), 2),
                }
                row["realization_percent"] = round(row["actual_tl"] * 100 / row["target_tl"], 1) if row["target_tl"] else 0.0
                row["unit_realization_percent"] = round(row["unit_actual"] * 100 / row["unit_target"], 1) if row["unit_target"] else 0.0
                products.append(row)
            target = sum(item["target_tl"] for item in products)
            actual = sum(item["actual_tl"] for item in products)
            unit_target = sum(item["unit_target"] for item in products)
            unit_actual = sum(item["unit_actual"] for item in products)
            return {
                "source": "Resmi NATIONAL hedef / kabul edilen gerçekleşme kaynağı",
                "target_tl": round(target, 2),
                "actual_tl": round(actual, 2),
                "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
                "unit_target": round(unit_target, 2),
                "unit_actual": round(unit_actual, 2),
                "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
                "products": products,
            }
        return {}
'''
    text = replace_function(text, "load_national_dashboard_metrics", "load_product_performance", national)

    product = '''    def load_product_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        if filters.representative_id is None:
            official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
            actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
            if official and actual_rows:
                production = None
                if ProductionResultService.final_upload(filters.year, filters.month):
                    production = {}
                    for target in self.session.query(Target).filter(
                        Target.year == filters.year, Target.month == filters.month
                    ).all():
                        effective = ProductionResultService.effective_product(
                            filters.year, filters.month, target.representative_id, target.product_id
                        )
                        production[target.product_id] = production.get(target.product_id, Decimal("0")) + Decimal(str(effective.get("actual_tl") or 0))
                rows = []
                for item in official:
                    actual = production.get(item["product_id"], Decimal("0")) if production is not None else Decimal(str(item["actual_tl"] or 0))
                    rows.append(SimpleNamespace(
                        product_id=item["product_id"],
                        product_name=item["product_name"],
                        realization_tl=actual,
                        target_tl=Decimal(str(item["target_tl"] or 0)),
                    ))
                return sorted(rows, key=lambda row: row.realization_tl, reverse=True)
        q = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)
        if filters.representative_id is not None:
            q = q.filter(Target.representative_id == filters.representative_id)
        totals = {}
        products = {p.id: p for p in Product.query.all()}
        for target in q.all():
            bucket = totals.setdefault(target.product_id, [Decimal("0"), Decimal("0")])
            bucket[1] += Decimal(str(target.tl_target or 0))
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(effective.get("actual_tl") or 0))
        rows = [SimpleNamespace(product_id=pid, product_name=products[pid].product_name if pid in products else str(pid), realization_tl=vals[0], target_tl=vals[1]) for pid, vals in totals.items()]
        return sorted(rows, key=lambda row: row.realization_tl, reverse=True)
'''
    text = replace_function(text, "load_product_performance", "load_city_performance", product)

    region = '''    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        target_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, TARGET_TYPE)
        if target_upload:
            target_rows = self.session.query(IMSRawData).filter(
                IMSRawData.upload_id == target_upload,
                IMSRawData.sheet_type == TARGET_TYPE,
                IMSRawData.territory != "NATIONAL",
            ).all()
            if target_rows:
                production_exists = ProductionResultService.final_upload(filters.year, filters.month) is not None
                actual_by_key = {}
                if production_exists:
                    for target in self.session.query(Target).filter(
                        Target.year == filters.year, Target.month == filters.month
                    ).all():
                        rep = self.session.get(Representative, target.representative_id)
                        if rep is None or not rep.region:
                            continue
                        region_key = str(rep.region).strip().split()[0]
                        effective = ProductionResultService.effective_product(
                            filters.year, filters.month, target.representative_id, target.product_id
                        )
                        bucket = actual_by_key.setdefault((region_key, target.product_id), [Decimal("0"), Decimal("0")])
                        bucket[0] += Decimal(str(effective.get("actual_unit") or 0))
                        bucket[1] += Decimal(str(effective.get("actual_tl") or 0))
                else:
                    actual_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, ACTUAL_TYPE)
                    if actual_upload:
                        for row in self.session.query(IMSRawData).filter(
                            IMSRawData.upload_id == actual_upload,
                            IMSRawData.sheet_type == ACTUAL_TYPE,
                            IMSRawData.territory != "NATIONAL",
                        ).all():
                            actual_by_key[(str(row.territory), row.product_id)] = [Decimal(str(row.unit or 0)), Decimal(str(row.tl or 0))]
                reps_by_region = {}
                city_by_region = {}
                for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                    region_key = str(rep.region).strip().split()[0]
                    reps_by_region.setdefault(region_key, set()).add(rep.id)
                    if rep.city and region_key not in city_by_region:
                        city_by_region[region_key] = rep.city
                buckets = {}
                for target in target_rows:
                    region_key = str(target.territory)
                    bucket = buckets.setdefault(region_key, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                    actual_unit, actual_tl = actual_by_key.get((region_key, target.product_id), [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(target.unit or 0))
                    bucket[1] += actual_unit
                    bucket[2] += Decimal(str(target.tl or 0))
                    bucket[3] += actual_tl
                return [SimpleNamespace(
                    region=region_key,
                    city=city_by_region.get(region_key),
                    unit_target=vals[0], unit_actual=vals[1],
                    tl_target=vals[2], tl_actual=vals[3],
                    representative_count=len(reps_by_region.get(region_key, set())),
                ) for region_key, vals in sorted(buckets.items())]
        targets = self.session.query(Target, Representative).join(
            Representative, Representative.id == Target.representative_id
        ).filter(
            Target.year == filters.year,
            Target.month == filters.month,
            Representative.region.isnot(None),
        ).all()
        buckets = {}
        for target, rep in targets:
            key = (rep.region, rep.city)
            bucket = buckets.setdefault(key, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), set()])
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(target.unit_target or 0)); bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
            bucket[2] += Decimal(str(target.tl_target or 0)); bucket[3] += Decimal(str(effective.get("actual_tl") or 0)); bucket[4].add(rep.id)
        return [SimpleNamespace(region=k[0], city=k[1], unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(v[4])) for k, v in sorted(buckets.items())]
'''
    text = replace_function(text, "load_region_performance", "load_competition_overview", region)
    path.write_text(text)


if __name__ == "__main__":
    patch_importer()
    patch_dashboard()
