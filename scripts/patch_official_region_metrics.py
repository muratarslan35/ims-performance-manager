from pathlib import Path

p = Path('app/services/ims_import_service.py')
text = p.read_text(encoding='utf-8')
start = text.index('    def persist_national_dashboard_metrics(')
end = text.index('    def clear_week(', start)
method = '''    def persist_national_dashboard_metrics(self, year, month):
        """Persist source-authoritative National and region subtotal KPI rows.

        Person rows remain untouched for representative reporting. Company and
        region KPI totals use the workbook's own subtotal rows so a workbook
        whose person allocations do not reconcile cannot inflate executive or
        region totals.
        """
        if not self.upload or not self.workbook:
            return

        def upsert(sheet_name, sheet_type, product_id, unit, tl, metadata, representative="NATIONAL", territory=None):
            record = IMSRawData.query.filter_by(
                upload_id=self.upload.id,
                sheet_type=sheet_type,
                product_id=product_id,
                representative=representative,
                territory=territory,
            ).first()
            values = dict(
                year=year, month=month, quarter=self.quarter_for(month),
                week_number=self.upload.week_number, sheet_name=sheet_name,
                sheet_type=sheet_type, source_row=0, product_id=product_id,
                representative=representative, territory=territory,
                unit=float(unit or 0), tl=float(tl or 0),
                raw_json=json.dumps(metadata, ensure_ascii=False),
            )
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
            else:
                db.session.add(IMSRawData(upload_id=self.upload.id, **values))

        def is_region_subtotal(row):
            if len(row) < 2:
                return False
            territory = self.clean_text(row.iloc[0])
            representative = self.clean_text(row.iloc[1])
            if not territory or not representative:
                return False
            return (
                AliasService.normalize(territory) == AliasService.normalize(representative)
                and bool(re.match(r"^\\d{3}\\b", AliasService.normalize(territory)))
            )

        balance_name = next((name for name in self.workbook if "BAKIYE" in AliasService.normalize(name)), None)
        if balance_name:
            frame = self.workbook[balance_name]
            header_row = next((
                i for i in range(min(12, len(frame)))
                if "HEDEF" in " ".join(AliasService.normalize(v) for v in frame.iloc[i])
                and "CIKIS" in " ".join(AliasService.normalize(v) for v in frame.iloc[i])
            ), None)
            if header_row is not None:
                sections, current = {}, ""
                for column in range(frame.shape[1]):
                    label = AliasService.normalize(self.clean_text(frame.iloc[header_row, column]))
                    if any(token in label for token in ("HEDEF", "CIKIS", "BAKIYE")):
                        current = label
                    sections[column] = current

                def balance_values(row):
                    metric_values = {}
                    for column, section in sections.items():
                        product_match = self.resolve_product_match(self.clean_text(frame.iloc[header_row, column]))
                        if not product_match["matched"]:
                            continue
                        product_id = product_match["object"].id
                        values = metric_values.setdefault(product_id, {"target_tl": 0.0, "actual_tl": 0.0})
                        if "HEDEF" in section:
                            values["target_tl"] = self.safe_float(row.iloc[column])
                        elif "CIKIS" in section:
                            values["actual_tl"] = self.safe_float(row.iloc[column])
                    return metric_values

                for row_index in range(header_row + 1, len(frame)):
                    row = frame.iloc[row_index]
                    territory = self.clean_text(row.iloc[0]) if frame.shape[1] > 0 else ""
                    representative = self.clean_text(row.iloc[1]) if frame.shape[1] > 1 else ""
                    normalized_rep = AliasService.normalize(representative)
                    if normalized_rep == "NATIONAL":
                        for product_id, values in balance_values(row).items():
                            upsert(balance_name, "dashboard_balance_national", product_id,
                                   values["target_tl"], values["actual_tl"], values)
                    elif is_region_subtotal(row):
                        for product_id, values in balance_values(row).items():
                            upsert(balance_name, "dashboard_balance_region", product_id,
                                   values["target_tl"], values["actual_tl"], values,
                                   representative=representative, territory=territory)

        weekly_name = next((name for name in self.workbook if "HAFTALIK" in AliasService.normalize(name) and "CIKIS" in AliasService.normalize(name)), None)
        if weekly_name:
            frame = self.workbook[weekly_name]
            if len(frame) >= 3:
                sections, current = {}, ""
                for column in range(frame.shape[1]):
                    label = AliasService.normalize(self.clean_text(frame.iloc[0, column]))
                    if label:
                        current = label
                    sections[column] = current
                selected_tl = next((s for s in sections.values() if "CIKIS" in s and "TL" in s), "")
                selected_unit = next((s for s in sections.values() if "CIKIS" in s and "KUTU" in s), "")

                def weekly_values(row):
                    values = {}
                    for column, section in sections.items():
                        if section not in {selected_tl, selected_unit}:
                            continue
                        product_match = self.resolve_product_match(self.clean_text(frame.iloc[1, column]))
                        if not product_match["matched"]:
                            continue
                        bucket = values.setdefault(product_match["object"].id, {"actual_tl": 0.0, "actual_unit": 0.0})
                        if section == selected_tl:
                            bucket["actual_tl"] = self.safe_float(row.iloc[column])
                        elif section == selected_unit:
                            bucket["actual_unit"] = self.safe_float(row.iloc[column])
                    return values

                for row_index in range(2, len(frame)):
                    row = frame.iloc[row_index]
                    territory = self.clean_text(row.iloc[0]) if frame.shape[1] > 0 else ""
                    representative = self.clean_text(row.iloc[1]) if frame.shape[1] > 1 else ""
                    normalized_rep = AliasService.normalize(representative)
                    if normalized_rep == "NATIONAL":
                        for product_id, values in weekly_values(row).items():
                            upsert(weekly_name, "dashboard_weekly_units", product_id,
                                   values["actual_unit"], values["actual_tl"], values)
                    elif is_region_subtotal(row):
                        for product_id, values in weekly_values(row).items():
                            upsert(weekly_name, "dashboard_weekly_region", product_id,
                                   values["actual_unit"], values["actual_tl"], values,
                                   representative=representative, territory=territory)
        db.session.flush()

'''
p.write_text(text[:start] + method + text[end:], encoding='utf-8')

