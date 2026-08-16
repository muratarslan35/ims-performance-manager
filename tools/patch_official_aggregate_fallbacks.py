from pathlib import Path
import re


def replace_method(text, name, next_name, body):
    pattern = rf"    def {name}\(.*?(?=    def {next_name}\()"
    text, count = re.subn(pattern, body.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"replace {name}: {count}")
    return text


path = Path("app/query/dashboard_query.py")
text = path.read_text()

national = '''    def load_national_dashboard_metrics(self, filters: Optional[DashboardFilterParams] = None) -> dict:
        """Use exact official aggregates when present and preserve legacy periods otherwise."""
        if not filters or filters.year is None or filters.month is None:
            return {}
        official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
        actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
        if official and actual_rows:
            if ProductionResultService.final_upload(filters.year, filters.month):
                production = {}
                for target in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                    effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
                    bucket = production.setdefault(target.product_id, [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(effective.get("actual_tl") or 0))
                    bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
                for item in official:
                    values = production.get(item["product_id"], [Decimal("0"), Decimal("0")])
                    item["actual_tl"] = float(values[0]); item["actual_unit"] = float(values[1])
            products = []
            for item in official:
                row = {
                    "product_id": item["product_id"], "product_name": item["product_name"],
                    "target_tl": round(float(item["target_tl"] or 0), 2),
                    "actual_tl": round(float(item["actual_tl"] or 0), 2),
                    "unit_target": round(float(item["target_unit"] or 0), 2),
                    "unit_actual": round(float(item["actual_unit"] or 0), 2),
                }
                row["realization_percent"] = round(row["actual_tl"] * 100 / row["target_tl"], 1) if row["target_tl"] else 0.0
                row["unit_realization_percent"] = round(row["unit_actual"] * 100 / row["unit_target"], 1) if row["unit_target"] else 0.0
                products.append(row)
            target = sum(item["target_tl"] for item in products); actual = sum(item["actual_tl"] for item in products)
            unit_target = sum(item["unit_target"] for item in products); unit_actual = sum(item["unit_actual"] for item in products)
            return {
                "source": "Resmi NATIONAL hedef / kabul edilen gerçekleşme kaynağı",
                "target_tl": round(target, 2), "actual_tl": round(actual, 2),
                "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
                "unit_target": round(unit_target, 2), "unit_actual": round(unit_actual, 2),
                "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
                "products": products,
            }

        upload_id = self.session.query(IMSUpload.id).filter(
            IMSUpload.year == filters.year, IMSUpload.month == filters.month,
            IMSUpload.status == "COMPLETED"
        ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id:
            return {}
        balance_rows = self.session.query(Product.id, Product.product_name, IMSRawData.unit, IMSRawData.tl).join(
            Product, Product.id == IMSRawData.product_id
        ).filter(IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_balance_national").all()
        if not balance_rows:
            return {}
        weekly_by_product = {
            row[0]: (float(row[1] or 0), float(row[2] or 0))
            for row in self.session.query(IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl).filter(
                IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_weekly_units"
            ).all()
        }
        target_unit_by_product = dict(self.session.query(
            Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
        ).filter(Target.year == filters.year, Target.month == filters.month).group_by(Target.product_id).all())
        products = []
        for row in balance_rows:
            weekly_unit, weekly_tl = weekly_by_product.get(row[0], (0.0, float(row[3] or 0)))
            products.append({
                "product_id": row[0], "product_name": row[1],
                "target_tl": round(float(row[2] or 0), 2), "actual_tl": round(float(weekly_tl or 0), 2),
                "unit_target": round(float(target_unit_by_product.get(row[0], 0) or 0), 2), "unit_actual": round(float(weekly_unit or 0), 2),
            })
        target = sum(item["target_tl"] for item in products); actual = sum(item["actual_tl"] for item in products)
        for item in products:
            item["realization_percent"] = round(item["actual_tl"] * 100 / item["target_tl"], 1) if item["target_tl"] else 0.0
            item["unit_realization_percent"] = round(item["unit_actual"] * 100 / item["unit_target"], 1) if item["unit_target"] else 0.0
        unit_target = sum(item["unit_target"] for item in products); unit_actual = sum(item["unit_actual"] for item in products)
        return {
            "source": "BAKİYE / TTS HAFTALIK ÇIKIŞLARI · NATIONAL",
            "target_tl": round(target, 2), "actual_tl": round(actual, 2),
            "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
            "unit_target": round(unit_target, 2), "unit_actual": round(unit_actual, 2),
            "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
            "products": products,
        }
'''
text = replace_method(text, "load_national_dashboard_metrics", "load_product_performance", national)

