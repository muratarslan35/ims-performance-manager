"""Runtime optimizer for dashboard competition lookups.

The dashboard previously discovered the latest usable competition upload with a
JOIN + GROUP BY over ``ims_competition_data``. As the table grows into millions
of rows that discovery becomes proportional to historical data volume and is
executed more than once during one cold dashboard render.

This installer preserves the existing business rule exactly:
- same requested year/month,
- COMPLETED upload only,
- newest week/completion/id wins,
- upload must contain at least one non-zero TL competition row.

The implementation changes only the access path: a correlated EXISTS probe uses
the existing upload/metric index and stops on the first qualifying row. The
resolved upload id is memoized per DashboardQuery instance so one dashboard
request performs the lookup only once.
"""
from __future__ import annotations

from sqlalchemy import desc, exists

from app.models import CompetitionData, IMSUpload


def install_dashboard_runtime_optimizer() -> None:
    """Install the bounded dashboard lookup and targeted field-read repair."""
    from app.query.dashboard_query import DashboardQuery
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

    # Do not reinstall the broad PR-285 field monkeypatches. The representative
    # SQL-scope optimizer remains installed by CompetitiveIntelligenceService;
    # this repair changes only the proven Week-8 source-selection regressions.
    install_week8_read_path_repair()
