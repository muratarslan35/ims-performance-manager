from pathlib import Path


def insert_after(source, anchor, block, guard):
    if guard in source:
        return source
    if anchor not in source:
        raise RuntimeError(f"anchor missing: {anchor[:60]}")
    return source.replace(anchor, anchor + block, 1)


def main():
    path = Path("app/query/dashboard_query.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "from app.services.official_aggregate_service import OfficialAggregateService, ACTUAL_TYPE\n",
        "from app.services.official_aggregate_service import OfficialAggregateService, ACTUAL_TYPE, TARGET_TYPE\n",
        1,
    )

    period_anchor = '''        if not filters or filters.year is None or filters.month is None:
            return SimpleNamespace(realization_tl=Decimal("0"), target_tl=Decimal("0"))
'''
    period_block = '''        if filters.representative_id is None:
            official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
            actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
            if official and actual_rows:
                if ProductionResultService.final_upload(filters.year, filters.month):
                    actuals = {}
                    for target_row in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                        effective = ProductionResultService.effective_product(filters.year, filters.month, target_row.representative_id, target_row.product_id)
                        actuals[target_row.product_id] = actuals.get(target_row.product_id, Decimal("0")) + Decimal(str(effective.get("actual_tl") or 0))
                    realization = sum((actuals.get(item["product_id"], Decimal("0")) for item in official), Decimal("0"))
                else:
                    realization = sum((Decimal(str(item["actual_tl"] or 0)) for item in official), Decimal("0"))
                target = sum((Decimal(str(item["target_tl"] or 0)) for item in official), Decimal("0"))
                return SimpleNamespace(realization_tl=realization, target_tl=target)
'''
    source = insert_after(source, period_anchor, period_block, "if filters.representative_id is None:\n            official = OfficialAggregateService.product_totals(filters.year, filters.month, \"NATIONAL\")")

    product_anchor = '''        if not filters or filters.year is None or filters.month is None:
            return []
        q = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)
'''
    product_block = '''        if filters.representative_id is None:
            official = OfficialAggregateService.product_totals(filters.year, filters.month, "NATIONAL")
            actual_rows = OfficialAggregateService.rows(filters.year, filters.month, "NATIONAL", ACTUAL_TYPE)
            if official and actual_rows:
                production_actuals = None
                if ProductionResultService.final_upload(filters.year, filters.month):
                    production_actuals = {}
                    for target_row in self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month).all():
                        effective = ProductionResultService.effective_product(filters.year, filters.month, target_row.representative_id, target_row.product_id)
                        production_actuals[target_row.product_id] = production_actuals.get(target_row.product_id, Decimal("0")) + Decimal(str(effective.get("actual_tl") or 0))
                rows = []
                for item in official:
                    actual = production_actuals.get(item["product_id"], Decimal("0")) if production_actuals is not None else Decimal(str(item["actual_tl"] or 0))
                    rows.append(SimpleNamespace(
                        product_id=item["product_id"], product_name=item["product_name"],
                        realization_tl=actual, target_tl=Decimal(str(item["target_tl"] or 0)),
                    ))
                return sorted(rows, key=lambda row: row.realization_tl, reverse=True)
'''
    # This anchor occurs in load_product_performance only after the national method.
    idx = source.find("    def load_product_performance")
    if idx == -1:
        raise RuntimeError("load_product_performance missing")
    tail = source[idx:]
    if "production_actuals = None" not in tail:
        if product_anchor not in tail:
            raise RuntimeError("product performance anchor missing")
        tail = tail.replace(product_anchor, product_anchor.replace("        q = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)\n", "") + product_block + "        q = self.session.query(Target).filter(Target.year == filters.year, Target.month == filters.month)\n", 1)
        source = source[:idx] + tail

    region_start = source.index("    def load_region_performance")
    region_end = source.index("    def load_competition_overview", region_start)
    old_region = source[region_start:region_end]
    new_region = '''    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []
        if not ProductionResultService.final_upload(filters.year, filters.month):
            target_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, TARGET_TYPE)
            actual_upload = OfficialAggregateService.latest_upload_id(filters.year, filters.month, ACTUAL_TYPE)
            if target_upload and actual_upload:
                target_rows = self.session.query(IMSRawData).filter(
                    IMSRawData.upload_id == target_upload,
                    IMSRawData.sheet_type == TARGET_TYPE,
                    IMSRawData.territory != "NATIONAL",
                ).all()
                actual_rows = self.session.query(IMSRawData).filter(
                    IMSRawData.upload_id == actual_upload,
                    IMSRawData.sheet_type == ACTUAL_TYPE,
                    IMSRawData.territory != "NATIONAL",
                ).all()
                actual_by_key = {(row.territory, row.product_id): row for row in actual_rows}
                buckets = {}
                for target in target_rows:
                    actual = actual_by_key.get((target.territory, target.product_id))
                    bucket = buckets.setdefault(target.territory, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), target.representative or target.territory])
                    bucket[0] += Decimal(str(target.unit or 0))
                    bucket[1] += Decimal(str(actual.unit or 0)) if actual else Decimal("0")
                    bucket[2] += Decimal(str(target.tl or 0))
                    bucket[3] += Decimal(str(actual.tl or 0)) if actual else Decimal("0")
                return [
                    SimpleNamespace(
                        region=region,
                        city=(str(values[4]).split(" ", 1)[1] if " " in str(values[4]) else str(values[4])),
                        unit_target=values[0], unit_actual=values[1], tl_target=values[2], tl_actual=values[3],
                        representative_count=len({rep.id for rep in Representative.query.filter(Representative.region == region).all()}),
                    )
                    for region, values in sorted(buckets.items())
                ]
        targets = self.session.query(Target, Representative).join(Representative, Representative.id == Target.representative_id).filter(Target.year == filters.year, Target.month == filters.month, Representative.region.isnot(None)).all()
        buckets = {}
        for target, rep in targets:
            key = (rep.region, rep.city)
            bucket = buckets.setdefault(key, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), set()])
            effective = ProductionResultService.effective_product(filters.year, filters.month, target.representative_id, target.product_id)
            bucket[0] += Decimal(str(target.unit_target or 0)); bucket[1] += Decimal(str(effective.get("actual_unit") or 0))
            bucket[2] += Decimal(str(target.tl_target or 0)); bucket[3] += Decimal(str(effective.get("actual_tl") or 0)); bucket[4].add(rep.id)
        return [SimpleNamespace(region=k[0], city=k[1], unit_target=v[0], unit_actual=v[1], tl_target=v[2], tl_actual=v[3], representative_count=len(v[4])) for k, v in sorted(buckets.items())]

'''
    source = source[:region_start] + new_region + source[region_end:]
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