region = '''    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        target_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, TARGET_TYPE)
        if target_upload:
            target_rows = self.session.query(IMSRawData).filter(
                IMSRawData.upload_id == target_upload, IMSRawData.sheet_type == TARGET_TYPE, IMSRawData.territory != "NATIONAL"
            ).all()
            if target_rows:
                production_exists = ProductionResultService.final_upload(filters.year, filters.month) is not None
                actual_by_key = {}
                if production_exists:
                    for target in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                        rep = self.session.get(Representative, target.representative_id)
                        if rep is None or not rep.region: continue
                        rk = str(rep.region).strip().split()[0]
                        effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
                        bucket = actual_by_key.setdefault((rk, target.product_id), [Decimal("0"), Decimal("0")])
                        bucket[0] += Decimal(str(effective.get("actual_unit") or 0)); bucket[1] += Decimal(str(effective.get("actual_tl") or 0))
                else:
                    actual_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, ACTUAL_TYPE)
                    if actual_upload:
                        for row in self.session.query(IMSRawData).filter(
                            IMSRawData.upload_id == actual_upload, IMSRawData.sheet_type == ACTUAL_TYPE, IMSRawData.territory != "NATIONAL"
                        ).all():
                            actual_by_key[(str(row.territory), row.product_id)] = [Decimal(str(row.unit or 0)), Decimal(str(row.tl or 0))]
                reps_by_region = {}; city_by_region = {}
                for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                    rk = str(rep.region).strip().split()[0]; reps_by_region.setdefault(rk, set()).add(rep.id)
                    if rep.city and rk not in city_by_region: city_by_region[rk] = rep.city
                buckets = {}
                for target in target_rows:
                    rk = str(target.territory); bucket = buckets.setdefault(rk, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                    au, atl = actual_by_key.get((rk, target.product_id), [Decimal("0"), Decimal("0")])
                    bucket[0] += Decimal(str(target.unit or 0)); bucket[1] += au
                    bucket[2] += Decimal(str(target.tl or 0)); bucket[3] += atl
                return [SimpleNamespace(region=rk, city=city_by_region.get(rk), unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(reps_by_region.get(rk, set()))) for rk, v in sorted(buckets.items())]

        if ProductionResultService.final_upload(filters.year, filters.month) is None:
            upload_id = self.session.query(IMSUpload.id).filter(
                IMSUpload.year == filters.year, IMSUpload.month == filters.month, IMSUpload.status == "COMPLETED"
            ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
            if upload_id:
                balance_rows = self.session.query(IMSRawData.territory, Product.id, IMSRawData.unit).join(
                    Product, Product.id == IMSRawData.product_id
                ).filter(IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_balance_region").all()
                if balance_rows:
                    weekly_rows = self.session.query(IMSRawData.territory, IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl).filter(
                        IMSRawData.upload_id == upload_id, IMSRawData.sheet_type == "dashboard_weekly_region"
                    ).all()
                    def region_key(value):
                        value = str(value or "").strip(); first = value.split()[0] if value else ""
                        return first if first.isdigit() else value
                    weekly = {(region_key(r[0]), r[1]): (Decimal(str(r[2] or 0)), Decimal(str(r[3] or 0))) for r in weekly_rows}
                    unit_targets = {(region_key(r[0]), r[1]): Decimal(str(r[2] or 0)) for r in self.session.query(
                        Representative.region, Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
                    ).join(Target, Target.representative_id == Representative.id).filter(
                        Target.year == filters.year, Target.month == filters.month, Representative.region.isnot(None)
                    ).group_by(Representative.region, Target.product_id).all()}
                    representative_ids = {}; city_by_region = {}
                    for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                        rk = region_key(rep.region); representative_ids.setdefault(rk, set()).add(rep.id)
                        if rep.city and rk not in city_by_region: city_by_region[rk] = rep.city
                    buckets = {}
                    for territory, product_id, target_tl in balance_rows:
                        rk = region_key(territory); bucket = buckets.setdefault(rk, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                        au, atl = weekly.get((rk, product_id), (Decimal("0"), Decimal("0")))
                        bucket[0] += unit_targets.get((rk, product_id), Decimal("0")); bucket[1] += au
                        bucket[2] += Decimal(str(target_tl or 0)); bucket[3] += atl
                    return [SimpleNamespace(region=rk, city=city_by_region.get(rk), unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(representative_ids.get(rk, set()))) for rk, v in sorted(buckets.items())]

        targets = self.session.query(Target, Representative).join(Representative, Representative.id == Target.representative_id).filter(
            Target.year == filters.year, Target.month == filters.month, Representative.region.isnot(None)
        ).all()
        buckets = {}
        for target, rep in targets:
            key = (rep.region, rep.city); bucket = buckets.setdefault(key, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), set()])
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(target.unit_target or 0)); bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
            bucket[2] += Decimal(str(target.tl_target or 0)); bucket[3] += Decimal(str(effective.get("actual_tl") or 0)); bucket[4].add(rep.id)
        return [SimpleNamespace(region=k[0], city=k[1], unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(v[4])) for k, v in sorted(buckets.items())]
'''
text = replace_method(text, "load_region_performance", "load_competition_overview", region)
path.write_text(text)

# Test fixture must satisfy current non-null upload_id schema.
test_path = Path("tests/test_official_aggregate_sources.py")
test = test_path.read_text()
test = test.replace('self.summary = IMSSummary(\n            year=2038,', 'self.summary = IMSSummary(\n            upload_id=self.upload.id,\n            year=2038,')
test_path.write_text(test)