q = Path('app/query/dashboard_query.py')
text = q.read_text(encoding='utf-8')
start = text.index('    def load_national_dashboard_metrics(')
end = text.index('    def load_product_performance(', start)
national = '''    def load_national_dashboard_metrics(self, filters: Optional[DashboardFilterParams] = None) -> dict:
        """Return workbook-reconciled company totals for the selected IMS period."""
        if not filters or filters.year is None or filters.month is None:
            return {}
        upload_id = self.session.query(IMSUpload.id).filter(
            IMSUpload.year == filters.year, IMSUpload.month == filters.month,
            IMSUpload.status == "COMPLETED"
        ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
        if not upload_id:
            return {}
        balance_rows = self.session.query(
            Product.id, Product.product_name, IMSRawData.unit, IMSRawData.tl
        ).join(Product, Product.id == IMSRawData.product_id).filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.sheet_type == "dashboard_balance_national"
        ).all()
        if not balance_rows:
            return {}
        weekly_by_product = {
            row[0]: (float(row[1] or 0), float(row[2] or 0))
            for row in self.session.query(
                IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl
            ).filter(
                IMSRawData.upload_id == upload_id,
                IMSRawData.sheet_type == "dashboard_weekly_units",
            ).all()
        }
        target_unit_by_product = dict(self.session.query(
            Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
        ).filter(
            Target.year == filters.year,
            Target.month == filters.month,
        ).group_by(Target.product_id).all())
        products = []
        for row in balance_rows:
            weekly_unit, weekly_tl = weekly_by_product.get(row[0], (0.0, float(row[3] or 0)))
            products.append({
                "product_id": row[0], "product_name": row[1],
                "target_tl": round(float(row[2] or 0), 2),
                "actual_tl": round(float(weekly_tl or 0), 2),
                "unit_target": round(float(target_unit_by_product.get(row[0], 0) or 0), 2),
                "unit_actual": round(float(weekly_unit or 0), 2),
            })
        target = sum(item["target_tl"] for item in products)
        actual = sum(item["actual_tl"] for item in products)
        for item in products:
            item["realization_percent"] = round(item["actual_tl"] * 100 / item["target_tl"], 1) if item["target_tl"] else 0.0
            item["unit_realization_percent"] = round(item["unit_actual"] * 100 / item["unit_target"], 1) if item["unit_target"] else 0.0
        unit_target = sum(item["unit_target"] for item in products)
        unit_actual = sum(item["unit_actual"] for item in products)
        return {
            "source": "BAKİYE / TTS HAFTALIK ÇIKIŞLARI · NATIONAL",
            "target_tl": round(target, 2), "actual_tl": round(actual, 2),
            "realization_percent": round(actual * 100 / target, 2) if target else 0.0,
            "unit_target": round(unit_target, 2),
            "unit_actual": round(unit_actual, 2),
            "unit_realization_percent": round(unit_actual * 100 / unit_target, 2) if unit_target else 0.0,
            "products": products,
        }

'''
text = text[:start] + national + text[end:]
start = text.index('    def load_region_performance(')
end = text.index('    def load_competition_overview(', start)
region = '''    def load_region_performance(self, filters: Optional[DashboardFilterParams] = None):
        if not filters or filters.year is None or filters.month is None:
            return []

        if ProductionResultService.final_upload(filters.year, filters.month) is None:
            upload_id = self.session.query(IMSUpload.id).filter(
                IMSUpload.year == filters.year,
                IMSUpload.month == filters.month,
                IMSUpload.status == "COMPLETED",
            ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
            if upload_id:
                balance_rows = self.session.query(
                    IMSRawData.territory, Product.id, IMSRawData.unit
                ).join(Product, Product.id == IMSRawData.product_id).filter(
                    IMSRawData.upload_id == upload_id,
                    IMSRawData.sheet_type == "dashboard_balance_region",
                ).all()
                if balance_rows:
                    weekly_rows = self.session.query(
                        IMSRawData.territory, IMSRawData.product_id, IMSRawData.unit, IMSRawData.tl
                    ).filter(
                        IMSRawData.upload_id == upload_id,
                        IMSRawData.sheet_type == "dashboard_weekly_region",
                    ).all()

                    def region_key(value):
                        value = str(value or "").strip()
                        first = value.split()[0] if value else ""
                        return first if first.isdigit() else value

                    weekly = {
                        (region_key(row[0]), row[1]): (Decimal(str(row[2] or 0)), Decimal(str(row[3] or 0)))
                        for row in weekly_rows
                    }
                    unit_targets = {
                        (region_key(row[0]), row[1]): Decimal(str(row[2] or 0))
                        for row in self.session.query(
                            Representative.region, Target.product_id, func.coalesce(func.sum(Target.unit_target), 0.0)
                        ).join(Target, Target.representative_id == Representative.id).filter(
                            Target.year == filters.year,
                            Target.month == filters.month,
                            Representative.region.isnot(None),
                        ).group_by(Representative.region, Target.product_id).all()
                    }
                    representative_ids = {}
                    city_by_region = {}
                    for rep in self.session.query(Representative).filter(Representative.region.isnot(None)).all():
                        rk = region_key(rep.region)
                        representative_ids.setdefault(rk, set()).add(rep.id)
                        if rep.city and rk not in city_by_region:
                            city_by_region[rk] = rep.city
                    buckets = {}
                    for territory, product_id, target_tl in balance_rows:
                        rk = region_key(territory)
                        bucket = buckets.setdefault(rk, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
                        actual_unit, actual_tl = weekly.get((rk, product_id), (Decimal("0"), Decimal("0")))
                        bucket[0] += unit_targets.get((rk, product_id), Decimal("0"))
                        bucket[1] += actual_unit
                        bucket[2] += Decimal(str(target_tl or 0))
                        bucket[3] += actual_tl
                    return [
                        SimpleNamespace(
                            region=rk,
                            city=city_by_region.get(rk),
                            unit_target=vals[0], unit_actual=vals[1],
                            tl_target=vals[2], tl_actual=vals[3],
                            representative_count=len(representative_ids.get(rk, set())),
                        )
                        for rk, vals in sorted(buckets.items())
                    ]

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
q.write_text(text[:start] + region + text[end:], encoding='utf-8')

r = Path('app/services/region_performance_service.py')
text = r.read_text(encoding='utf-8')
text = text.replace('from sqlalchemy import and_, func, or_', 'from sqlalchemy import and_, func, or_, desc')
text = text.replace('from app.models import Product, Representative, Target', 'from app.models import IMSRawData, IMSUpload, Product, Representative, Target')
insert = text.index('    def aggregate(self, months):')
helper = '''    def _official_ims_region_month(self, year, month):
        """Return explicit workbook region subtotal metrics for an IMS month."""
        if ProductionResultService.final_upload(year, month) is not None:
            return {}
        upload_id = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == year,
            IMSUpload.month == month,
            IMSUpload.status == "COMPLETED",
        ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()
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
            product_id: [Decimal(str(target_tl or 0)), weekly.get(product_id, (Decimal("0"), False))[0], weekly.get(product_id, (Decimal("0"), False))[1]]
            for product_id, target_tl in balance
        }

