"""Snapshot-only executive reporting read model and professional file exports."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
import unicodedata

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import and_, or_

from app.models import Product, Representative, RepresentativeBrickAssignment
from app.services.alias_service import AliasService
from app.services.period_service import PeriodService
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
)
from app.services.realization_rounding import realization_percent


class ExecutiveReportingService:
    PERIODS = {
        "monthly": "Aylık",
        "quarterly": "3 Aylık",
        "half_year": "6 Aylık · Ocak–Haziran",
        "yearly": "Yıllık",
    }
    SCOPES = {
        "national": "National",
        "region": "Bölge",
        "city": "İl",
        "representative": "Temsilci",
    }
    REGION_LABELS = {
        "101": "İstanbul",
        "201": "Kadıköy",
        "301": "Bursa",
        "401": "İzmir",
        "501": "Ankara",
        "601": "Samsun",
        "602": "Trabzon",
        "701": "Adana",
        "801": "Konya",
        "802": "Antalya",
        "901": "Diyarbakır",
    }

    def __init__(self, *, year=None, month=None, period="monthly", scope="national",
                 scope_value="", scope_values=None, product_ids=None):
        active = PeriodService.get_active_period()
        self.year = int(year or active.get("year") or datetime.now().year)
        self.month = max(1, min(12, int(month or active.get("month") or datetime.now().month)))
        self.period = period if period in self.PERIODS else "monthly"
        self.scope = scope if scope in self.SCOPES else "national"
        raw_scope_values = scope_values if scope_values is not None else [scope_value]
        scope_values = [
            str(value).strip()
            for value in raw_scope_values
            if str(value or "").strip()
        ]
        if self.scope == "region":
            scope_values = sorted(
                {self._region_code(value) or value for value in scope_values},
                key=lambda value: int(value) if str(value).isdigit() else 9999,
            )
        elif self.scope == "city":
            scope_values = sorted(set(scope_values), key=self._scope_key)
        elif self.scope == "representative":
            scope_values = [
                str(value) for value in sorted(
                    {int(value) for value in scope_values if str(value).isdigit()}
                )
            ]
        else:
            scope_values = []
        self.scope_values = scope_values
        # Backward-compatible scalar accessor for old links/warm jobs.
        self.scope_value = self.scope_values[0] if self.scope_values else ""
        self.product_ids = {int(value) for value in (product_ids or []) if str(value).isdigit()}

    def months(self):
        if self.period == "monthly":
            return [(self.year, self.month)]
        if self.period == "quarterly":
            ordinal = self.year * 12 + self.month - 1
            return [((ordinal - delta) // 12, (ordinal - delta) % 12 + 1) for delta in (2, 1, 0)]
        if self.period == "half_year":
            return [(self.year, month) for month in range(1, 7)]
        return [(self.year, month) for month in range(1, self.month + 1)]

    @staticmethod
    def _region_code(value):
        match = re.search(r"(?<!\d)(\d{3})(?!\d)", str(value or ""))
        return match.group(1) if match else ""

    @classmethod
    def _region_label(cls, value):
        raw = str(value or "").strip()
        code = cls._region_code(raw)
        if code in cls.REGION_LABELS:
            return cls.REGION_LABELS[code]
        descriptive = re.sub(r"^\s*\d{3}\s*", "", raw).strip()
        if descriptive and descriptive != code:
            return descriptive.title()
        return raw or "Bölge"

    @staticmethod
    def _scope_key(value):
        return AliasService.normalize(value).strip()

    def _assignment_rows(self):
        periods = list(dict.fromkeys(self.months()))
        if not periods:
            return []
        conditions = [
            and_(
                RepresentativeBrickAssignment.year == year,
                RepresentativeBrickAssignment.month == month,
            )
            for year, month in periods
        ]
        return RepresentativeBrickAssignment.query.filter(
            RepresentativeBrickAssignment.active.is_(True),
            or_(*conditions),
        ).all()

    def filter_options(self):
        reps = Representative.query.filter(
            Representative.active.is_(True)
        ).order_by(
            Representative.region.asc(), Representative.city.asc(), Representative.rep_name.asc()
        ).all()

        region_labels = {}
        for representative in reps:
            raw = str(representative.region or "").strip()
            if not raw:
                continue
            code = self._region_code(raw) or raw
            region_labels.setdefault(code, self._region_label(raw))

        assignments = self._assignment_rows()
        active_rep_ids = {int(row.id) for row in reps}
        assignment_cities = {
            str(row.city).strip()
            for row in assignments
            if int(row.representative_id) in active_rep_ids and str(row.city or "").strip()
        }
        cities = assignment_cities or {
            str(row.city).strip()
            for row in reps
            if str(row.city or "").strip()
        }

        return {
            "products": Product.query.filter_by(is_active=True).order_by(
                Product.display_order.asc(), Product.product_name.asc()
            ).all(),
            "regions": [
                {"value": value, "label": label}
                for value, label in sorted(
                    region_labels.items(),
                    key=lambda item: (int(item[0]) if str(item[0]).isdigit() else 9999, item[1]),
                )
            ],
            "cities": [
                {"value": city, "label": city}
                for city in sorted(cities, key=self._scope_key)
            ],
            "representatives": reps,
        }

    def _representatives(self):
        rows = Representative.query.filter(
            Representative.active.is_(True)
        ).order_by(Representative.rep_name.asc()).all()
        if self.scope == "region" and self.scope_values:
            selected_codes = {
                self._region_code(value) or str(value).strip()
                for value in self.scope_values
            }
            rows = [
                row for row in rows
                if (self._region_code(row.region) or str(row.region or "").strip()) in selected_codes
            ]
        elif self.scope == "city" and self.scope_values:
            selected_cities = {self._scope_key(value) for value in self.scope_values}
            assignment_rep_ids = {
                int(row.representative_id)
                for row in self._assignment_rows()
                if self._scope_key(row.city) in selected_cities
            }
            if assignment_rep_ids:
                rows = [row for row in rows if int(row.id) in assignment_rep_ids]
            else:
                rows = [row for row in rows if self._scope_key(row.city) in selected_cities]
        elif self.scope == "representative" and self.scope_values:
            selected_ids = {
                int(value) for value in self.scope_values if str(value).isdigit()
            }
            rows = [row for row in rows if int(row.id) in selected_ids]
        return rows

    def _representative_city_map(self, representatives):
        selected_ids = {int(row.id) for row in representatives}
        cities = defaultdict(set)
        for assignment in self._assignment_rows():
            rep_id = int(assignment.representative_id)
            if rep_id in selected_ids and str(assignment.city or "").strip():
                cities[rep_id].add(str(assignment.city).strip())
        return {
            int(row.id): ", ".join(sorted(cities.get(int(row.id)) or {str(row.city or "").strip() or "-"}, key=self._scope_key))
            for row in representatives
        }

    def _brick_city_map(self, representatives):
        selected_ids = {int(row.id) for row in representatives}
        mapping = {}
        for assignment in self._assignment_rows():
            rep_id = int(assignment.representative_id)
            if rep_id not in selected_ids:
                continue
            brick_key = self._scope_key(assignment.brick)
            if brick_key:
                mapping[(rep_id, brick_key)] = str(assignment.city or "").strip() or "-"
        return mapping

    @staticmethod
    def _rival_rows(market):
        for row in (market or {}).get("rows") or []:
            product = row.get("product") or {}
            product_id = row.get("product_id") or product.get("id")
            for rival in row.get("rivals") or []:
                yield product_id, rival

    def build(self):
        representatives = self._representatives()
        rep_ids = [int(row.id) for row in representatives]
        rep_meta = {int(row.id): row for row in representatives}
        rep_city_map = self._representative_city_map(representatives)
        brick_city_map = self._brick_city_map(representatives)

        products = Product.query.order_by(Product.display_order, Product.product_name).all()
        product_meta = {int(row.id): row for row in products}
        product_name_to_id = {
            self._scope_key(row.product_name): int(row.id)
            for row in products
        }

        buckets = defaultdict(lambda: {
            "target_tl": 0.0, "actual_tl": 0.0, "target_unit": 0.0, "actual_unit": 0.0,
            "market_unit": 0.0, "rivals": defaultdict(float), "months": set(),
        })
        rep_buckets = {
            rep_id: {
                "target_tl": 0.0, "actual_tl": 0.0, "target_unit": 0.0,
                "actual_unit": 0.0, "market_unit": 0.0,
            }
            for rep_id in rep_ids
        }
        brick_buckets = defaultdict(lambda: {
            "company_unit": 0.0, "competitor_unit": 0.0, "market_unit": 0.0,
            "rivals": defaultdict(float),
        })
        trend = []
        source_weeks = []

        for year, month in self.months():
            snapshots = PersistentRepresentativeSnapshotService.get_active_many(rep_ids, year, month)
            monthly_totals = defaultdict(float)
            for rep_id, payload in snapshots.items():
                rep_id = int(rep_id)
                monthly = ((payload or {}).get("snapshots") or {}).get("monthly") or {}
                rep_bucket = rep_buckets.setdefault(rep_id, defaultdict(float))

                for row in monthly.get("products") or []:
                    product = row.get("product") or {}
                    product_id = row.get("product_id") or product.get("id")
                    if product_id is None:
                        continue
                    product_id = int(product_id)
                    if self.product_ids and product_id not in self.product_ids:
                        continue
                    bucket = buckets[product_id]
                    for key in ("target_tl", "actual_tl", "target_unit", "actual_unit"):
                        value = float(row.get(key, 0) or 0)
                        bucket[key] += value
                        rep_bucket[key] += value
                        monthly_totals[key] += value
                    bucket["months"].add((year, month))

                market = monthly.get("market_analysis") or {}
                source_week = market.get("source_week") or market.get("latest_week")
                if source_week is not None:
                    source_weeks.append(int(source_week))

                for row in market.get("rows") or []:
                    product = row.get("product") or {}
                    product_id = row.get("product_id") or product.get("id")
                    if product_id is None:
                        continue
                    product_id = int(product_id)
                    if self.product_ids and product_id not in self.product_ids:
                        continue
                    market_unit = float(row.get("market_unit", 0) or 0)
                    buckets[product_id]["market_unit"] += market_unit
                    rep_bucket["market_unit"] += market_unit

                for product_id, rival in self._rival_rows(market):
                    if product_id is None:
                        continue
                    product_id = int(product_id)
                    if self.product_ids and product_id not in self.product_ids:
                        continue
                    name = str(rival.get("name") or rival.get("product_name") or "Rakip").strip()
                    buckets[product_id]["rivals"][name] += float(
                        rival.get("unit", rival.get("value", rival.get("metric_value", 0))) or 0
                    )

                for row in market.get("brick_product_rows") or []:
                    product_name = str(row.get("product_name") or "").strip()
                    product_id = product_name_to_id.get(self._scope_key(product_name))
                    if self.product_ids and (product_id is None or product_id not in self.product_ids):
                        continue
                    brick = str(row.get("brick") or "Brick bilgisi yok").strip()
                    key = (rep_id, self._scope_key(brick), product_id or self._scope_key(product_name))
                    brick_bucket = brick_buckets[key]
                    brick_bucket["representative_id"] = rep_id
                    brick_bucket["brick"] = brick
                    brick_bucket["product_id"] = product_id
                    brick_bucket["product_name"] = (
                        product_meta[product_id].product_name
                        if product_id in product_meta else product_name or "Ürün"
                    )
                    company_unit = float(row.get("company_unit", 0) or 0)
                    competitor_unit = float(row.get("competitor_unit", 0) or 0)
                    market_unit = float(row.get("market_unit", 0) or 0)
                    brick_bucket["company_unit"] += company_unit
                    brick_bucket["competitor_unit"] += competitor_unit
                    brick_bucket["market_unit"] += market_unit
                    for market_product in row.get("market_products") or []:
                        if market_product.get("is_company"):
                            continue
                        rival_name = str(market_product.get("name") or "Rakip").strip()
                        brick_bucket["rivals"][rival_name] += float(market_product.get("unit", 0) or 0)

            trend.append({
                "label": f"{month:02d}/{year}",
                "actual_tl": round(monthly_totals["actual_tl"], 2),
                "actual_unit": round(monthly_totals["actual_unit"], 2),
            })

        rows = []
        for product_id, values in buckets.items():
            product = product_meta.get(product_id)
            if product is None:
                continue
            market_unit = values["market_unit"]
            company_unit = values["actual_unit"]
            competitor_unit = (
                max(market_unit - company_unit, 0.0)
                if market_unit else sum(values["rivals"].values())
            )
            rows.append({
                "product_id": product_id,
                "product_name": product.product_name,
                "target_tl": round(values["target_tl"], 2),
                "actual_tl": round(values["actual_tl"], 2),
                "realization_percent": (
                    realization_percent(values["actual_tl"], values["target_tl"])
                    if values["target_tl"] else 0
                ),
                "target_unit": round(values["target_unit"], 2),
                "actual_unit": round(company_unit, 2),
                "market_unit": round(market_unit, 2),
                "competitor_unit": round(competitor_unit, 2),
                "market_share_percent": (
                    round(company_unit * 100 / market_unit, 1) if market_unit else None
                ),
                "rivals": [
                    {
                        "name": name,
                        "unit": round(value, 2),
                        "share_percent": (
                            round(value * 100 / market_unit, 1) if market_unit else None
                        ),
                    }
                    for name, value in sorted(
                        values["rivals"].items(), key=lambda item: item[1], reverse=True
                    )
                ],
            })
        rows.sort(key=lambda row: (product_meta[row["product_id"]].display_order, row["product_name"]))

        totals = {
            key: round(sum(row[key] for row in rows), 2)
            for key in (
                "target_tl", "actual_tl", "target_unit", "actual_unit",
                "market_unit", "competitor_unit",
            )
        }
        totals["realization_percent"] = (
            realization_percent(totals["actual_tl"], totals["target_tl"])
            if totals["target_tl"] else 0
        )
        totals["market_share_percent"] = (
            round(totals["actual_unit"] * 100 / totals["market_unit"], 1)
            if totals["market_unit"] else None
        )

        representative_rows = []
        for rep_id in rep_ids:
            representative = rep_meta[rep_id]
            values = rep_buckets.get(rep_id) or {}
            target_tl = float(values.get("target_tl", 0) or 0)
            actual_tl = float(values.get("actual_tl", 0) or 0)
            actual_unit = float(values.get("actual_unit", 0) or 0)
            market_unit = float(values.get("market_unit", 0) or 0)
            representative_rows.append({
                "representative_id": rep_id,
                "representative_name": representative.rep_name,
                "region_code": self._region_code(representative.region) or str(representative.region or ""),
                "region_name": self._region_label(representative.region),
                "city": rep_city_map.get(rep_id, str(representative.city or "") or "-"),
                "target_tl": round(target_tl, 2),
                "actual_tl": round(actual_tl, 2),
                "realization_percent": (
                    realization_percent(actual_tl, target_tl) if target_tl else 0
                ),
                "target_unit": round(float(values.get("target_unit", 0) or 0), 2),
                "actual_unit": round(actual_unit, 2),
                "market_unit": round(market_unit, 2),
                "market_share_percent": (
                    round(actual_unit * 100 / market_unit, 1) if market_unit else None
                ),
            })
        representative_rows.sort(
            key=lambda row: (
                int(row["region_code"]) if str(row["region_code"]).isdigit() else 9999,
                self._scope_key(row["representative_name"]),
            )
        )

        region_buckets = defaultdict(lambda: {
            "target_tl": 0.0, "actual_tl": 0.0, "actual_unit": 0.0,
            "market_unit": 0.0, "representative_count": 0,
        })
        for row in representative_rows:
            bucket = region_buckets[row["region_code"]]
            bucket["region_name"] = row["region_name"]
            bucket["target_tl"] += row["target_tl"]
            bucket["actual_tl"] += row["actual_tl"]
            bucket["actual_unit"] += row["actual_unit"]
            bucket["market_unit"] += row["market_unit"]
            bucket["representative_count"] += 1
        region_rows = []
        for region_code, values in region_buckets.items():
            region_rows.append({
                "region_code": region_code,
                "region_name": values["region_name"],
                "representative_count": values["representative_count"],
                "target_tl": round(values["target_tl"], 2),
                "actual_tl": round(values["actual_tl"], 2),
                "realization_percent": (
                    realization_percent(values["actual_tl"], values["target_tl"])
                    if values["target_tl"] else 0
                ),
                "actual_unit": round(values["actual_unit"], 2),
                "market_unit": round(values["market_unit"], 2),
                "market_share_percent": (
                    round(values["actual_unit"] * 100 / values["market_unit"], 1)
                    if values["market_unit"] else None
                ),
            })
        region_rows.sort(
            key=lambda row: (
                int(row["region_code"]) if str(row["region_code"]).isdigit() else 9999,
                row["region_name"],
            )
        )

        brick_rows = []
        for values in brick_buckets.values():
            rep_id = int(values["representative_id"])
            representative = rep_meta.get(rep_id)
            if representative is None:
                continue
            market_unit = float(values["market_unit"] or 0)
            company_unit = float(values["company_unit"] or 0)
            rivals = sorted(values["rivals"].items(), key=lambda item: item[1], reverse=True)
            brick_key = self._scope_key(values["brick"])
            brick_rows.append({
                "region_name": self._region_label(representative.region),
                "city": brick_city_map.get(
                    (rep_id, brick_key),
                    rep_city_map.get(rep_id, str(representative.city or "") or "-"),
                ),
                "representative_id": rep_id,
                "representative_name": representative.rep_name,
                "brick": values["brick"],
                "product_id": values["product_id"],
                "product_name": values["product_name"],
                "company_unit": round(company_unit, 2),
                "competitor_unit": round(float(values["competitor_unit"] or 0), 2),
                "market_unit": round(market_unit, 2),
                "share_percent": (
                    round(company_unit * 100 / market_unit, 1) if market_unit else None
                ),
                "rivals": [
                    {"name": name, "unit": round(unit, 2)}
                    for name, unit in rivals
                ],
            })
        brick_rows.sort(
            key=lambda row: (
                self._scope_key(row["region_name"]),
                self._scope_key(row["city"]),
                self._scope_key(row["representative_name"]),
                self._scope_key(row["brick"]),
                self._scope_key(row["product_name"]),
            )
        )

        rival_rows = [
            {
                "product_name": row["product_name"],
                "market_unit": row["market_unit"],
                "company_unit": row["actual_unit"],
                "company_share_percent": row["market_share_percent"],
                **rival,
            }
            for row in rows for rival in row["rivals"]
        ]

        return {
            "year": self.year,
            "month": self.month,
            "period": self.period,
            "period_label": self.PERIODS[self.period],
            "scope": self.scope,
            "scope_values": list(self.scope_values),
            "scope_label": self.scope_label(),
            "rows": rows,
            "totals": totals,
            "trend": trend,
            "region_rows": region_rows,
            "representative_rows": representative_rows,
            "rival_rows": rival_rows,
            "brick_rows": brick_rows,
            "representative_count": len(representatives),
            "source_week": max(source_weeks) if source_weeks else None,
            "generated_at": datetime.now(),
        }

    def scope_label(self):
        if self.scope == "national":
            return "Türkiye Geneli"

        labels = []
        if self.scope == "region":
            labels = [self._region_label(value) for value in self.scope_values]
        elif self.scope == "city":
            labels = list(self.scope_values)
        elif self.scope == "representative":
            ids = [int(value) for value in self.scope_values if str(value).isdigit()]
            names = {
                int(row.id): row.rep_name
                for row in Representative.query.filter(
                    Representative.id.in_(ids),
                    Representative.active.is_(True),
                ).all()
            } if ids else {}
            labels = [str(names.get(value, f"Temsilci {value}")) for value in ids]

        if not labels:
            return {
                "region": "Tüm Bölgeler",
                "city": "Tüm İller",
                "representative": "Tüm Temsilciler",
            }.get(self.scope, self.SCOPES[self.scope])
        if len(labels) <= 3:
            return " + ".join(labels)
        return " + ".join(labels[:3]) + f" +{len(labels) - 3}"

    @staticmethod
    def _filename_slug(value):
        text = str(value or "").strip().replace("ı", "i").replace("İ", "I")
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()

    def export_filename(self, report, file_type):
        prefixes = {
            "national": "national-analiz-raporu",
            "region": "bolge-analiz-raporu",
            "city": "il-analiz-raporu",
            "representative": "temsilci-analiz-raporu",
        }
        prefix = prefixes.get(self.scope, "analiz-raporu")
        scope_slug = ""
        if self.scope != "national":
            scope_slug = self._filename_slug(report.get("scope_label"))
        parts = [prefix]
        if scope_slug:
            parts.append(scope_slug)
        parts.extend([str(report["year"]), f'{int(report["month"]):02d}'])
        return "-".join(parts) + f".{file_type}"

    @staticmethod
    def _headers():
        return ["Ürün", "Hedef TL", "Gerçekleşen TL", "Realizasyon %", "Hedef Kutu",
                "Gerçekleşen Kutu", "Toplam Pazar Kutu", "Rakip Kutu", "Pazar Payı %", "Başlıca Rakipler"]

    @staticmethod
    def _rivals_by_product(report):
        grouped = defaultdict(list)
        ordered_products = []
        for row in report.get("rows") or []:
            product_name = str(row.get("product_name") or "Ürün")
            ordered_products.append(product_name)
        for item in report.get("rival_rows") or []:
            product_name = str(item.get("product_name") or "Ürün")
            grouped[product_name].append(item)
        result = []
        seen = set()
        for product_name in ordered_products + sorted(grouped):
            if product_name in seen or product_name not in grouped:
                continue
            seen.add(product_name)
            rows = sorted(
                grouped[product_name],
                key=lambda item: float(item.get("unit") or 0),
                reverse=True,
            )
            result.append((product_name, rows))
        return result

    @staticmethod
    def _excel_title(sheet, title, subtitle, end_column):
        navy, blue, white = "123E70", "0B5CAD", "FFFFFF"
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_column)
        sheet.cell(1, 1, title)
        sheet.cell(1, 1).font = Font(name="Aptos Display", size=20, bold=True, color=white)
        sheet.cell(1, 1).fill = PatternFill("solid", fgColor=navy)
        sheet.cell(1, 1).alignment = Alignment(vertical="center")
        sheet.row_dimensions[1].height = 34
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=end_column)
        sheet.cell(2, 1, subtitle)
        sheet.cell(2, 1).font = Font(name="Aptos", size=10, color=white)
        sheet.cell(2, 1).fill = PatternFill("solid", fgColor=blue)
        sheet.row_dimensions[2].height = 23

    @staticmethod
    def _style_excel_header(cells):
        for cell in cells:
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF", size=10)
            cell.fill = PatternFill("solid", fgColor="0B5CAD")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def to_excel(self, report):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Yönetim Özeti"
        subtitle = f'{report["scope_label"]} | {report["period_label"]} | {report["year"]}/{report["month"]:02d}'
        self._excel_title(sheet, "SATIŞ VE PAZAR PERFORMANS RAPORU", subtitle, 10)
        sheet.append([])
        sheet.append([
            "Kapsam", report["scope_label"], "Dönem", report["period_label"],
            "Rapor Ayı", f'{report["year"]}/{report["month"]:02d}',
            "Temsilci", report["representative_count"], "IMS Hafta", report["source_week"] or "-",
        ])
        sheet.append([])
        sheet.append([
            "Hedef TL", report["totals"]["target_tl"],
            "Gerçekleşen TL", report["totals"]["actual_tl"],
            "TL Realizasyon", report["totals"]["realization_percent"] / 100,
            "Pazar Payı", (report["totals"]["market_share_percent"] or 0) / 100,
            "Toplam Pazar Kutu", report["totals"]["market_unit"],
        ])
        for column in range(1, 11, 2):
            sheet.cell(6, column).font = Font(name="Aptos", bold=True, color="64748B", size=9)
            sheet.cell(6, column).fill = PatternFill("solid", fgColor="EAF1F8")
            sheet.cell(6, column + 1).font = Font(name="Aptos Display", bold=True, color="123E70", size=13)
            sheet.cell(6, column + 1).fill = PatternFill("solid", fgColor="F5F8FC")
        sheet.cell(6, 2).number_format = '₺#,##0'
        sheet.cell(6, 4).number_format = '₺#,##0'
        sheet.cell(6, 6).number_format = '0%'
        sheet.cell(6, 8).number_format = '0.0%'
        sheet.cell(6, 10).number_format = '#,##0'
        sheet.append([])
        sheet.append(self._headers()[:-1])
        for row in report["rows"]:
            sheet.append([
                row["product_name"], row["target_tl"], row["actual_tl"], row["realization_percent"],
                row["target_unit"], row["actual_unit"], row["market_unit"], row["competitor_unit"],
                row["market_share_percent"],
            ])
        last_row = sheet.max_row
        self._style_excel_header(sheet[8])
        sheet.freeze_panes = "A9"
        sheet.auto_filter.ref = f"A8:I{last_row}"
        thin = Side(style="thin", color="DCE5EF")
        for row in sheet.iter_rows(min_row=9, max_row=last_row, min_col=1, max_col=9):
            for cell in row:
                cell.border = Border(bottom=thin)
                cell.font = Font(name="Aptos", size=10, color="203247")
                cell.alignment = Alignment(vertical="center")
            for cell in row[1:3]:
                cell.number_format = '₺#,##0'
            row[3].number_format = '0"%"'
            for cell in row[4:8]:
                cell.number_format = '#,##0'
            row[8].number_format = '0.0"%"'
        widths = [23, 16, 18, 14, 15, 18, 18, 16, 14, 14]
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.sheet_view.showGridLines = False
        sheet.print_title_rows = "1:8"
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

        if last_row >= 9:
            performance_chart = BarChart()
            performance_chart.type = "col"
            performance_chart.style = 10
            performance_chart.title = "Ürün Bazında Hedef / Gerçekleşen TL"
            performance_chart.y_axis.title = "TL"
            performance_chart.x_axis.title = "Ürün"
            performance_chart.height = 7.8
            performance_chart.width = 14.5
            performance_chart.gapWidth = 65
            performance_chart.add_data(
                Reference(sheet, min_col=2, max_col=3, min_row=8, max_row=last_row),
                titles_from_data=True,
            )
            performance_chart.set_categories(
                Reference(sheet, min_col=1, min_row=9, max_row=last_row)
            )
            performance_chart.legend.position = "b"
            if len(performance_chart.series) >= 2:
                performance_chart.series[0].graphicalProperties.solidFill = "94A3B8"
                performance_chart.series[1].graphicalProperties.solidFill = "0B5CAD"
            performance_chart.dLbls = DataLabelList()
            performance_chart.dLbls.showVal = False
            sheet.add_chart(performance_chart, "K4")
            sheet.print_area = f"A1:Q{max(last_row, 20)}"
        else:
            sheet.print_area = f"A1:J{last_row}"

        trend = workbook.create_sheet("Dönem Trendi")
        self._excel_title(trend, "DÖNEMSEL SATIŞ GELİŞİMİ", subtitle, 4)
        trend.append([])
        trend.append(["Dönem", "Gerçekleşen TL", "Gerçekleşen Kutu", "TL Payı"])
        total_trend_tl = sum(float(row["actual_tl"] or 0) for row in report["trend"])
        for item in report["trend"]:
            trend.append([
                item["label"], item["actual_tl"], item["actual_unit"],
                (item["actual_tl"] / total_trend_tl) if total_trend_tl else 0,
            ])
        self._style_excel_header(trend[4])
        for row in trend.iter_rows(min_row=5, max_row=trend.max_row):
            row[1].number_format = '₺#,##0'
            row[2].number_format = '#,##0'
            row[3].number_format = '0.0%'
        chart = LineChart()
        chart.style = 13
        chart.title = "Gerçekleşen TL Trendi"
        chart.y_axis.title = "TL"
        chart.x_axis.title = "Dönem"
        chart.height = 8
        chart.width = 16
        chart.add_data(
            Reference(trend, min_col=2, min_row=4, max_row=trend.max_row),
            titles_from_data=True,
        )
        chart.set_categories(Reference(trend, min_col=1, min_row=5, max_row=trend.max_row))
        chart.legend = None
        if chart.series:
            chart.series[0].graphicalProperties.line.solidFill = "0B5CAD"
            chart.series[0].graphicalProperties.line.width = 28575
            chart.series[0].marker.symbol = "circle"
            chart.series[0].marker.size = 7
        chart.dLbls = DataLabelList()
        chart.dLbls.showVal = True
        chart.dLbls.numFmt = '#,##0'
        trend.add_chart(chart, "F4")
        for index, width in enumerate([18, 20, 20, 14], 1):
            trend.column_dimensions[get_column_letter(index)].width = width
        trend.freeze_panes = "A5"
        trend.sheet_view.showGridLines = False
        trend.page_setup.orientation = "landscape"
        trend.page_setup.paperSize = trend.PAPERSIZE_A4
        trend.page_setup.fitToWidth = 1
        trend.page_setup.fitToHeight = 1
        trend.sheet_properties.pageSetUpPr.fitToPage = True

        regions = workbook.create_sheet("Bölge Analizi")
        self._excel_title(regions, "BÖLGE PERFORMANS ANALİZİ", subtitle, 9)
        regions.append([])
        regions.append([
            "Bölge", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon %",
            "Gerçekleşen Kutu", "Toplam Pazar Kutu", "Pazar Payı %", "Bölge Kodu",
        ])
        for item in report.get("region_rows") or []:
            regions.append([
                item["region_name"], item["representative_count"], item["target_tl"],
                item["actual_tl"], item["realization_percent"], item["actual_unit"],
                item["market_unit"], item["market_share_percent"], item["region_code"],
            ])
        self._style_excel_header(regions[4])
        regions.freeze_panes = "A5"
        regions.auto_filter.ref = f"A4:I{max(4, regions.max_row)}"
        regions.sheet_view.showGridLines = False
        for row in regions.iter_rows(min_row=5, max_row=regions.max_row):
            row[2].number_format = '₺#,##0'
            row[3].number_format = '₺#,##0'
            row[4].number_format = '0"%"'
            row[5].number_format = '#,##0'
            row[6].number_format = '#,##0'
            row[7].number_format = '0.0"%"'
        for index, width in enumerate([22, 12, 17, 18, 15, 18, 18, 15, 12], 1):
            regions.column_dimensions[get_column_letter(index)].width = width
        regions.page_setup.orientation = "landscape"
        regions.page_setup.paperSize = regions.PAPERSIZE_A4
        regions.page_setup.fitToWidth = 1
        regions.page_setup.fitToHeight = 0
        regions.sheet_properties.pageSetUpPr.fitToPage = True

        reps = workbook.create_sheet("Temsilci Analizi")
        self._excel_title(reps, "TEMSİLCİ PERFORMANS ANALİZİ", subtitle, 10)
        reps.append([])
        reps.append([
            "Bölge", "İl", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon %",
            "Hedef Kutu", "Gerçekleşen Kutu", "Toplam Pazar", "Pazar Payı %",
        ])
        for item in report.get("representative_rows") or []:
            reps.append([
                item["region_name"], item["city"], item["representative_name"],
                item["target_tl"], item["actual_tl"], item["realization_percent"],
                item["target_unit"], item["actual_unit"], item["market_unit"],
                item["market_share_percent"],
            ])
        self._style_excel_header(reps[4])
        reps.freeze_panes = "A5"
        reps.auto_filter.ref = f"A4:J{max(4, reps.max_row)}"
        reps.sheet_view.showGridLines = False
        for row in reps.iter_rows(min_row=5, max_row=reps.max_row):
            row[3].number_format = '₺#,##0'
            row[4].number_format = '₺#,##0'
            row[5].number_format = '0"%"'
            row[6].number_format = '#,##0'
            row[7].number_format = '#,##0'
            row[8].number_format = '#,##0'
            row[9].number_format = '0.0"%"'
        for index, width in enumerate([20, 18, 28, 17, 18, 15, 15, 18, 18, 15], 1):
            reps.column_dimensions[get_column_letter(index)].width = width
        reps.page_setup.orientation = "landscape"
        reps.page_setup.paperSize = reps.PAPERSIZE_A4
        reps.page_setup.fitToWidth = 1
        reps.page_setup.fitToHeight = 0
        reps.sheet_properties.pageSetUpPr.fitToPage = True

        bricks = workbook.create_sheet("Brick Analizi")
        self._excel_title(bricks, "BRICK VE REKABET ANALİZİ", subtitle, 11)
        bricks.append([])
        bricks.append([
            "Bölge", "İl", "Temsilci", "Brick", "Ürün", "Şirket Kutu",
            "Rakip Toplam Kutu", "Toplam Pazar", "Pazar Payı %",
            "En Güçlü Rakip", "En Güçlü Rakip Kutu",
        ])
        for item in report.get("brick_rows") or []:
            top_rival = (item.get("rivals") or [{}])[0]
            bricks.append([
                item["region_name"], item["city"], item["representative_name"], item["brick"],
                item["product_name"], item["company_unit"], item["competitor_unit"],
                item["market_unit"], item["share_percent"],
                top_rival.get("name") or "-", top_rival.get("unit") or 0,
            ])
        self._style_excel_header(bricks[4])
        bricks.freeze_panes = "A5"
        bricks.auto_filter.ref = f"A4:K{max(4, bricks.max_row)}"
        bricks.sheet_view.showGridLines = False
        for row in bricks.iter_rows(min_row=5, max_row=bricks.max_row):
            row[5].number_format = '#,##0'
            row[6].number_format = '#,##0'
            row[7].number_format = '#,##0'
            row[8].number_format = '0.0"%"'
            row[10].number_format = '#,##0'
        for index, width in enumerate([18, 16, 24, 24, 20, 14, 17, 16, 14, 28, 20], 1):
            bricks.column_dimensions[get_column_letter(index)].width = width
        bricks.page_setup.orientation = "landscape"
        bricks.page_setup.paperSize = bricks.PAPERSIZE_A4
        bricks.page_setup.fitToWidth = 1
        bricks.page_setup.fitToHeight = 0
        bricks.sheet_properties.pageSetUpPr.fitToPage = True

        rival_groups = self._rivals_by_product(report)
        rivals = workbook.create_sheet("Rakip Analizi")
        self._excel_title(rivals, "RAKİP ANALİZİ · YÖNETİM ÖZETİ", subtitle, 8)
        rivals.append([])
        rivals.append([
            "Ürün", "Şirket Kutu", "Şirket Pazar Payı", "Toplam Pazar",
            "Rakip Sayısı", "Lider Rakip", "Lider Rakip Kutu", "Lider Rakip Payı",
        ])
        for product_name, items in rival_groups:
            leader = items[0] if items else {}
            sample = items[0] if items else {}
            rivals.append([
                product_name,
                sample.get("company_unit") or 0,
                (sample.get("company_share_percent") or 0) / 100,
                sample.get("market_unit") or 0,
                len(items),
                leader.get("name") or "-",
                leader.get("unit") or 0,
                (leader.get("share_percent") or 0) / 100,
            ])
        self._style_excel_header(rivals[4])
        rivals.freeze_panes = "A5"
        rivals.auto_filter.ref = f"A4:H{max(4, rivals.max_row)}"
        rivals.sheet_view.showGridLines = False
        for row in rivals.iter_rows(min_row=5, max_row=rivals.max_row):
            row[1].number_format = '#,##0'
            row[2].number_format = '0.0%'
            row[3].number_format = '#,##0'
            row[6].number_format = '#,##0'
            row[7].number_format = '0.0%'
        for index, width in enumerate([24, 16, 20, 18, 14, 30, 19, 18], 1):
            rivals.column_dimensions[get_column_letter(index)].width = width
        rivals.page_setup.orientation = "landscape"
        rivals.page_setup.paperSize = rivals.PAPERSIZE_A4
        rivals.page_setup.fitToWidth = 1
        rivals.page_setup.fitToHeight = 0
        rivals.sheet_properties.pageSetUpPr.fitToPage = True
        rivals.print_title_rows = "1:4"
        rivals.print_area = f"A1:H{max(4, rivals.max_row)}"

        used_titles = set(workbook.sheetnames)
        for product_name, items in rival_groups:
            raw_title = re.sub(r'[:\\/?*\[\]]+', "-", f"Rakip - {product_name}").strip()
            base_title = raw_title[:31] or "Rakip Detayı"
            title = base_title
            counter = 2
            while title in used_titles:
                suffix = f" {counter}"
                title = base_title[:31 - len(suffix)] + suffix
                counter += 1
            used_titles.add(title)

            detail = workbook.create_sheet(title)
            self._excel_title(detail, f"{product_name.upper()} · RAKİP DETAYI", subtitle, 6)
            detail.append([])
            detail.append([
                "Rakip", "Rakip Kutu", "Rakip Pazar Payı",
                "Şirket Kutu", "Şirket Pazar Payı", "Toplam Pazar Kutu",
            ])
            for item in items:
                detail.append([
                    item["name"], item["unit"], (item["share_percent"] or 0) / 100,
                    item["company_unit"], (item["company_share_percent"] or 0) / 100,
                    item["market_unit"],
                ])
            self._style_excel_header(detail[4])
            detail.freeze_panes = "A5"
            detail.auto_filter.ref = f"A4:F{max(4, detail.max_row)}"
            detail.sheet_view.showGridLines = False
            for row in detail.iter_rows(min_row=5, max_row=detail.max_row):
                row[1].number_format = '#,##0'
                row[2].number_format = '0.0%'
                row[3].number_format = '#,##0'
                row[4].number_format = '0.0%'
                row[5].number_format = '#,##0'
            for index, width in enumerate([34, 18, 20, 18, 20, 20], 1):
                detail.column_dimensions[get_column_letter(index)].width = width

            if detail.max_row >= 5:
                rival_chart = BarChart()
                rival_chart.type = "bar"
                rival_chart.style = 10
                rival_chart.title = f"{product_name} · Rakip Kutu Dağılımı"
                rival_chart.x_axis.title = "Kutu"
                rival_chart.y_axis.title = "Rakip"
                rival_chart.height = 8
                rival_chart.width = 12.5
                rival_chart.gapWidth = 45
                rival_chart.add_data(
                    Reference(detail, min_col=2, min_row=4, max_row=detail.max_row),
                    titles_from_data=True,
                )
                rival_chart.set_categories(
                    Reference(detail, min_col=1, min_row=5, max_row=detail.max_row)
                )
                rival_chart.legend = None
                if rival_chart.series:
                    rival_chart.series[0].graphicalProperties.solidFill = "E87422"
                rival_chart.dLbls = DataLabelList()
                rival_chart.dLbls.showVal = True
                rival_chart.dLbls.numFmt = '#,##0'
                detail.add_chart(rival_chart, "H4")
                detail.print_area = f"A1:N{max(detail.max_row, 22)}"
            else:
                detail.print_area = f"A1:F{detail.max_row}"
            detail.page_setup.orientation = "landscape"
            detail.page_setup.paperSize = detail.PAPERSIZE_A4
            detail.page_setup.fitToWidth = 1
            detail.page_setup.fitToHeight = 0
            detail.sheet_properties.pageSetUpPr.fitToPage = True

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    def to_pdf(self, report):
        """Create a branded, multi-page management report with full rival detail."""
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        output = BytesIO()
        font_name, bold_name = "Helvetica", "Helvetica-Bold"
        for regular, bold in (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),):
            try:
                pdfmetrics.registerFont(TTFont("ReportSans", regular)); pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
                font_name, bold_name = "ReportSans", "ReportSans-Bold"
            except Exception:
                pass
        navy, blue, green, pale, line = colors.HexColor("#123E70"), colors.HexColor("#0B5CAD"), colors.HexColor("#16865B"), colors.HexColor("#F3F7FB"), colors.HexColor("#DCE5EF")
        styles = getSampleStyleSheet()
        title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName=bold_name, fontSize=19, leading=23, textColor=colors.white, alignment=TA_LEFT)
        subtitle = ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontName=font_name, fontSize=8.5, leading=12, textColor=colors.HexColor("#DDEBFA"))
        heading = ParagraphStyle("Heading", parent=styles["Heading2"], fontName=bold_name, fontSize=12, leading=15, textColor=navy, spaceAfter=7)
        normal = ParagraphStyle("NormalTR", parent=styles["Normal"], fontName=font_name, fontSize=7.5, leading=10, textColor=colors.HexColor("#25364A"))
        small = ParagraphStyle("SmallTR", parent=normal, fontSize=6.5, leading=8)

        def footer(canvas, doc):
            canvas.saveState(); canvas.setStrokeColor(line); canvas.line(14*mm, 10*mm, 283*mm, 10*mm)
            canvas.setFont(font_name, 6.5); canvas.setFillColor(colors.HexColor("#64748B"))
            canvas.drawString(14*mm, 6*mm, f'IMS Performans Takip Sistemi | {report["scope_label"]}')
            canvas.drawRightString(283*mm, 6*mm, f'Sayfa {doc.page}'); canvas.restoreState()

        doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=14*mm, leftMargin=14*mm, topMargin=12*mm, bottomMargin=14*mm, title="Satış ve Pazar Performans Raporu")
        story = []
        hero = Table([[Paragraph("SATIŞ VE PAZAR PERFORMANS RAPORU", title), Paragraph(f'{report["scope_label"]}<br/>{report["period_label"]} - {report["year"]}/{report["month"]:02d}', subtitle)]], colWidths=[190*mm, 74*mm])
        hero.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),navy),("BACKGROUND",(1,0),(1,0),blue),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)])); story += [hero, Spacer(1, 7*mm)]
        total = report["totals"]
        kpis = [["HEDEF TL", "GERÇEKLEŞEN TL", "TL REALİZASYON", "PAZAR PAYI", "TOPLAM PAZAR"], [f'₺{total["target_tl"]:,.0f}', f'₺{total["actual_tl"]:,.0f}', f'%{total["realization_percent"]}', f'%{total["market_share_percent"]:.1f}' if total["market_share_percent"] is not None else "-", f'{total["market_unit"]:,.0f} kutu']]
        kpi_table = Table(kpis, colWidths=[52.8*mm]*5, rowHeights=[7*mm, 13*mm]); kpi_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),pale),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#64748B")),("FONTNAME",(0,0),(-1,0),bold_name),("FONTSIZE",(0,0),(-1,0),6.5),("FONTNAME",(0,1),(-1,1),bold_name),("FONTSIZE",(0,1),(-1,1),13),("TEXTCOLOR",(0,1),(-1,1),navy),("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BOX",(0,0),(-1,-1),.5,line),("INNERGRID",(0,0),(-1,-1),.5,line)])); story += [kpi_table, Spacer(1, 7*mm), Paragraph("Ürün performansı", heading)]
        product_data = [["Ürün", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Hedef Kutu", "Gerçekleşen Kutu", "Toplam Pazar", "Pazar Payı"]]
        for row in report["rows"]:
            product_data.append([Paragraph(row["product_name"], normal), f'₺{row["target_tl"]:,.0f}', f'₺{row["actual_tl"]:,.0f}', f'%{row["realization_percent"]}', f'{row["target_unit"]:,.0f}', f'{row["actual_unit"]:,.0f}', f'{row["market_unit"]:,.0f}', f'%{row["market_share_percent"]:.1f}' if row["market_share_percent"] is not None else "-"])
        product_table = Table(product_data, repeatRows=1, colWidths=[39*mm,35*mm,38*mm,28*mm,31*mm,36*mm,31*mm,27*mm])
        product_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),blue),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),bold_name),("FONTNAME",(0,1),(-1,-1),font_name),("FONTSIZE",(0,0),(-1,-1),7),("ALIGN",(1,1),(-1,-1),"RIGHT"),("ALIGN",(0,0),(-1,0),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,pale]),("GRID",(0,0),(-1,-1),.35,line),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story += [product_table, PageBreak(), Paragraph("Bölge karşılaştırması", heading)]
        region_data = [["Bölge", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Gerçekleşen Kutu", "Toplam Pazar", "Pazar Payı"]]
        for item in report.get("region_rows") or []:
            region_data.append([
                Paragraph(item["region_name"], small),
                f'{item["representative_count"]}',
                f'₺{item["target_tl"]:,.0f}',
                f'₺{item["actual_tl"]:,.0f}',
                f'%{item["realization_percent"]}',
                f'{item["actual_unit"]:,.0f}',
                f'{item["market_unit"]:,.0f}',
                f'%{item["market_share_percent"]:.1f}' if item["market_share_percent"] is not None else "-",
            ])
        if len(region_data) == 1:
            region_data.append(["Veri yok", "-", "-", "-", "-", "-", "-", "-"])
        region_table = Table(
            region_data, repeatRows=1,
            colWidths=[45*mm, 25*mm, 36*mm, 39*mm, 29*mm, 36*mm, 31*mm, 27*mm],
        )
        region_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),blue),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),bold_name),("FONTNAME",(0,1),(-1,-1),font_name),
            ("FONTSIZE",(0,0),(-1,-1),6.6),("ALIGN",(1,1),(-1,-1),"RIGHT"),
            ("ALIGN",(0,0),(-1,0),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,pale]),
            ("GRID",(0,0),(-1,-1),.3,line),("TOPPADDING",(0,0),(-1,-1),4),
            ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        story += [region_table, PageBreak(), Paragraph("Temsilci performansı", heading)]
        representative_data = [["Bölge", "İl", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Gerçekleşen Kutu", "Pazar Payı"]]
        for item in report.get("representative_rows") or []:
            representative_data.append([
                Paragraph(item["region_name"], small),
                Paragraph(item["city"], small),
                Paragraph(item["representative_name"], small),
                f'₺{item["target_tl"]:,.0f}',
                f'₺{item["actual_tl"]:,.0f}',
                f'%{item["realization_percent"]}',
                f'{item["actual_unit"]:,.0f}',
                f'%{item["market_share_percent"]:.1f}' if item["market_share_percent"] is not None else "-",
            ])
        if len(representative_data) == 1:
            representative_data.append(["Veri yok", "-", "-", "-", "-", "-", "-", "-"])
        representative_table = Table(
            representative_data, repeatRows=1,
            colWidths=[29*mm, 27*mm, 53*mm, 34*mm, 36*mm, 27*mm, 34*mm, 28*mm],
        )
        representative_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),blue),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),bold_name),("FONTNAME",(0,1),(-1,-1),font_name),
            ("FONTSIZE",(0,0),(-1,-1),6.6),("ALIGN",(3,1),(-1,-1),"RIGHT"),
            ("ALIGN",(0,0),(-1,0),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,pale]),
            ("GRID",(0,0),(-1,-1),.3,line),("TOPPADDING",(0,0),(-1,-1),4),
            ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        story += [representative_table, PageBreak(), Paragraph("Tüm rakipler ve aylık pazar payları", heading), Paragraph("Pazar payı, seçilen kapsam ve dönemde ilgili ürünün toplam pazar kutusu üzerinden hesaplanır.", normal), Spacer(1, 3*mm)]
        rival_data = [["Ürün", "Rakip", "Rakip Kutu", "Rakibin Pazar Payı", "Şirket Kutu", "Şirket Pazar Payı", "Toplam Pazar"]]
        for item in report["rival_rows"]:
            rival_data.append([Paragraph(item["product_name"], small), Paragraph(item["name"], small), f'{item["unit"]:,.0f}', f'%{item["share_percent"]:.1f}' if item["share_percent"] is not None else "-", f'{item["company_unit"]:,.0f}', f'%{item["company_share_percent"]:.1f}' if item["company_share_percent"] is not None else "-", f'{item["market_unit"]:,.0f}'])
        if len(rival_data) == 1: rival_data.append(["Veri yok", "-", "-", "-", "-", "-", "-"])
        rival_table = Table(rival_data, repeatRows=1, colWidths=[35*mm,74*mm,29*mm,37*mm,29*mm,37*mm,28*mm])
        rival_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),navy),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),bold_name),("FONTNAME",(0,1),(-1,-1),font_name),("FONTSIZE",(0,0),(-1,-1),6.7),("ALIGN",(2,1),(-1,-1),"RIGHT"),("ALIGN",(0,0),(-1,0),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,pale]),("GRID",(0,0),(-1,-1),.3,line),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        story += [rival_table, PageBreak(), Paragraph("Brick ve rekabet analizi", heading)]
        brick_data = [["Bölge", "İl", "Temsilci", "Brick", "Ürün", "Şirket", "Rakip", "Pazar", "Pay"]]
        all_pdf_bricks = report.get("brick_rows") or []
        pdf_bricks = all_pdf_bricks
        if len(all_pdf_bricks) > 500:
            pdf_bricks = sorted(
                all_pdf_bricks,
                key=lambda item: (
                    -float(item.get("competitor_unit") or 0),
                    str(item.get("brick") or ""),
                ),
            )[:500]
            story.append(Paragraph(
                f"PDF yönetim görünümünde en yüksek rakip baskısına sahip 500 brick satırı gösterilir. "
                f"Tam {len(all_pdf_bricks)} satır Excel Brick Analizi sayfasında bulunur.",
                normal,
            ))
            story.append(Spacer(1, 2*mm))
        for item in pdf_bricks:
            brick_data.append([
                Paragraph(item["region_name"], small),
                Paragraph(item["city"], small),
                Paragraph(item["representative_name"], small),
                Paragraph(item["brick"], small),
                Paragraph(item["product_name"], small),
                f'{item["company_unit"]:,.0f}',
                f'{item["competitor_unit"]:,.0f}',
                f'{item["market_unit"]:,.0f}',
                f'%{item["share_percent"]:.1f}' if item["share_percent"] is not None else "-",
            ])
        if len(brick_data) == 1:
            brick_data.append(["Veri yok", "-", "-", "-", "-", "-", "-", "-", "-"])
        brick_table = Table(
            brick_data, repeatRows=1,
            colWidths=[25*mm,24*mm,42*mm,43*mm,31*mm,22*mm,22*mm,22*mm,21*mm],
        )
        brick_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),navy),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),bold_name),("FONTNAME",(0,1),(-1,-1),font_name),
            ("FONTSIZE",(0,0),(-1,-1),6.1),("ALIGN",(5,1),(-1,-1),"RIGHT"),
            ("ALIGN",(0,0),(-1,0),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,pale]),
            ("GRID",(0,0),(-1,-1),.25,line),("TOPPADDING",(0,0),(-1,-1),3),
            ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(brick_table)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        output.seek(0); return output

    def to_powerpoint(self, report):
        """Create a branded, editable 16:9 management presentation."""
        from pptx import Presentation
        from pptx.chart.data import ChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Inches, Pt

        navy = RGBColor(13, 50, 86)
        blue = RGBColor(12, 92, 173)
        teal = RGBColor(24, 134, 91)
        orange = RGBColor(232, 116, 34)
        ink = RGBColor(31, 49, 69)
        muted = RGBColor(101, 116, 139)
        pale = RGBColor(241, 246, 251)
        line = RGBColor(218, 228, 238)
        white = RGBColor(255, 255, 255)
        font = "Aptos"
        logo = Path(__file__).resolve().parents[1] / "static" / "img" / "bilim-ilac-corporate.png"

        deck = Presentation()
        deck.slide_width = Inches(13.333)
        deck.slide_height = Inches(7.5)
        blank = deck.slide_layouts[6]

        def fill(shape, color):
            shape.fill.solid()
            shape.fill.fore_color.rgb = color
            shape.line.fill.background()

        def text_box(slide, text, left, top, width, height, *, size=18, color=ink,
                     bold=False, align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP):
            shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
            frame = shape.text_frame
            frame.clear()
            frame.word_wrap = True
            frame.vertical_anchor = valign
            paragraph = frame.paragraphs[0]
            paragraph.alignment = align
            run = paragraph.add_run()
            run.text = str(text)
            run.font.name = font
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
            return shape

        def add_footer(slide, page):
            rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.48), Inches(7.12), Inches(12.36), Inches(.012))
            fill(rule, line)
            text_box(slide, f'IMS Performans Takip Sistemi  ·  {report["scope_label"]}', .52, 7.17, 6.8, .18, size=7, color=muted)
            text_box(slide, str(page), 11.55, 7.16, .42, .2, size=7, color=muted, align=PP_ALIGN.RIGHT)
            if logo.is_file():
                slide.shapes.add_picture(str(logo), Inches(12.13), Inches(7.13), width=Inches(.50), height=Inches(.24))

        def add_heading(slide, title, section, page):
            bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, deck.slide_width, Inches(.12))
            fill(bar, teal)
            text_box(slide, section.upper(), .55, .36, 4.0, .24, size=8, color=blue, bold=True)
            text_box(slide, title, .55, .68, 11.9, .52, size=25, color=navy, bold=True)
            add_footer(slide, page)

        def style_table(table, *, header_size=9, body_size=8):
            table.first_row = True
            for column, cell in enumerate(table.rows[0].cells):
                cell.fill.solid(); cell.fill.fore_color.rgb = navy
                cell.margin_left = cell.margin_right = Inches(.08)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.alignment = PP_ALIGN.LEFT if column == 0 else PP_ALIGN.RIGHT
                    for run in paragraph.runs:
                        run.font.name = font; run.font.size = Pt(header_size); run.font.bold = True; run.font.color.rgb = white
            for row_index in range(1, len(table.rows)):
                row = table.rows[row_index]
                for column, cell in enumerate(row.cells):
                    cell.fill.solid(); cell.fill.fore_color.rgb = white if row_index % 2 else pale
                    cell.margin_left = cell.margin_right = Inches(.08)
                    for paragraph in cell.text_frame.paragraphs:
                        paragraph.alignment = PP_ALIGN.LEFT if column == 0 else PP_ALIGN.RIGHT
                        for run in paragraph.runs:
                            run.font.name = font; run.font.size = Pt(body_size); run.font.color.rgb = ink

        def add_table_slide(title, section, headers, rows, page, widths=None):
            slide = deck.slides.add_slide(blank)
            add_heading(slide, title, section, page)
            display_rows = rows or [["Veri bulunamadı"] + ["—"] * (len(headers) - 1)]
            shape = slide.shapes.add_table(
                len(display_rows) + 1, len(headers), Inches(.55), Inches(1.43), Inches(12.23), Inches(5.42)
            )
            table = shape.table
            if widths:
                for index, value in enumerate(widths):
                    table.columns[index].width = Inches(value)
            for index, value in enumerate(headers):
                table.cell(0, index).text = str(value)
            for row_index, values in enumerate(display_rows, 1):
                for column_index, value in enumerate(values):
                    table.cell(row_index, column_index).text = str(value)
            style_table(table, header_size=8.5, body_size=7.5 if len(display_rows) > 10 else 8.5)
            return slide

        def pages(values, size):
            rows = list(values or [])
            return [rows[index:index + size] for index in range(0, len(rows), size)] or [[]]

        page = 1
        cover = deck.slides.add_slide(blank)
        background = cover.background.fill
        background.solid(); background.fore_color.rgb = navy
        accent = cover.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(.18), deck.slide_height)
        fill(accent, teal)
        orb = cover.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.03), Inches(0), Inches(3.3), Inches(3.3))
        fill(orb, blue)
        text_box(cover, "SATIŞ VE PAZAR PERFORMANS RAPORU", .78, 1.60, 8.5, 1.15, size=30, color=white, bold=True)
        text_box(cover, report["scope_label"], .82, 3.02, 7.6, .55, size=19, color=white, bold=True)
        text_box(cover, f'{report["period_label"]}  ·  {report["year"]}/{report["month"]:02d}', .82, 3.66, 7.6, .42, size=14, color=RGBColor(202, 225, 245))
        text_box(cover, f'{report["representative_count"]} temsilci  ·  IMS {report.get("source_week") or "—"}. hafta', .82, 4.22, 7.6, .35, size=10, color=RGBColor(202, 225, 245))
        if logo.is_file():
            logo_back = cover.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(.78), Inches(6.08), Inches(1.92), Inches(.78))
            fill(logo_back, white)
            cover.shapes.add_picture(str(logo), Inches(.98), Inches(6.24), width=Inches(1.52), height=Inches(.46))
        text_box(cover, "Yönetim Raporları", 9.55, 6.68, 2.7, .22, size=8, color=RGBColor(202, 225, 245), align=PP_ALIGN.RIGHT)

        page += 1
        summary = deck.slides.add_slide(blank)
        add_heading(summary, "Yönetim özeti", "Genel görünüm", page)
        total = report["totals"]
        kpis = [
            ("Hedef TL", f'₺{total["target_tl"]:,.0f}', blue),
            ("Gerçekleşen TL", f'₺{total["actual_tl"]:,.0f}', teal),
            ("TL realizasyon", f'%{total["realization_percent"]}', orange),
            ("Pazar payı", f'%{total["market_share_percent"]:.1f}' if total["market_share_percent"] is not None else "—", RGBColor(121, 88, 181)),
        ]
        for index, (label, value, color) in enumerate(kpis):
            left = .58 + index * 3.08
            card = summary.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(1.55), Inches(2.78), Inches(1.38))
            fill(card, pale)
            stripe = summary.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(1.55), Inches(.06), Inches(1.38))
            fill(stripe, color)
            text_box(summary, label.upper(), left + .2, 1.78, 2.35, .22, size=8, color=muted, bold=True)
            value_size = 17 if len(value) > 12 else 22
            text_box(summary, value, left + .2, 2.15, 2.35, .48, size=value_size, color=navy, bold=True)
        text_box(summary, "Rapor kapsamı", .62, 3.35, 3.1, .3, size=12, color=navy, bold=True)
        scope_lines = [
            f'Kapsam: {report["scope_label"]}',
            f'Dönem: {report["period_label"]}',
            f'Ürün sayısı: {len(report.get("rows") or [])}',
            f'Toplam pazar: {total["market_unit"]:,.0f} kutu',
        ]
        text_box(summary, "\n".join(scope_lines), .62, 3.83, 4.0, 1.7, size=13, color=ink)
        product_rows = sorted(report.get("rows") or [], key=lambda row: float(row.get("actual_tl") or 0), reverse=True)
        if product_rows:
            chart_data = ChartData()
            chart_data.categories = [row["product_name"] for row in product_rows]
            chart_data.add_series("Gerçekleşen TL", [float(row.get("actual_tl") or 0) for row in product_rows])
            chart = summary.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(4.65), Inches(3.32), Inches(7.65), Inches(3.25), chart_data).chart
            chart.has_legend = False; chart.has_title = False
            chart.value_axis.tick_labels.font.name = font; chart.value_axis.tick_labels.font.size = Pt(8)
            chart.category_axis.tick_labels.font.name = font; chart.category_axis.tick_labels.font.size = Pt(9)
            chart.series[0].format.fill.solid(); chart.series[0].format.fill.fore_color.rgb = blue

        page += 1
        trend_slide = deck.slides.add_slide(blank)
        add_heading(trend_slide, "Dönemsel satış gelişimi", "Satış trendi", page)
        trend = report.get("trend") or []
        if trend:
            trend_data = ChartData(); trend_data.categories = [item["label"] for item in trend]
            trend_data.add_series("Gerçekleşen TL", [float(item.get("actual_tl") or 0) for item in trend])
            chart = trend_slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(.7), Inches(1.45), Inches(11.9), Inches(4.95), trend_data).chart
            chart.has_legend = False; chart.has_title = False
            chart.value_axis.tick_labels.font.name = font; chart.value_axis.tick_labels.font.size = Pt(9)
            chart.category_axis.tick_labels.font.name = font; chart.category_axis.tick_labels.font.size = Pt(10)
            series = chart.series[0]; series.format.line.color.rgb = blue; series.format.line.width = Pt(2.5)
        else:
            text_box(trend_slide, "Seçili dönemde trend verisi bulunamadı.", .7, 2.6, 11.8, .7, size=18, color=muted, align=PP_ALIGN.CENTER)

        product_data = [[
            row["product_name"], f'₺{row["target_tl"]:,.0f}', f'₺{row["actual_tl"]:,.0f}',
            f'%{row["realization_percent"]}', f'{row["actual_unit"]:,.0f}',
            f'{row["market_unit"]:,.0f}', f'%{row["market_share_percent"]:.1f}' if row["market_share_percent"] is not None else "—",
        ] for row in report.get("rows") or []]
        for index, chunk in enumerate(pages(product_data, 12), 1):
            page += 1
            add_table_slide(
                "Ürün performansı" + (f"  ·  {index}" if len(product_data) > 12 else ""), "Portföy analizi",
                ["Ürün", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Kutu", "Toplam pazar", "Pazar payı"],
                chunk, page, [2.35, 1.75, 1.85, 1.35, 1.35, 1.65, 1.45],
            )

        sections = [
            ("Bölge performansı", "Organizasyon", report.get("region_rows") or [], 11,
             ["Bölge", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Pazar payı"],
             lambda row: [row["region_name"], row["representative_count"], f'₺{row["target_tl"]:,.0f}', f'₺{row["actual_tl"]:,.0f}', f'%{row["realization_percent"]}', f'%{row["market_share_percent"]:.1f}' if row["market_share_percent"] is not None else "—"],
             [2.5, 1.3, 2.15, 2.15, 1.7, 1.7]),
            ("Temsilci performansı", "Saha performansı", report.get("representative_rows") or [], 12,
             ["Bölge", "İl", "Temsilci", "Hedef TL", "Gerçekleşen TL", "Realizasyon", "Pazar payı"],
             lambda row: [row["region_name"], row["city"], row["representative_name"], f'₺{row["target_tl"]:,.0f}', f'₺{row["actual_tl"]:,.0f}', f'%{row["realization_percent"]}', f'%{row["market_share_percent"]:.1f}' if row["market_share_percent"] is not None else "—"],
             [1.55, 1.45, 2.55, 1.75, 1.85, 1.45, 1.45]),
            ("Rakip analizi", "Pazar görünümü", report.get("rival_rows") or [], 12,
             ["Ürün", "Rakip", "Rakip kutu", "Rakip payı", "Şirket kutu", "Şirket payı", "Toplam pazar"],
             lambda row: [row["product_name"], row["name"], f'{row["unit"]:,.0f}', f'%{row["share_percent"]:.1f}' if row["share_percent"] is not None else "—", f'{row["company_unit"]:,.0f}', f'%{row["company_share_percent"]:.1f}' if row["company_share_percent"] is not None else "—", f'{row["market_unit"]:,.0f}'],
             [1.65, 2.5, 1.45, 1.45, 1.45, 1.45, 1.65]),
        ]
        for title, section, raw_rows, per_page, headers, formatter, widths in sections:
            formatted = [formatter(row) for row in raw_rows]
            chunks = pages(formatted, per_page)
            for index, chunk in enumerate(chunks, 1):
                page += 1
                add_table_slide(title + (f"  ·  {index}" if len(chunks) > 1 else ""), section, headers, chunk, page, widths)

        priority_bricks = sorted(
            report.get("brick_rows") or [],
            key=lambda row: (-float(row.get("competitor_unit") or 0), str(row.get("brick") or "")),
        )[:30]
        brick_data = [[
            row["city"], row["representative_name"], row["brick"], row["product_name"],
            f'{row["company_unit"]:,.0f}', f'{row["competitor_unit"]:,.0f}',
            f'%{row["share_percent"]:.1f}' if row["share_percent"] is not None else "—",
        ] for row in priority_bricks]
        brick_chunks = pages(brick_data, 10)
        for index, chunk in enumerate(brick_chunks, 1):
            page += 1
            slide = add_table_slide(
                "Öncelikli brickler" + (f"  ·  {index}" if len(brick_chunks) > 1 else ""), "Rekabet baskısı",
                ["İl", "Temsilci", "Brick", "Ürün", "Şirket", "Rakip", "Pazar payı"],
                chunk, page, [1.45, 2.2, 2.65, 1.6, 1.3, 1.3, 1.45],
            )
            if index == 1 and len(report.get("brick_rows") or []) > len(priority_bricks):
                text_box(slide, f'Rakip kutusu en yüksek 30 satır gösterilir. Tam {len(report.get("brick_rows") or [])} satır Excel çıktısında bulunur.', .62, 6.87, 10.8, .2, size=7, color=muted)

        page += 1
        closing = deck.slides.add_slide(blank)
        add_heading(closing, "Rapor kapsamı ve veri kaynağı", "Metodoloji", page)
        notes = [
            "Rapor yalnız yayınlanmış temsilci snapshot verilerinden hazırlanır.",
            "Pazar payı, ilgili ürünün toplam pazar kutusu üzerinden hesaplanır.",
            "Altı aylık rapor Ocak ile Haziran dönemini kapsar.",
            "Sunumdaki tablolar ve grafikler PowerPoint içinde düzenlenebilir.",
            "Tam satır düzeyindeki brick dökümü Excel çıktısında yer alır.",
        ]
        for index, note in enumerate(notes, 1):
            number = closing.shapes.add_shape(MSO_SHAPE.OVAL, Inches(.75), Inches(1.45 + (index - 1) * .94), Inches(.42), Inches(.42))
            fill(number, blue if index < 5 else teal)
            text_box(closing, index, .75, 1.49 + (index - 1) * .94, .42, .25, size=10, color=white, bold=True, align=PP_ALIGN.CENTER)
            text_box(closing, note, 1.38, 1.43 + (index - 1) * .94, 10.7, .5, size=15, color=ink)

        deck.core_properties.title = "Satış ve Pazar Performans Raporu"
        deck.core_properties.subject = f'{report["scope_label"]} · {report["period_label"]}'
        deck.core_properties.author = "Bilim İlaç"
        output = BytesIO()
        deck.save(output)
        output.seek(0)
        return output
