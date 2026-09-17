"""Representative competitor movement signals scoped to active bricks."""

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
    """Build only the four representative AI-panel signal families.

    The service intentionally keeps one scoped aggregate query. Historical work
    is limited to the first available IMS cut of the latest four months so the
    panel can spot repeatable early-month competitor behaviour without restoring
    the older broad monthly AI cards.
    """

    HISTORY_MONTHS = 4
    SYNTHETIC_MARKET_TOKENS = (
        "EKIP 4", "EKİP 4", "EKIP4", "EKİP4", "TOPLAM PAZAR",
        "TOTAL MARKET", "GRAND TOTAL", "SUBTOTAL",
    )

    def __init__(self, representative_id, year, month):
        self.representative_id, self.year, self.month = (
            int(representative_id),
            int(year),
            int(month),
        )

    @staticmethod
    def _key(value):
        return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())

    @staticmethod
    def _shift(year, month, delta):
        ordinal = year * 12 + month - 1 + delta
        return ordinal // 12, ordinal % 12 + 1

    @classmethod
    def _is_synthetic_market_values(cls, *values):
        haystack = " ".join(str(value or "").upper() for value in values)
        return any(token in haystack for token in cls.SYNTHETIC_MARKET_TOKENS)

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
        values = {
            str(brick).strip()
            for (brick,) in rows
            if str(brick or "").strip()
        }
        return values, {self._key(value) for value in values if self._key(value)}

    def _periods(self):
        return [
            self._shift(self.year, self.month, delta)
            for delta in range(-(self.HISTORY_MONTHS - 1), 1)
        ]

    def _upload_plan(self):
        """Load recent uploads once and select only early-month + current cuts."""
        periods = self._periods()
        filters = [
            and_(IMSUpload.year == year, IMSUpload.month == month)
            for year, month in periods
        ]
        uploads = IMSUpload.query.filter(
            IMSUpload.status == "COMPLETED",
            or_(*filters),
        ).order_by(
            IMSUpload.year.desc(),
            IMSUpload.month.desc(),
            desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        ).all()

        by_period = defaultdict(list)
        current_uploads = []
        for upload in uploads:
            period = (int(upload.year), int(upload.month))
            by_period[period].append(upload)
            if period == (self.year, self.month) and len(current_uploads) < 2:
                current_uploads.append(upload)

        early_by_period = {}
        for period, period_uploads in by_period.items():
            # week_number is the business cut carried by the IMS import. Lowest
            # week inside that month is the earliest available monthly cut.
            early_by_period[period] = min(
                period_uploads,
                key=lambda upload: (
                    int(upload.week_number)
                    if upload.week_number is not None
                    else 10**9,
                    int(upload.id),
                ),
            )

        selected = {upload.id: upload for upload in early_by_period.values()}
        for upload in current_uploads:
            selected[upload.id] = upload
        return periods, early_by_period, current_uploads, selected

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

    @staticmethod
    def _pattern_detail(pattern):
        return (
            f"Son {pattern['observed_months']} ayın ilk IMS kesitinde "
            f"{pattern['hit_months']} kez görüldü; "
            f"ortalama {pattern['average_unit']:,.0f} kutu "
            f"(min {pattern['min_unit']:,.0f} / max {pattern['max_unit']:,.0f})."
        )

    def _build_from_plan(
        self,
        periods,
        early_by_period,
        current_uploads,
        selected,
        brick_values,
        brick_keys,
    ):
        products = Product.query.filter_by(is_active=True).all()
        aggregate_rows = self._scoped_aggregate_rows(
            selected.keys(), brick_values, brick_keys
        )
        snapshots = defaultdict(
            lambda: defaultdict(lambda: {"company": 0.0, "competitor": 0.0})
        )

        for row in aggregate_rows:
            if self._key(row.subterritory) not in brick_keys:
                continue
            if self._is_synthetic_market_values(
                row.subterritory, row.product_group, row.product_name
            ):
                continue
            key = (
                str(row.subterritory).strip(),
                str(row.product_group).strip(),
                str(row.product_name).strip(),
            )
            managed_product = self._managed_product_for_row(row, products)
            side = (
                "company"
                if managed_product is not None
                and self._is_managed_product_name(row.product_name, managed_product)
                else "competitor"
            )
            snapshots[int(row.upload_id)][key][side] += float(row.metric_value or 0.0)

        latest_id = current_uploads[0].id if current_uploads else None
        previous_id = current_uploads[1].id if len(current_uploads) > 1 else None
        latest = snapshots.get(latest_id, {}) if latest_id is not None else {}
        previous = snapshots.get(previous_id, {}) if previous_id is not None else {}

        weekly_alerts = []
        for key in set(latest) | set(previous):
            brick, group, product = key
            current = latest.get(key, {}).get("competitor", 0.0)
            before = previous.get(key, {}).get("competitor", 0.0)
            delta = current - before
            if current >= 50 and (
                before == 0 or delta >= 50 or current >= before * 1.5
            ):
                weekly_alerts.append(
                    {
                        "brick": brick,
                        "group": group,
                        "product": product,
                        "previous_unit": round(before, 1),
                        "current_unit": round(current, 1),
                        "delta_unit": round(delta, 1),
                        "severity": "critical"
                        if before == 0 or delta >= 100
                        else "warning",
                    }
                )

        weekly_alerts.sort(
            key=lambda row: (
                row["severity"] != "critical",
                -row["delta_unit"],
                -row["current_unit"],
            )
        )
        weekly_alerts = weekly_alerts[:10]

        # Early-month analysis reuses the same aggregate query. The earliest
        # available IMS cut of each month is compared across at most four
        # months; no extra brick or month query is issued.
        available_periods = [
            period for period in periods if early_by_period.get(period) is not None
        ]
        available_early_months = len(available_periods)
        all_early_keys = set()
        for period in available_periods:
            upload = early_by_period[period]
            all_early_keys.update(snapshots.get(upload.id, {}).keys())

        early_patterns = []
        emerging = []
        weekly_pairs = {
            (self._key(row["brick"]), self._key(row["product"]))
            for row in weekly_alerts
        }

        for brick, group, product in all_early_keys:
            points = []
            for year, month in available_periods:
                upload = early_by_period[(year, month)]
                competitor = float(
                    snapshots.get(upload.id, {})
                    .get((brick, group, product), {})
                    .get("competitor", 0.0)
                )
                points.append((year, month, competitor))

            nonzero = [value for _year, _month, value in points if value > 0]
            if len(nonzero) >= 2:
                average = sum(nonzero) / len(nonzero)
                if average >= 20:
                    early_patterns.append(
                        {
                            "brick": brick,
                            "group": group,
                            "product": product,
                            "hit_months": len(nonzero),
                            "observed_months": available_early_months,
                            "average_unit": round(average, 1),
                            "min_unit": round(min(nonzero), 1),
                            "max_unit": round(max(nonzero), 1),
                            "latest_unit": round(points[-1][2], 1),
                            "periods": [
                                f"{month:02d}/{year}"
                                for year, month, value in points
                                if value > 0
                            ],
                        }
                    )

            if len(points) >= 2:
                latest_unit = points[-1][2]
                previous_values = [value for _y, _m, value in points[:-1]]
                previous_average = (
                    sum(previous_values) / len(previous_values)
                    if previous_values
                    else 0.0
                )
                delta = latest_unit - previous_average
                pair = (self._key(brick), self._key(product))
                is_new = previous_average <= 0 and latest_unit >= 50
                is_accelerating = (
                    previous_average > 0
                    and latest_unit >= previous_average * 1.5
                    and delta >= 50
                )
                if pair not in weekly_pairs and (is_new or is_accelerating):
                    emerging.append(
                        {
                            "brick": brick,
                            "group": group,
                            "product": product,
                            "latest_unit": round(latest_unit, 1),
                            "previous_average_unit": round(previous_average, 1),
                            "delta_unit": round(delta, 1),
                            "signal": "Yeni" if is_new else "Hızlanıyor",
                        }
                    )

        early_patterns.sort(
            key=lambda row: (
                -row["hit_months"],
                -row["average_unit"],
                row["brick"],
                row["product"],
            )
        )

        # Keep the two lower cards to 5–7 distinct observations in total.
        recurring_limit = min(4, len(early_patterns))
        recurring = early_patterns[:recurring_limit]
        recurring_pairs = {
            (self._key(row["brick"]), self._key(row["product"]))
            for row in recurring
        }
        emerging = [
            row
            for row in emerging
            if (self._key(row["brick"]), self._key(row["product"]))
            not in recurring_pairs
        ]
        emerging.sort(
            key=lambda row: (
                -row["delta_unit"],
                -row["latest_unit"],
                row["brick"],
                row["product"],
            )
        )
        emerging_limit = max(0, 7 - len(recurring))
        emerging = emerging[:emerging_limit]

        return {
            "weekly_alerts": weekly_alerts,
            # Compatibility keys stay empty because the duplicate legacy cards
            # are intentionally removed from the representative AI screen.
            "own_gaps": [],
            "monthly_trends": [],
            "early_month_patterns": recurring,
            "early_month_emerging": emerging,
            "compared_uploads": [upload.id for upload in current_uploads],
        }

    def build(self):
        brick_values, brick_keys = self._brick_scope()
        periods, early_by_period, current_uploads, selected = self._upload_plan()
        upload_signature = (
            "-".join(str(upload_id) for upload_id in sorted(selected)) or "none"
        )
        brick_signature = "-".join(sorted(brick_keys))
        scope_digest = hashlib.sha1(brick_signature.encode("utf-8")).hexdigest()[:16]
        cache_key = (
            f"rep-intelligence:{self.representative_id}:{self.year}:{self.month}:"
            f"{upload_signature}:{scope_digest}:focus-v2"
        )
        return RepresentativeAnalysisCache.get_or_compute(
            cache_key,
            lambda: self._build_from_plan(
                periods,
                early_by_period,
                current_uploads,
                selected,
                brick_values,
                brick_keys,
            ),
            ttl_seconds=60,
        )