'''
text = text[:insert] + helper + text[insert:]
start = text.index('    def aggregate(self, months):')
end = text.index('    def report(self):', start)
aggregate = '''    def aggregate(self, months):
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
            rep_bucket[0] += target; rep_bucket[1] += actual; rep_bucket[2] = rep_bucket[2] and row_complete
            bucket = person_month_product[(year, month, product_id)]
            bucket[0] += target; bucket[1] += actual; bucket[2] = bucket[2] and row_complete

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
                    bucket[0] += target; bucket[1] += actual; bucket[2] = bucket[2] and row_complete

        products = {item.id: item for item in Product.query.filter(Product.id.in_(all_product_ids)).all()} if all_product_ids else {}
        total_target = sum((vals[0] for vals in month_totals.values()), Decimal("0"))
        total_actual = sum((vals[1] for vals in month_totals.values()), Decimal("0"))
        complete = all(vals[2] for vals in month_totals.values()) if month_totals else False

        def result_row(vals):
            target, actual, row_complete = vals
            return {"target_tl": target, "actual_tl": actual if row_complete else None, "realization_percent": self.percent(actual, target) if row_complete else None, "gap_tl": (target - actual) if row_complete else None, "complete": row_complete}

        product_rows = [{"product_id": pid, "product_name": products[pid].product_name if pid in products else f"Ürün {pid}", **result_row(vals)} for pid, vals in product_totals.items()]
        product_rows.sort(key=lambda row: (-(row["actual_tl"] or Decimal("0")), row["product_name"]))
        representative_rows = [{"representative_id": rid, "representative_name": reps[rid].rep_name, "city": reps[rid].city or "-", "active": bool(reps[rid].active), "is_vacant": "boş" in (reps[rid].rep_name or "").casefold() or (reps[rid].rep_name or "").strip().upper() == "BOS", **result_row(vals)} for rid, vals in rep_totals.items()]
        representative_rows.sort(key=lambda row: (-(row["realization_percent"] or Decimal("0")), -(row["actual_tl"] or Decimal("0"))))
        monthly_rows = [{"year": year, "month": month, "label": f"{month:02d}/{year}", "source": source_by_month.get((year, month)), **result_row(month_totals[(year, month)])} for year, month in months]
        return {"target_tl": total_target, "actual_tl": total_actual if complete else None, "realization_percent": self.percent(total_actual, total_target) if complete else None, "gap_tl": (total_target-total_actual) if complete else None, "complete": complete, "products": product_rows, "representatives": representative_rows, "months": monthly_rows, "source_by_month": source_by_month}

