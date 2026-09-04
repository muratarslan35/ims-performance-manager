"""Runtime optimizer for dashboard competition lookups.

The dashboard previously discovered the latest usable competition upload with a
JOIN + GROUP BY over ``ims_competition_data``. As the table grows into millions
of rows that discovery becomes proportional to historical data volume and is
executed more than once during one cold dashboard render.

The implementation changes only the access path and preserves business rules.
"""
from __future__ import annotations

from sqlalchemy import desc, exists

from app.models import CompetitionData, IMSUpload


def install_dashboard_runtime_optimizer() -> None:
    """Install the bounded dashboard lookup and targeted field-read repair."""
    from app.query.dashboard_query import DashboardQuery
    from app.services.period_price_read_guard import install_period_price_read_guard
    from app.services.week8_read_path_repair import install_week8_read_path_repair

    if not getattr(DashboardQuery, "_bounded_competition_lookup_installed", False):
        original = DashboardQuery._latest_competition_upload_id

        def bounded_latest_competition_upload_id(self, filters):
            if not filters or filters.year is None or filters.month is None:
                return None

            cache = getattr(self, "_latest_competition_upload_cache", None)
            if cache is None:
                cache = {}
                self._latest_competition_upload_cache = cache

            key = (int(filters.year), int(filters.month))
            if key in cache:
                return cache[key]

            has_real_tl = exists().where(
                CompetitionData.upload_id == IMSUpload.id,
                CompetitionData.metric_type == "TL",
                CompetitionData.metric_value != 0,
            )
            upload_id = (
                self.session.query(IMSUpload.id)
                .filter(
                    IMSUpload.year == key[0],
                    IMSUpload.month == key[1],
                    IMSUpload.status == "COMPLETED",
                    has_real_tl,
                )
                .order_by(
                    desc(IMSUpload.week_number),
                    desc(IMSUpload.completed_at),
                    desc(IMSUpload.id),
                )
                .limit(1)
                .scalar()
            )
            cache[key] = upload_id
            return upload_id

        DashboardQuery._original_latest_competition_upload_id = original
        DashboardQuery._latest_competition_upload_id = bounded_latest_competition_upload_id
        DashboardQuery._bounded_competition_lookup_installed = True

    install_week8_read_path_repair()
    # Week-8 keeps its source-selection behavior, but the final TL->box repair
    # must use the price frozen for the requested IMS month rather than today's
    # mutable product master price.
    install_period_price_read_guard()
