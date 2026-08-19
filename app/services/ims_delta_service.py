"""Audit a staged IMS upload against the previous completed IMS without mutating live data.

Facts and upload-scoped master rows are compared by upload id. Targets are deliberately
period-scoped in the existing data model, so target deltas are compared by the current
and previous upload periods instead of assuming a non-existent Target.upload_id.
"""
from collections import defaultdict
from sqlalchemy import or_, desc
from app.models import IMSUpload, IMSRawData, IMSFact, Target, CompetitionData


def _previous_upload(upload):
    filters = [IMSUpload.status == "COMPLETED", IMSUpload.id != upload.id]
    if upload.week_number is None:
        period_filter = or_(
            IMSUpload.year < upload.year,
            (IMSUpload.year == upload.year) & (IMSUpload.month < upload.month),
        )
    else:
        period_filter = or_(
            IMSUpload.year < upload.year,
            (IMSUpload.year == upload.year) & (IMSUpload.month < upload.month),
            (IMSUpload.year == upload.year)
            & (IMSUpload.month == upload.month)
            & IMSUpload.week_number.isnot(None)
            & (IMSUpload.week_number < upload.week_number),
        )
    return (
        IMSUpload.query.filter(*filters, period_filter)
        .order_by(
            desc(IMSUpload.year),
            desc(IMSUpload.month),
            desc(IMSUpload.week_number),
            desc(IMSUpload.id),
        )
        .first()
    )


def _fact_map(upload_id):
    result = defaultdict(lambda: [0.0, 0.0])
    for row in IMSFact.query.filter_by(upload_id=upload_id).all():
        key = (row.representative_id, row.product_id)
        result[key][0] += float(row.unit or 0)
        result[key][1] += float(row.tl or 0)
    return dict(result)


def _target_map(year, month):
    """Read targets using their existing authoritative period identity."""
    return {
        (row.representative_id, row.product_id): (
            float(row.unit_target or 0),
            float(row.tl_target or 0),
        )
        for row in Target.query.filter_by(year=year, month=month).all()
    }


def _competition_count(upload_id):
    return CompetitionData.query.filter_by(upload_id=upload_id).count()


def _brick_map(upload_id):
    result = {}
    for row in IMSRawData.query.filter_by(
        upload_id=upload_id, sheet_type="official_brick_spread_master"
    ).all():
        # raw_json is intentionally part of the identity: official brick spread
        # metadata is side-channel master data and must never become a FACT.
        result[(row.representative, row.territory, row.raw_json)] = (
            float(row.unit or 0),
            float(row.tl or 0),
        )
    return result


def _changed(old, new, tolerance=0.000001):
    keys = set(old) | set(new)
    return [
        key
        for key in keys
        if key not in old
        or key not in new
        or any(abs(a - b) > tolerance for a, b in zip(old[key], new[key]))
    ]


def build_previous_ims_delta(importer):
    """Build a non-blocking audit delta before the transaction is published."""
    current = importer.upload
    previous = _previous_upload(current)
    current_competition = _competition_count(current.id)

    if previous is None:
        report = {
            "previous_upload_id": None,
            "baseline": False,
            "representatives_added": 0,
            "representatives_removed": 0,
            "products_added": 0,
            "products_removed": 0,
            "sales_changed": 0,
            "targets_changed": 0,
            "brick_spread_changed": 0,
            "competition_count_before": 0,
            "competition_count_after": current_competition,
            "competition_count_changed": current_competition != 0,
        }
    else:
        old_facts = _fact_map(previous.id)
        new_facts = _fact_map(current.id)
        old_keys, new_keys = set(old_facts), set(new_facts)
        old_reps, new_reps = {k[0] for k in old_keys}, {k[0] for k in new_keys}
        old_products, new_products = {k[1] for k in old_keys}, {k[1] for k in new_keys}
        old_competition = _competition_count(previous.id)
        report = {
            "previous_upload_id": previous.id,
            "baseline": True,
            "representatives_added": len(new_reps - old_reps),
            "representatives_removed": len(old_reps - new_reps),
            "products_added": len(new_products - old_products),
            "products_removed": len(old_products - new_products),
            "sales_changed": len(_changed(old_facts, new_facts)),
            "targets_changed": len(
                _changed(
                    _target_map(previous.year, previous.month),
                    _target_map(current.year, current.month),
                )
            ),
            "brick_spread_changed": len(
                _changed(_brick_map(previous.id), _brick_map(current.id))
            ),
            "competition_count_before": old_competition,
            "competition_count_after": current_competition,
            "competition_count_changed": old_competition != current_competition,
        }

    importer.previous_ims_delta = report
    importer.statistics["previous_ims_delta_changes"] = sum(
        report.get(key, 0)
        for key in (
            "representatives_added",
            "representatives_removed",
            "products_added",
            "products_removed",
            "sales_changed",
            "targets_changed",
            "brick_spread_changed",
        )
    )
    return report
