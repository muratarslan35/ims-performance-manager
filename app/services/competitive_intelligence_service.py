"""Real competitor movement alerts scoped to a representative's active bricks."""

from collections import defaultdict

from sqlalchemy import desc

from app.models import CompetitionData, IMSUpload, RepresentativeBrickAssignment
from app.services.alias_service import AliasService


class CompetitiveIntelligenceService:
    def __init__(self, representative_id, year, month):
        self.representative_id, self.year, self.month = int(representative_id), int(year), int(month)

    @staticmethod
    def _key(value):
        return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())

    @staticmethod
    def _shift(year, month, delta):
        ordinal = year * 12 + month - 1 + delta
        return ordinal // 12, ordinal % 12 + 1

    def _brick_keys(self):
        rows = RepresentativeBrickAssignment.query.filter_by(
            representative_id=self.representative_id, year=self.year, month=self.month, active=True
        ).all()
        return {self._key(row.brick) for row in rows if self._key(row.brick)}

    def _uploads(self, year, month, limit=2):
        return IMSUpload.query.filter_by(year=year, month=month, status="COMPLETED").order_by(
            desc(IMSUpload.completed_at), desc(IMSUpload.id)
        ).limit(limit).all()

    def _snapshot(self, upload_id, brick_keys):
        rows = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
        ).all()
        values = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        for row in rows:
            if self._key(row.subterritory) not in brick_keys:
                continue
            key = (str(row.subterritory).strip(), str(row.product_group).strip(), str(row.product_name).strip())
            side = "company" if row.is_company_product and not row.is_competitor else "competitor"
            values[key][side] += float(row.metric_value or 0)
        return values

    def build(self):
        bricks = self._brick_keys()
        uploads = self._uploads(self.year, self.month, 2)
        latest = self._snapshot(uploads[0].id, bricks) if uploads else {}
        previous = self._snapshot(uploads[1].id, bricks) if len(uploads) > 1 else {}
        weekly_alerts, own_gaps = [], []
        for key in set(latest) | set(previous):
            brick, group, product = key
            current = latest.get(key, {}).get("competitor", 0.0)
            before = previous.get(key, {}).get("competitor", 0.0)
            delta = current - before
            if current >= 50 and (before == 0 or delta >= 50 or current >= before * 1.5):
                weekly_alerts.append({
                    "brick": brick, "group": group, "product": product,
                    "previous_unit": round(before, 1), "current_unit": round(current, 1),
                    "delta_unit": round(delta, 1),
                    "severity": "critical" if before == 0 or delta >= 100 else "warning",
                })
        grouped = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        for (brick, group, _product), values in latest.items():
            grouped[(brick, group)]["company"] += values["company"]
            grouped[(brick, group)]["competitor"] += values["competitor"]
        for (brick, group), values in grouped.items():
            if values["company"] <= 0 and values["competitor"] > 0:
                own_gaps.append({"brick": brick, "group": group, "competitor_unit": round(values["competitor"], 1)})
        weekly_alerts.sort(key=lambda row: (row["severity"] != "critical", -row["delta_unit"], -row["current_unit"]))
        own_gaps.sort(key=lambda row: -row["competitor_unit"])

        monthly = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        for delta in range(-5, 1):
            year, month = self._shift(self.year, self.month, delta)
            period_uploads = self._uploads(year, month, 1)
            if not period_uploads:
                continue
            for (_brick, group, _product), values in self._snapshot(period_uploads[0].id, bricks).items():
                monthly[(group, year, month)]["company"] += values["company"]
                monthly[(group, year, month)]["competitor"] += values["competitor"]
        trends = []
        groups = sorted({key[0] for key in monthly})
        for group in groups:
            points = sorted((year, month, vals) for (name, year, month), vals in monthly.items() if name == group)
            if len(points) < 2:
                continue
            py, pm, prev = points[-2]; cy, cm, cur = points[-1]
            for side, label in (("company", "Kendi ürünümüz"), ("competitor", "Rakipler")):
                before, current = prev[side], cur[side]
                delta = current - before
                if abs(delta) < 1:
                    continue
                trends.append({"group": group, "side": label, "previous_period": f"{pm:02d}/{py}", "current_period": f"{cm:02d}/{cy}", "previous_unit": round(before,1), "current_unit": round(current,1), "delta_unit": round(delta,1), "change_percent": round(delta*100/before,1) if before else None})
        trends.sort(key=lambda row: -abs(row["delta_unit"]))
        return {"weekly_alerts": weekly_alerts[:10], "own_gaps": own_gaps[:10], "monthly_trends": trends[:12], "compared_uploads": [u.id for u in uploads]}
