"""Audit a staged IMS upload against the previous completed IMS without mutating live data.

The delta is informational, never a publication failure by itself. Facts and upload-scoped
masters are compared by stable business grain. Period-scoped targets use a pre-import
snapshot for same-period reimports so a changed target in the new workbook is observable
without changing the existing target schema.
"""
from collections import defaultdict

from sqlalchemy import desc, or_

from app.models import CompetitionData, IMSFact, IMSRawData, IMSUpload, Target


DELTA_COMPETITION_STREAM_BATCH_SIZE = 5000


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


def _competition_business_key(row):
    (
        period_type,
        territory,
        subterritory,
        product_group,
        product_name,
        metric_type,
        is_subtotal,
        is_grand_total,
        _metric_value,
    ) = row
    return (
        period_type,
        territory,
        subterritory,
        product_group,
        product_name,
        metric_type,
        bool(is_subtotal),
        bool(is_grand_total),
    )


def _competition_map_from_rows(rows):
    """Aggregate scalar competition rows with the established delta business grain."""
    result = defaultdict(float)
    for row in rows:
        result[_competition_business_key(row)] += float(row[8] or 0)
    return {key: (value,) for key, value in result.items()}


def _competition_rows(upload_id):
    """Yield only scalar fields required by the competition delta audit."""
    return (
        CompetitionData.query.with_entities(
            CompetitionData.period_type,
            CompetitionData.territory,
            CompetitionData.subterritory,
            CompetitionData.product_group,
            CompetitionData.product_name,
            CompetitionData.metric_type,
            CompetitionData.is_subtotal,
            CompetitionData.is_grand_total,
            CompetitionData.metric_value,
        )
        .filter(CompetitionData.upload_id == upload_id)
        .yield_per(DELTA_COMPETITION_STREAM_BATCH_SIZE)
    )


def _competition_map(upload_id):
    """Preserve the established map helper without materializing ORM model objects."""
    return _competition_map_from_rows(_competition_rows(upload_id))


def _competition_delta_from_rows(old_rows, new_rows, tolerance=0.000001):
    """Compare two competition streams with one shared key table.

    Each side keeps its own floating-point accumulator, so duplicate-grain summation
    semantics stay identical to the historical two-map implementation.  A shared
    entry stores the business key once instead of building current-map, previous-map
    and their set union at the same time.
    """
    values = {}
    before = 0
    after = 0

    for row in old_rows:
        key = _competition_business_key(row)
        state = values.get(key)
        if state is None:
            # old_sum, new_sum, old_seen, new_seen
            state = [0.0, 0.0, True, False]
            values[key] = state
            before += 1
        elif not state[2]:
            state[2] = True
            before += 1
        state[0] += float(row[8] or 0)

    for row in new_rows:
        key = _competition_business_key(row)
        state = values.get(key)
        if state is None:
            state = [0.0, 0.0, False, True]
            values[key] = state
            after += 1
        elif not state[3]:
            state[3] = True
            after += 1
        state[1] += float(row[8] or 0)

    changed = 0
    for old_value, new_value, old_seen, new_seen in values.values():
        if not old_seen or not new_seen or abs(float(old_value) - float(new_value)) > tolerance:
            changed += 1

    return {
        "competition_changed": changed,
        "competition_count_before": before,
        "competition_count_after": after,
        "competition_count_changed": before != after,
    }


def _competition_delta(old_upload_id, new_upload_id):
    old_rows = () if old_upload_id is None else _competition_rows(old_upload_id)
    new_rows = () if new_upload_id is None else _competition_rows(new_upload_id)
    return _competition_delta_from_rows(old_rows, new_rows)


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
    current_targets = target_snapshot(current.year, current.month)
    competition_delta = _competition_delta(previous.id if previous is not None else None, current.id)

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
            "competition_count_before": competition_delta["competition_count_before"],
            "competition_count_after": competition_delta["competition_count_after"],
            "competition_count_changed": competition_delta["competition_count_changed"],
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
            **competition_delta,
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