'''
r.write_text(text[:start] + aggregate + text[end:], encoding='utf-8')

t = Path('tests/test_auth_routes.py')
src = t.read_text(encoding='utf-8')
marker = 'def test_target_analysis_groups_products_under_one_representative(app):'
test = '''def test_region_totals_prefer_official_workbook_subtotal_but_keep_person_allocations(app):
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, IMSSummary, Product, Representative, Target
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams
    from app.services.region_performance_service import RegionPerformanceService
    import json

    with app.app_context():
        product = Product(product_code="OFFICIAL-REG", product_name="Resmi Bölge Ürünü", is_active=True)
        rep_a = Representative(rep_code="OFF-A", rep_name="Resmi A", region="901", city="Diyarbakır", active=True)
        rep_b = Representative(rep_code="OFF-B", rep_name="Resmi B", region="901", city="Diyarbakır", active=False)
        db.session.add_all([product, rep_a, rep_b]); db.session.flush()
        upload = IMSUpload(file_name="official-region.xlsx", year=2035, month=1, quarter="Q1", status="COMPLETED")
        db.session.add(upload); db.session.flush()
        for rep, target, actual in ((rep_a, 4000, 400), (rep_b, 3000, 300)):
            db.session.add(Target(year=2035, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, tl_target=target, unit_target=10))
            db.session.add(IMSSummary(upload_id=upload.id, year=2035, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, tl=actual, unit=2))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2035, month=1, quarter="Q1", sheet_name="BAKİYE", sheet_type="dashboard_balance_region", source_row=0, product_id=product.id, representative="901 DIYARBAKIR", territory="901 DIYARBAKIR", unit=6000, tl=650, raw_json=json.dumps({"target_tl":6000})),
            IMSRawData(upload_id=upload.id, year=2035, month=1, quarter="Q1", sheet_name="TTS HAFTALIK ÇIKIŞLARI", sheet_type="dashboard_weekly_region", source_row=0, product_id=product.id, representative="901 DIYARBAKIR", territory="901 DIYARBAKIR", unit=9, tl=650, raw_json=json.dumps({"actual_tl":650,"actual_unit":9})),
        ])
        db.session.commit()

        report = RegionPerformanceService("901", 2035, 1).report()
        monthly = report["periods"]["monthly"]
        assert monthly["target_tl"] == 6000
        assert monthly["actual_tl"] == 650
        assert sum(row["target_tl"] for row in monthly["representatives"]) == 7000
        assert monthly["months"][0]["source"] == "OFFICIAL_REGION_SUBTOTAL"

        rows = DashboardQuery().load_region_performance(DashboardFilterParams(year=2035, month=1))
        row = next(item for item in rows if str(item.region) == "901")
        assert row.tl_target == 6000
        assert row.tl_actual == 650
        assert row.unit_actual == 9
        assert row.unit_target == 20


'''
if marker not in src:
    raise SystemExit('test marker not found')
t.write_text(src.replace(marker, test + marker, 1), encoding='utf-8')
