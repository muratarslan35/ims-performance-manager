"""Real competitor movement alerts scoped to a representative's active bricks."""

from __future__ import annotations

from collections import defaultdict
import hashlib

from sqlalchemy import and_, desc, func, or_

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product, RepresentativeBrickAssignment
from app.services.alias_service import AliasService
from app.services.representative_query_optimizer import install_representative_market_query_optimizer


# The representative route imports RepresentativeMarketService first and this
# service immediately afterwards. Installing here keeps the existing public
# service API intact while moving its expensive read paths to SQL scope.
install_representative_market_query_optimizer()


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

    @staticmethod
    def _label_candidates(values):
        candidates = set()
        for value in values or ():
            raw = str(value or "").strip()
            if not raw:
                continue
            normalized = str(AliasService.normalize(raw) or "").strip()
            candidates.add(raw)
            if normalized:
                candidates.add(normalized)
        return candidates

    def _brick_scope(self):
        rows = db.session.query(RepresentativeBrickAssignment.brick).filter(
            RepresentativeBrickAssignment.representative_id == self.representative_id,
            RepresentativeBrickAssignment.year == self.year,
            RepresentativeBrickAssignment.month == self.month,
            RepresentativeBrickAssignment.active.is_(True),
            RepresentativeBrickAssignment.brick.isnot(None),
        ).all()
        values = {str(brick).strip() for (brick,) in rows if str(brick or "").strip()}
        return values, {self._key(value) for value in values if self._key(value)}

    def _periods(self):
        return [self._shift(self.year, self.month, delta) for delta in range(-5, 1)]

    def _upload_plan(self):
        """Load six-month latest uploads plus current previous snapshot in one query."""
        periods = self._periods()
        filters = [and_(IMSUpload.year == year, IMSUpload.month == month) for year, month in periods]
        uploads = IMSUpload.query.filter(
            IMSUpload.status == "COMPLETED",
            or_(*filters),
        ).order_by(
            IMSUpload.year.desc(),
            IMSUpload.month.desc(),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        ).all()

        latest_by_period = {}
        current_uploads = []
        for upload in uploads:
            period = (int(upload.year), int(upload.month))
            latest_by_period.setdefault(period, upload)
            if period == (self.year, self.month) and len(current_uploads) < 2:
                current_uploads.append(upload)

        selected = {upload.id: upload for upload in latest_by_period.values()}
        for upload in current_uploads:
            selected[upload.id] = upload
        return periods, latest_by_period, current_uploads, selected

    def _scoped_aggregate_rows(self, upload_ids, brick_values, brick_keys):
        if not upload_ids or not brick_keys:
            return []
        brick_labels = self._label_candidates(brick_values)
        if not brick_labels:
            return []

        return db.session.query(
            CompetitionData.upload_id.label("upload_id"),
            CompetitionData.subterritory.label("subterritory"),
            CompetitionData.product_group.label("product_group"),
            CompetitionData.product_name.label("product_name"),
            func.sum(CompetitionData.metric_value).label("metric_value"),
        ).filter(
            CompetitionData.upload_id.in_(sorted(upload_ids)),
            CompetitionData.metric_type == "UNIT",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.subterritory.in_(sorted(brick_labels)),
        ).group_by(
            CompetitionData.upload_id,
            CompetitionData.subterritory,
            CompetitionData.product_group,
            CompetitionData.product_name,
        ).all()

    def _managed_product_for_row(self, row, products):
        group_key, product_key = self._key(row.product_group), self._key(row.product_name)
        for product in products:
            candidates = {
                self._key(product.product_name),
                self._key(product.product_code),
                self._key(product.ims_name),
                self._key(product.competitor_group),
            } - {""}
            if any(key in group_key or key in product_key for key in candidates):
                return product
        return None

    def _is_managed_product_name(self, product_name, product):
        product_key = self._key(product_name)
        own_keys = {
            self._key(product.product_name),
            self._key(product.product_code),
            self._key(product.ims_name),
        } - {""}
        return any(key in product_key or product_key in key for key in own_keys)

    def _build_from_plan(self, periods, latest_by_period, current_uploads, selected, brick_values, brick_keys):
        products = Product.query.filter_by(is_active=True).all()
        aggregate_rows = self._scoped_aggregate_rows(selected.keys(), brick_values, brick_keys)
        snapshots = defaultdict(lambda: defaultdict(lambda: {"company": 0.0, "competitor": 0.0}))

        for row in aggregate_rows:
            if self._key(row.subterritory) not in brick_keys:
                continue
            key = (
                str(row.subterritory).strip(),
                str(row.product_group).strip(),
                str(row.product_name).strip(),
            )
            managed_product = self._managed_product_for_row(row, products)
            side = (
                "company"
                if managed_product is not None and self._is_managed_product_name(row.product_name, managed_product)
                else "competitor"
            )
            snapshots[int(row.upload_id)][key][side] += float(row.metric_value or 0.0)

        latest_id = current_uploads[0].id if current_uploads else None
        previous_id = current_uploads[1].id if len(current_uploads) > 1 else None
        latest = snapshots.get(latest_id, {}) if latest_id is not None else {}
        previous = snapshots.get(previous_id, {}) if previous_id is not None else {}

        weekly_alerts, own_gaps = [], []
        for key in set(latest) | set(previous):
            brick, group, product = key
            current = latest.get(key, {}).get("competitor", 0.0)
            before = previous.get(key, {}).get("competitor", 0.0)
            delta = current - before
            if current >= 50 and (before == 0 or delta >= 50 or current >= before * 1.5):
                weekly_alerts.append({
                    "brick": brick,
                    "group": group,
                    "product": product,
                    "previous_unit": round(before, 1),
                    "current_unit": round(current, 1),
                    "delta_unit": round(delta, 1),
                    "severity": "critical" if before == 0 or delta >= 100 else "warning",
                })

        grouped = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        for (brick, group, _product), values in latest.items():
            grouped[(brick, group)]["company"] += values["company"]
            grouped[(brick, group)]["competitor"] += values["competitor"]
        for (brick, group), values in grouped.items():
            if values["company"] <= 0 and values["competitor"] > 0:
                own_gaps.append({
                    "brick": brick,
                    "group": group,
                    "competitor_unit": round(values["competitor"], 1),
                })

        weekly_alerts.sort(key=lambda row: (row["severity"] != "critical", -row["delta_unit"], -row["current_unit"]))
        own_gaps.sort(key=lambda row: -row["competitor_unit"])

        monthly = defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        for year, month in periods:
            upload = latest_by_period.get((year, month))
            if upload is None:
                continue
            for (_brick, group, _product), values in snapshots.get(upload.id, {}).items():
                monthly[(group, year, month)]["company"] += values["company"]
                monthly[(group, year, month)]["competitor"] += values["competitor"]

        trends = []
        groups = sorted({key[0] for key in monthly})
        for group in groups:
            points = sorted(
                (year, month, vals)
                for (name, year, month), vals in monthly.items()
                if name == group
            )
            if len(points) < 2:
                continue
            py, pm, prev = points[-2]
            cy, cm, cur = points[-1]
            for side, label in (("company", "Kendi ürünümüz"), ("competitor", "Rakipler")):
                before, current = prev[side], cur[side]
                delta = current - before
                if abs(delta) < 1:
                    continue
                trends.append({
                    "group": group,
                    "side": label,
                    "previous_period": f"{pm:02d}/{py}",
                    "current_period": f"{cm:02d}/{cy}",
                    "previous_unit": round(before, 1),
                    "current_unit": round(current, 1),
                    "delta_unit": round(delta, 1),
                    "change_percent": round(delta * 100 / before, 1) if before else None,
                })
        trends.sort(key=lambda row: -abs(row["delta_unit"]))
        return {
            "weekly_alerts": weekly_alerts[:10],
            "own_gaps": own_gaps[:10],
            "monthly_trends": trends[:12],
            "compared_uploads": [upload.id for upload in current_uploads],
        }

    def build(self):
        brick_values, brick_keys = self._brick_scope()
        periods, latest_by_period, current_uploads, selected = self._upload_plan()
        upload_signature = "-".join(str(upload_id) for upload_id in sorted(selected)) or "none"
        brick_signature = "-".join(sorted(brick_keys))
        scope_digest = hashlib.sha1(brick_signature.encode("utf-8")).hexdigest()[:16]
        cache_key = (
            f"rep-intelligence:{self.representative_id}:{self.year}:{self.month}:"
            f"{upload_signature}:{scope_digest}"
        )
        return RepresentativeAnalysisCache.get_or_compute(
            cache_key,
            lambda: self._build_from_plan(
                periods, latest_by_period, current_uploads, selected, brick_values, brick_keys
            ),
            ttl_seconds=60,
        )
