#!/usr/bin/env python3
"""Read-only Q1 region/product box-source and screen reconciliation audit."""

import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models import (
    IMSSummary,
    Product,
    ProductionRegionProductResult,
    ProductionResultUpload,
    Representative,
    Target,
)
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService


YEAR = 2026
MONTHS = (1, 2, 3)
TOLERANCE = Decimal("0.01")


def dec(value):
    return Decimal(str(value or 0))


def close(left, right):
    return abs(dec(left) - dec(right)) <= TOLERANCE


def main():
    app = create_app()
    failures = []
    records = []
    with app.app_context():
        uploads = {}
        for month in MONTHS:
            upload = ProductionResultService.final_upload(YEAR, month)
            uploads[month] = upload
            print(
                "Q1_UNIT_UPLOAD|"
                f"month={month}|id={getattr(upload, 'id', None)}|"
                f"stage={getattr(upload, 'production_stage', None)}|"
                f"status={getattr(upload, 'status', None)}"
            )

        region_codes = sorted({
            str(row[0])
            for upload in uploads.values() if upload is not None
            for row in db.session.query(ProductionRegionProductResult.region_code)
                .filter_by(upload_id=upload.id).distinct().all()
        })
        products = {row.id: row.product_name for row in Product.query.all()}
        # Exercise the deployed explicit-marker plus all-region quota classifier.
        quota_months = ProductionResultService.quota_product_months(
            [(YEAR, month) for month in MONTHS]
        )
        print("Q1_QUOTA_PRODUCTS|" + json.dumps({
            products[product_id]: [f"{month:02d}/{year}" for year, month in periods]
            for product_id, periods in quota_months.items()
        }, ensure_ascii=False, sort_keys=True))
        print(f"Q1_UNIT_SCOPE|regions={len(region_codes)}|products={len(products)}|months=3")
        print("Q1_UNIT_REGIONS|" + json.dumps(region_codes, ensure_ascii=False))

        for region in region_codes:
            service = RegionPerformanceService(region, YEAR, 3)
            monthly_screen = {}
            for month in MONTHS:
                report = service.aggregate([(YEAR, month)])
                monthly_screen[month] = {row["product_id"]: row for row in report["products"]}

                upload = uploads[month]
                production_rows = {
                    row.product_id: row
                    for row in ProductionRegionProductResult.query.filter_by(
                        upload_id=upload.id, region_code=region
                    ).all()
                } if upload is not None else {}

                ims_target_rows = db.session.query(
                    Target.product_id,
                    func.coalesce(func.sum(Target.unit_target), 0.0),
                ).join(
                    Representative, Representative.id == Target.representative_id
                ).filter(
                    Target.year == YEAR,
                    Target.month == month,
                    Target.representative_id.in_(service.rep_ids),
                ).group_by(Target.product_id).all()
                ims_targets = {pid: dec(value) for pid, value in ims_target_rows}

                ims_actual_rows = db.session.query(
                    IMSSummary.product_id,
                    func.coalesce(func.sum(IMSSummary.unit), 0.0),
                ).filter(
                    IMSSummary.year == YEAR,
                    IMSSummary.month == month,
                    IMSSummary.representative_id.in_(service.rep_ids),
                ).group_by(IMSSummary.product_id).all()
                ims_actuals = {pid: dec(value) for pid, value in ims_actual_rows}

                product_ids = sorted(set(production_rows) | set(ims_targets) | set(monthly_screen[month]))
                for product_id in product_ids:
                    prod = production_rows.get(product_id)
                    screen = monthly_screen[month].get(product_id)
                    expected_target = dec(prod.target_unit) if prod is not None else ims_targets.get(product_id, Decimal("0"))
                    expected_actual = dec(prod.actual_unit) if prod is not None else ims_actuals.get(product_id, Decimal("0"))
                    passed = bool(screen) and screen["unit_complete"] and close(screen["target_unit"], expected_target) and close(screen["actual_unit"], expected_actual)
                    record = {
                        "region": region,
                        "month": month,
                        "product": products.get(product_id, str(product_id)),
                        "source": f"P{upload.production_stage}" if prod is not None else "IMS",
                        "ims_target": float(ims_targets.get(product_id, Decimal("0"))),
                        "ims_actual": float(ims_actuals.get(product_id, Decimal("0"))),
                        "production_target": float(dec(prod.target_unit)) if prod is not None else None,
                        "production_actual": float(dec(prod.actual_unit)) if prod is not None else None,
                        "production_target_tl": float(dec(prod.target_tl)) if prod is not None else None,
                        "production_actual_tl": float(dec(prod.actual_tl)) if prod is not None else None,
                        "production_tl_percent": float(dec(prod.realization_percent)) if prod is not None else None,
                        "production_unit_percent": float(dec(prod.unit_realization_percent)) if prod is not None else None,
                        "screen_target": float(dec(screen["target_unit"])) if screen else None,
                        "screen_actual": float(dec(screen["actual_unit"])) if screen and screen["actual_unit"] is not None else None,
                        "screen_difference": float(dec(screen["unit_difference"])) if screen and screen["unit_difference"] is not None else None,
                        "pass": passed,
                    }
                    records.append(record)
                    if not passed:
                        failures.append(record)

            quarter = service.aggregate([(YEAR, month) for month in MONTHS])
            quarter_by_product = {row["product_id"]: row for row in quarter["products"]}
            for product_id, qrow in quarter_by_product.items():
                month_rows = [monthly_screen[m].get(product_id) for m in MONTHS]
                expected_target = sum((dec(row["target_unit"]) for row in month_rows if row), Decimal("0"))
                expected_actual = sum((dec(row["actual_unit"]) for row in month_rows if row and row["actual_unit"] is not None), Decimal("0"))
                passed = qrow["unit_complete"] and all(row and row["unit_complete"] for row in month_rows) and close(qrow["target_unit"], expected_target) and close(qrow["actual_unit"], expected_actual)
                if not passed:
                    failures.append({
                        "region": region,
                        "month": "Q1",
                        "product": products.get(product_id, str(product_id)),
                        "expected_target": float(expected_target),
                        "expected_actual": float(expected_actual),
                        "screen_target": float(dec(qrow["target_unit"])),
                        "screen_actual": float(dec(qrow["actual_unit"])),
                        "pass": False,
                    })

        print("Q1_UNIT_DIYARBAKIR_BEGIN")
        for record in records:
            if record["region"] == "901":
                print("Q1_UNIT_DIYARBAKIR|" + json.dumps(record, ensure_ascii=False, sort_keys=True))
        print("Q1_UNIT_DIYARBAKIR_END")
        for record in records:
            if record["region"] == "901" and record["month"] == 3 and record["product"] == "Monurol":
                target_tl = dec(record["production_target_tl"])
                actual_tl = dec(record["production_actual_tl"])
                target_unit = dec(record["production_target"])
                actual_unit = dec(record["production_actual"])
                focused = {
                    **record,
                    "calculated_tl_difference": float(actual_tl - target_tl),
                    "calculated_tl_percent": float(actual_tl * Decimal("100") / target_tl),
                    "calculated_unit_difference": float(actual_unit - target_unit),
                    "calculated_unit_percent": float(actual_unit * Decimal("100") / target_unit),
                }
                print("MONUROL_901_MARCH|" + json.dumps(focused, ensure_ascii=False, sort_keys=True))
        for failure in failures[:100]:
            print("Q1_UNIT_FAILURE|" + json.dumps(failure, ensure_ascii=False, sort_keys=True))
        print(
            "Q1_UNIT_RESULT|"
            f"{'PASS' if not failures else 'FAIL'}|records={len(records)}|failures={len(failures)}|"
            f"regions={len(region_codes)}"
        )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
