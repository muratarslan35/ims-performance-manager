"""Audit a staged IMS upload against the previous completed IMS without mutating live data.

The delta is informational, never a publication failure by itself. Facts and upload-scoped
masters are compared by stable business grain. Period-scoped targets use a pre-import
snapshot for same-period reimports so a changed target in the new workbook is observable
without changing the existing target schema.
"""
from collections import defaultdict

from sqlalchemy import desc, or_

from app.models import CompetitionData, IMSFact, IMSRawData, IMSUpload, Target


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


def target_snapshot(year, month):
    """Return the authoritative period-scoped target state without mutating it."""
    return {
        (row.representative_id, row.product_id): (
            float(row.unit_target or 0),
            float(row.tl_target or 0),
        )
        for row in Target.query.filter_by(year=year, month=month).all()
    }


def _fact_map(upload_id):
    result = defaultdict(lambda: [0.0, 0.0])
    for row in IMSFact.query.filter_by(upload_id=upload_id).all():
        key = (row.representative_id, row.product_id)
        result[key][0] += float(row.unit or 0)
        result[key][1] += float(row.tl or 0)
    return dict(result)


def _representative_context_map(upload_id):
    """Compare representative/cadre geography independently from sales amounts."""
    result = defaultdict(set)
    rows = IMSRawData.query.filter(
        IMSRawData.upload_id == upload_id,
        IMSRawData.representative_id.isnot(None),
    ).all()
    for row in rows:
        # Brick spread is audited independently. Region/cadre identity here is
        # intentionally limited to stable organisational context.
        context = (
            str(row.territory or "").strip(),
            str(row.province or "").strip(),
            str(row.manager or "").strip(),
        )
        if any(context):
            result[row.representative_id].add(context)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def _competition_map(upload_id):
    """Compare competition values by business grain, not sheet title/position."""
    result = defaultdict(float)
    for row in CompetitionData.query.filter_by(upload_id=upload_id).all():
        key = (
            row.period_type,
            row.territory,
            row.subterritory,
            row.product_group,
            row.product_name,
            row.metric_type,
            bool(row.is_subtotal),
            bool(row.is_grand_total),
        )
        result[key] += float(row.metric_value or 0)
    return {key: (value,) for key, value in result.items()}


def _brick_map(upload_id):
    result = {}
    for row in IMSRawData.query.filter_by(
        upload_id=upload_id, sheet_type="official_brick_spread_master"
    ).all():
        # Metadata is source evidence only. The side-channel remains outside
        # FACT/SUMMARY and is compared independently from sales.
        key = (
            row.representative_id,
            row.representative,
            row.territory,
            row.product,
            row.raw_json,
        )
        result[key] = (float(row.unit or 0), float(row.tl or 0))
    return result


def _changed_numeric(old, new, tolerance=0.000001):
    keys = set(old) | set(new)
    return [
        key
        for key in keys
        if key not in old
        or key not in new
        or any(abs(float(a) - float(b)) > tolerance for a, b in zip(old[key], new[key]))
    ]


def _changed_exact(old, new):
    keys = set(old) | set(new)
    return [key for key in keys if key not in old or key not in new or old[key] != new[key]]


def build_previous_ims_delta(importer):
    """Build a complete non-blocking delta before the transaction is published."""
    current = importer.upload
    previous = _previous_upload(current)
    current_competition_map = _competition_map(current.id)
    current_targets = target_snapshot(current.year, current.month)

    if previous is None:
        report = {
            "previous_upload_id": None,
            "baseline": False,
            "representatives_added": 0,
            "representatives_removed": 0,
            "products_added": 0,
            "products_removed": 0,
            "region_cadre_changed": 0,
            "sales_changed": 0,
            "targets_changed": 0,
            "brick_spread_changed": 0,
            "competition_changed": 0,
            "competition_count_before": 0,
            "competition_count_after": len(current_competition_map),
            "competition_count_changed": bool(current_competition_map),
            "target_delta_basis": "FIRST_BASELINE",
        }
    else:
        old_facts = _fact_map(previous.id)
        new_facts = _fact_map(current.id)
        old_keys, new_keys = set(old_facts), set(new_facts)
        old_reps, new_reps = {key[0] for key in old_keys}, {key[0] for key in new_keys}
        old_products, new_products = {key[1] for key in old_keys}, {key[1] for key in new_keys}

        if previous.year == current.year and previous.month == current.month:
            old_targets = getattr(importer, "pre_import_target_snapshot", None)
            if old_targets is None:
                old_targets = current_targets
            target_basis = "PRE_IMPORT_SAME_PERIOD"
        else:
            old_targets = target_snapshot(previous.year, previous.month)
            target_basis = "PREVIOUS_PERIOD"

        old_competition_map = _competition_map(previous.id)
        old_context = _representative_context_map(previous.id)
        new_context = _representative_context_map(current.id)

        report = {
            "previous_upload_id": previous.id,
            "baseline": True,
            "representatives_added": len(new_reps - old_reps),
            "representatives_removed": len(old_reps - new_reps),
            "products_added": len(new_products - old_products),
            "products_removed": len(old_products - new_products),
            "region_cadre_changed": len(_changed_exact(old_context, new_context)),
            "sales_changed": len(_changed_numeric(old_facts, new_facts)),
            "targets_changed": len(_changed_numeric(old_targets, current_targets)),
            "brick_spread_changed": len(
                _changed_numeric(_brick_map(previous.id), _brick_map(current.id))
            ),
            "competition_changed": len(
                _changed_numeric(old_competition_map, current_competition_map)
            ),
            "competition_count_before": len(old_competition_map),
            "competition_count_after": len(current_competition_map),
            "competition_count_changed": len(old_competition_map) != len(current_competition_map),
            "target_delta_basis": target_basis,
        }

    importer.previous_ims_delta = report
    importer.statistics["previous_ims_delta_changes"] = sum(
        int(report.get(key, 0) or 0)
        for key in (
            "representatives_added",
            "representatives_removed",
            "products_added",
            "products_removed",
            "region_cadre_changed",
            "sales_changed",
            "targets_changed",
            "brick_spread_changed",
            "competition_changed",
        )
    )
    importer.statistics["previous_ims_region_cadre_changed"] = int(report.get("region_cadre_changed", 0) or 0)
    importer.statistics["previous_ims_competition_changed"] = int(report.get("competition_changed", 0) or 0)
    importer.statistics["previous_ims_targets_changed"] = int(report.get("targets_changed", 0) or 0)
    return report
