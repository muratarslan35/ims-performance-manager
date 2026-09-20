"""Snapshot-only executive reporting read model and file exports."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.models import Product, Representative
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

    def __init__(self, *, year=None, month=None, period="monthly", scope="national",
                 scope_value="", product_ids=None):
        active = PeriodService.get_active_period()
        self.year = int(year or active.get("year") or datetime.now().year)
        self.month = max(1, min(12, int(month or active.get("month") or datetime.now().month)))
        self.period = period if period in self.PERIODS else "monthly"
        self.scope = scope if scope in self.SCOPES else "national"
        self.scope_value = str(scope_value or "").strip()
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
    def filter_options():
        reps = Representative.query.order_by(
            Representative.region.asc(), Representative.city.asc(), Representative.rep_name.asc()
        ).all()
        return {
            "products": Product.query.filter_by(is_active=True).order_by(
                Product.display_order.asc(), Product.product_name.asc()
            ).all(),
            "regions": sorted({str(row.region).strip() for row in reps if str(row.region or "").strip()}),
            "cities": sorted({str(row.city).strip() for row in reps if str(row.city or "").strip()}),
            "representatives": reps,
        }

    def _representatives(self):
        query = Representative.query
        if self.scope == "region":
            query = query.filter(Representative.region == self.scope_value) if self.scope_value else query.filter(Representative.id == -1)
        elif self.scope == "city":
            query = query.filter(Representative.city == self.scope_value) if self.scope_value else query.filter(Representative.id == -1)
        elif self.scope == "representative":
            query = query.filter(Representative.id == int(self.scope_value)) if self.scope_value.isdigit() else query.filter(Representative.id == -1)
        return query.order_by(Representative.rep_name.asc()).all()

    @staticmethod
    def _rival_rows(market):
        for row in (market or {}).get("rows") or []:
            product = row.get("product") or {}
            product_id = row.get("product_id") or product.get("id")
            for rival in row.get("rivals") or []:
                yield product_id, rival

    def build(self):
        representatives = self._representatives()
        rep_ids = [row.id for row in representatives]
        product_meta = {row.id: row for row in Product.query.order_by(Product.display_order, Product.product_name).all()}
        buckets = defaultdict(lambda: {
            "target_tl": 0.0, "actual_tl": 0.0, "target_unit": 0.0, "actual_unit": 0.0,
            "market_unit": 0.0, "rivals": defaultdict(float), "months": set(),
        })
        trend = []
        source_weeks = []

        for year, month in self.months():
            snapshots = PersistentRepresentativeSnapshotService.get_active_many(rep_ids, year, month)
            monthly_totals = defaultdict(float)
            for rep_id, payload in snapshots.items():
                monthly = ((payload or {}).get("snapshots") or {}).get("monthly") or {}
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
                    buckets[product_id]["market_unit"] += float(row.get("market_unit", 0) or 0)
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
            competitor_unit = max(market_unit - company_unit, 0.0) if market_unit else sum(values["rivals"].values())
            rows.append({
                "product_id": product_id,
                "product_name": product.product_name,
                "target_tl": round(values["target_tl"], 2),
                "actual_tl": round(values["actual_tl"], 2),
                "realization_percent": realization_percent(values["actual_tl"], values["target_tl"]) if values["target_tl"] else 0,
                "target_unit": round(values["target_unit"], 2),
                "actual_unit": round(company_unit, 2),
                "market_unit": round(market_unit, 2),
                "competitor_unit": round(competitor_unit, 2),
                "market_share_percent": round(company_unit * 100 / market_unit, 1) if market_unit else None,
                "rivals": [
                    {"name": name, "unit": round(value, 2)}
                    for name, value in sorted(values["rivals"].items(), key=lambda item: item[1], reverse=True)[:10]
                ],
            })
        rows.sort(key=lambda row: (product_meta[row["product_id"]].display_order, row["product_name"]))
        totals = {
            key: round(sum(row[key] for row in rows), 2)
            for key in ("target_tl", "actual_tl", "target_unit", "actual_unit", "market_unit", "competitor_unit")
        }
        totals["realization_percent"] = realization_percent(totals["actual_tl"], totals["target_tl"]) if totals["target_tl"] else 0
        totals["market_share_percent"] = round(totals["actual_unit"] * 100 / totals["market_unit"], 1) if totals["market_unit"] else None
        return {
            "year": self.year, "month": self.month, "period": self.period,
            "period_label": self.PERIODS[self.period], "scope": self.scope,
            "scope_label": self.scope_label(), "rows": rows, "totals": totals,
            "trend": trend, "representative_count": len(representatives),
            "source_week": max(source_weeks) if source_weeks else None,
            "generated_at": datetime.now(),
        }

    def scope_label(self):
        if self.scope == "national":
            return "Türkiye Geneli"
        if self.scope == "representative" and self.scope_value.isdigit():
            row = Representative.query.filter_by(id=int(self.scope_value)).first()
            return row.rep_name if row else "Temsilci"
        return self.scope_value or self.SCOPES[self.scope]

    @staticmethod
    def _headers():
        return ["Ürün", "Hedef TL", "Gerçekleşen TL", "Realizasyon %", "Hedef Kutu",
                "Gerçekleşen Kutu", "Toplam Pazar Kutu", "Rakip Kutu", "Pazar Payı %", "Başlıca Rakipler"]

    def to_excel(self, report):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Genel Müdür Raporu"
        sheet.append(["GENEL MÜDÜR PAZAR RAPORU"])
        sheet.append(["Kapsam", report["scope_label"], "Dönem", report["period_label"], "Yıl/Ay", f'{report["year"]}/{report["month"]:02d}'])
        sheet.append([])
        sheet.append(self._headers())
        for row in report["rows"]:
            sheet.append([
                row["product_name"], row["target_tl"], row["actual_tl"], row["realization_percent"],
                row["target_unit"], row["actual_unit"], row["market_unit"], row["competitor_unit"],
                row["market_share_percent"], ", ".join(item["name"] for item in row["rivals"][:5]),
            ])
        sheet.freeze_panes = "A5"
        sheet.auto_filter.ref = f"A4:J{max(4, sheet.max_row)}"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF", size=14)
            cell.fill = PatternFill("solid", fgColor="123E70")
        for cell in sheet[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0B5CAD")
            cell.alignment = Alignment(horizontal="center")
        widths = [24, 16, 18, 15, 15, 18, 18, 15, 15, 34]
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[chr(64 + index)].width = width
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    def to_pdf(self, report):
        """Create a dependency-free, valid PDF containing the filtered result."""
        lines = [
            "GENEL MUDUR PAZAR RAPORU",
            f'Kapsam: {report["scope_label"]} | Donem: {report["period_label"]} | {report["year"]}/{report["month"]:02d}',
            "",
            "Urun | Hedef TL | Gerceklesen TL | % | Kutu | Pazar | Pay %",
        ]
        for row in report["rows"]:
            lines.append(
                f'{row["product_name"][:24]} | {row["target_tl"]:.0f} | {row["actual_tl"]:.0f} | '
                f'{row["realization_percent"]} | {row["actual_unit"]:.0f} | {row["market_unit"]:.0f} | '
                f'{row["market_share_percent"] if row["market_share_percent"] is not None else "-"}'
            )
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
        commands = ["BT", "/F1 10 Tf", "48 790 Td", "14 TL"]
        for index, line in enumerate(escaped):
            if index:
                commands.append("T*")
            commands.append(f"({line}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode())
        pdf.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
        return BytesIO(bytes(pdf))
