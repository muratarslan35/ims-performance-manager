"""Re-import the current production IMS workbook into an isolated DB copy and prove business fingerprints are unchanged.

The script is designed for deployment gates. DATABASE_URL must point to a copied
SQLite database, never the live file. The source workbook is selected from the
latest COMPLETED IMSUpload, so no workbook filename or sheet layout is hardcoded.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import (
    CompetitionData,
    IMSFact,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Target,
)
from app.services.ims_import_service import IMSImportService
from config import Config


EXCLUDED_COLUMNS = {
    "id", "upload_id", "raw_data_id", "created_at", "updated_at",
    "uploaded_at", "completed_at",
}
BLOCKING_STATS = (
    "unclassified_sheet", "unclassified_master_cell", "unresolved_representative",
    "unresolved_product", "invalid_metric", "row_error", "conflicting_match",
    "duplicate_conflict",
)
REQUIRED_IMPORT_STAGES = (
    "validate_and_load_workbook",
    "discover_and_prepare_sheets",
    "stage_raw_rows",
    "assignments_and_targets",
    "facts_summary_and_official_aggregates",
    "competition_import",
    "source_reconciliation",
    "commit_upload",
)


class AcceptanceConfig(Config):
    """Use the copied IMS DB while disabling startup mutations/user-vault reconciliation."""
    TESTING = True
    USER_VAULT_PATH = Path("/tmp/ims-acceptance-users-disabled.db")


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return format(value, ".12g")
    return value


def _rows(model, query, extra_excluded=()):
    excluded = EXCLUDED_COLUMNS | set(extra_excluded)
    columns = [column.name for column in model.__table__.columns if column.name not in excluded]
    result = []
    for row in query.all():
        result.append({name: _json_value(getattr(row, name)) for name in columns})
    return result


def _fingerprint(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sorted_rows(rows):
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))


def _period_query(model, upload):
    return model.query.filter_by(year=upload.year, month=upload.month)


def _competition_semantic_rows(query, upload=None):
    """Canonical business totals independent of physical source row/grain labels."""
    grouped = {}
    for row in query.all():
        scoped_year = upload.year if upload is not None else row.year
        scoped_month = upload.month if upload is not None else row.month
        scoped_week = (
            upload.week_number if upload is not None and row.period_type == "weekly"
            else (None if upload is not None else row.week_number)
        )
        key = (
            row.period_type, scoped_year, scoped_month, scoped_week,
            row.territory, row.product_group, row.product_name, row.metric_type,
            bool(row.is_subtotal), bool(row.is_grand_total),
        )
        grouped[key] = grouped.get(key, Decimal("0")) + Decimal(str(row.metric_value))
    return _sorted_rows([
        {
            "period_type": key[0], "year": key[1], "month": key[2],
            "week_number": key[3], "territory": key[4],
            "product_group": key[5], "product_name": key[6],
            "metric_type": key[7], "is_subtotal": key[8],
            "is_grand_total": key[9], "metric_total": str(value),
        }
        for key, value in grouped.items()
    ])


def _competition_diagnostics(query, upload=None):
    """Read-only migration diagnostics at progressively stable business grains."""
    rows = query.all()
    variants = {
        "without_territory": lambda row: (
            row.period_type, upload.year if upload else row.year,
            upload.month if upload else row.month,
            row.product_group, row.product_name, row.metric_type,
            bool(row.is_subtotal), bool(row.is_grand_total),
        ),
        "without_period": lambda row: (
            row.territory, row.product_group, row.product_name, row.metric_type,
            bool(row.is_subtotal), bool(row.is_grand_total),
        ),
        "product_metric": lambda row: (
            row.product_group, row.product_name, row.metric_type,
            bool(row.is_subtotal), bool(row.is_grand_total),
        ),
        "metric": lambda row: (row.metric_type,),
    }
    result = {}
    for name, key_fn in variants.items():
        grouped = {}
        for row in rows:
            key = key_fn(row)
            grouped[key] = grouped.get(key, Decimal("0")) + Decimal(str(row.metric_value))
        canonical = _sorted_rows([
            {"key": list(key), "metric_total": str(value)}
            for key, value in grouped.items()
        ])
        result[name] = {"count": len(canonical), "sha256": _fingerprint(canonical)}
        if name in {"product_metric", "metric"}:
            result[name]["entries"] = canonical
    return result


def _grouped_competition_snapshot(grouped, include_entries=False):
    canonical = _sorted_rows([
        {"key": list(key), "metric_total": str(value)}
        for key, value in grouped.items()
    ])
    result = {"count": len(canonical), "sha256": _fingerprint(canonical)}
    if include_entries:
        result["entries"] = canonical
    return result


def _streaming_competition_snapshot(upload):
    """Fingerprint one upload in one bounded streaming pass.

    The previous acceptance path materialized the same large competition upload
    three times through the ORM.  On the two-core production host this consumed
    the entire deployment timeout after a successful import.  This pass retains
    exact physical per-sheet evidence plus every semantic diagnostic grain while
    keeping only compact aggregate dictionaries in memory.
    """
    excluded = EXCLUDED_COLUMNS
    columns = [
        column for column in CompetitionData.__table__.columns
        if column.name not in excluded
    ]
    names = [column.name for column in columns]
    query = (
        db.session.query(*(getattr(CompetitionData, name) for name in names))
        .filter(CompetitionData.upload_id == upload.id)
        .order_by(*(getattr(CompetitionData, name) for name in names))
        .yield_per(5000)
    )

    physical = hashlib.sha256()
    sheet_hashers = {}
    sheet_semantic = {}
    sheet_without_period = {}
    semantic = {}
    diagnostics = {
        "without_territory": {},
        "without_period": {},
        "product_metric": {},
        "metric": {},
    }
    count = 0
    for values in query:
        row = {name: _json_value(value) for name, value in zip(names, values)}
        encoded = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8") + b"\n"
        physical.update(encoded)
        sheet_name = str(row.get("sheet_name") or "")
        sheet_state = sheet_hashers.setdefault(
            sheet_name, {"count": 0, "hasher": hashlib.sha256()}
        )
        sheet_state["count"] += 1
        sheet_state["hasher"].update(encoded)
        count += 1

        period_type = row.get("period_type")
        scoped_week = upload.week_number if period_type == "weekly" else None
        metric_value = Decimal(str(row.get("metric_value") or 0))
        semantic_key = (
            period_type, upload.year, upload.month, scoped_week,
            row.get("territory"), row.get("product_group"), row.get("product_name"),
            row.get("metric_type"), bool(row.get("is_subtotal")),
            bool(row.get("is_grand_total")),
        )
        semantic[semantic_key] = semantic.get(semantic_key, Decimal("0")) + metric_value
        sheet_grouped = sheet_semantic.setdefault(sheet_name, {})
        sheet_grouped[semantic_key] = (
            sheet_grouped.get(semantic_key, Decimal("0")) + metric_value
        )
        diagnostic_keys = {
            "without_territory": (
                period_type, upload.year, upload.month, row.get("product_group"),
                row.get("product_name"), row.get("metric_type"),
                bool(row.get("is_subtotal")), bool(row.get("is_grand_total")),
            ),
            "without_period": (
                row.get("territory"), row.get("product_group"), row.get("product_name"),
                row.get("metric_type"), bool(row.get("is_subtotal")),
                bool(row.get("is_grand_total")),
            ),
            "product_metric": (
                row.get("product_group"), row.get("product_name"), row.get("metric_type"),
                bool(row.get("is_subtotal")), bool(row.get("is_grand_total")),
            ),
            "metric": (row.get("metric_type"),),
        }
        for grain, key in diagnostic_keys.items():
            grouped = diagnostics[grain]
            grouped[key] = grouped.get(key, Decimal("0")) + metric_value
        stable_sheet_key = diagnostic_keys["without_period"]
        stable_sheet_grouped = sheet_without_period.setdefault(sheet_name, {})
        stable_sheet_grouped[stable_sheet_key] = (
            stable_sheet_grouped.get(stable_sheet_key, Decimal("0")) + metric_value
        )

    return {
        "physical": {"count": count, "sha256": physical.hexdigest()},
        "sheets": {
            sheet: {"count": state["count"], "sha256": state["hasher"].hexdigest()}
            for sheet, state in sorted(sheet_hashers.items())
        },
        "sheet_semantic": {
            sheet: _grouped_competition_snapshot(grouped)
            for sheet, grouped in sorted(sheet_semantic.items())
        },
        "sheet_without_period": {
            sheet: _grouped_competition_snapshot(grouped)
            for sheet, grouped in sorted(sheet_without_period.items())
        },
        "semantic": _grouped_competition_snapshot(semantic),
        "diagnostics": {
            grain: _grouped_competition_snapshot(
                grouped, include_entries=grain in {"product_metric", "metric"}
            )
            for grain, grouped in diagnostics.items()
        },
    }


def _snapshot(upload):
    # FACT rows are versioned by upload_id. Comparing the whole month would
    # incorrectly mix baseline and acceptance uploads in the isolated DB and
    # produce a false fingerprint mismatch after a successful re-import.
    facts = _sorted_rows(_rows(IMSFact, IMSFact.query.filter_by(upload_id=upload.id)))
    # Summary and Target are intentionally period-scoped in the existing
    # production model, so they continue to be compared by year/month.
    summaries = _sorted_rows(_rows(IMSSummary, _period_query(IMSSummary, upload)))
    targets = _sorted_rows(_rows(Target, _period_query(Target, upload)))
    competition = _streaming_competition_snapshot(upload)
    spread = _sorted_rows(_rows(
        IMSRawData,
        IMSRawData.query.filter_by(upload_id=upload.id, sheet_type="official_brick_spread_master"),
    ))
    official_aggregates = _sorted_rows(_rows(
        IMSRawData,
        IMSRawData.query.filter(
            IMSRawData.upload_id == upload.id,
            IMSRawData.sheet_type.in_(("official_target_aggregate", "official_actual_aggregate")),
        ),
        extra_excluded=("sheet_name", "source_row", "raw_json"),
    ))
    return {
        "fact": {"count": len(facts), "sha256": _fingerprint(facts)},
        "summary": {"count": len(summaries), "sha256": _fingerprint(summaries)},
        "target": {"count": len(targets), "sha256": _fingerprint(targets)},
        "competition": competition["physical"],
        "competition_sheets": competition["sheets"],
        "competition_sheet_semantic": competition["sheet_semantic"],
        "competition_sheet_without_period": competition["sheet_without_period"],
        "competition_semantic": competition["semantic"],
        "competition_diagnostics": competition["diagnostics"],
        "official_brick_spread": {"count": len(spread), "sha256": _fingerprint(spread)},
        "official_aggregates": {"count": len(official_aggregates), "sha256": _fingerprint(official_aggregates)},
        "summary_unit": sum(float(row.unit or 0) for row in _period_query(IMSSummary, upload).all()),
        "summary_tl": sum(float(row.tl or 0) for row in _period_query(IMSSummary, upload).all()),
        "target_unit": sum(float(row.unit_target or 0) for row in _period_query(Target, upload).all()),
        "target_tl": sum(float(row.tl_target or 0) for row in _period_query(Target, upload).all()),
    }


def _competition_delta(before, after, limit=30):
    """Return bounded product/metric evidence without weakening acceptance."""
    result = {}
    for grain in ("product_metric", "metric"):
        before_rows = {
            json.dumps(row["key"], ensure_ascii=False, sort_keys=True): Decimal(row["metric_total"])
            for row in before[grain].get("entries", [])
        }
        after_rows = {
            json.dumps(row["key"], ensure_ascii=False, sort_keys=True): Decimal(row["metric_total"])
            for row in after[grain].get("entries", [])
        }
        keys = sorted(set(before_rows) | set(after_rows))
        changes = []
        for key in keys:
            old = before_rows.get(key)
            new = after_rows.get(key)
            if old == new:
                continue
            changes.append({
                "key": json.loads(key), "before": None if old is None else str(old),
                "after": None if new is None else str(new),
                "delta": str((new or Decimal("0")) - (old or Decimal("0"))),
            })
        result[grain] = changes[:limit]
    return result


def _validate_competition_coverage(before, after, manifest_names):
    """Preserve every baseline sheet while permitting proven metadata fixes.

    A source sheet may change its physical fingerprint only when its row count
    and territory/product/metric totals (the stable business grain) remain
    identical.  This permits correcting metadata such as the historical
    MONTHLY -> WEEKLY classification on TTS REKABET without accepting any loss
    or movement of business values.
    """
    before_sheets = before["competition_sheets"]
    after_sheets = after["competition_sheets"]
    missing = sorted(set(before_sheets) - set(after_sheets))
    unmanifested = sorted(set(after_sheets) - set(manifest_names))
    changed = []
    migrated_grain = []
    for sheet in sorted(set(before_sheets) & set(after_sheets)):
        if before_sheets[sheet] == after_sheets[sheet]:
            continue
        changed.append(sheet)
        count_equal = before_sheets[sheet]["count"] == after_sheets[sheet]["count"]
        stable_equal = (
            before["competition_sheet_without_period"].get(sheet)
            == after["competition_sheet_without_period"].get(sheet)
        )
        if count_equal and stable_equal:
            migrated_grain.append(sheet)

    unsafe_changed = sorted(set(changed) - set(migrated_grain))
    if missing or unsafe_changed or unmanifested:
        raise AssertionError(
            "Competition kaynak sheet koruması başarısız: "
            f"missing={missing}, changed={unsafe_changed}, "
            f"unmanifested={unmanifested}"
        )
    if after["competition"]["count"] < before["competition"]["count"]:
        raise AssertionError(
            "Competition kapsamı azaldı: "
            f"before={before['competition']['count']}, after={after['competition']['count']}"
        )
    return {
        "baseline_sheet_count": len(before_sheets),
        "new_sheets": sorted(set(after_sheets) - set(before_sheets)),
        "metadata_migrated_sheets": migrated_grain,
    }


def _source_path(app, upload):
    upload_folder = Path(app.config["UPLOAD_FOLDER"])
    direct = upload_folder / upload.file_name
    if direct.is_file():
        return direct
    normalized = upload.file_name.casefold()
    matches = [path for path in upload_folder.glob("*") if path.is_file() and path.name.casefold() == normalized]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        f"Acceptance workbook bulunamadı: upload_id={upload.id}, file={upload.file_name}, folder={upload_folder}"
    )


def _assert_equal(label, before, after):
    if before != after:
        raise AssertionError(f"{label} fingerprint/count değişti: before={before}, after={after}")


def main():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("verify_ims_acceptance yalnız izole SQLite kopyası üzerinde çalıştırılmalıdır.")
    db_path = Path(database_url.removeprefix("sqlite:///"))
    if not db_path.name.startswith("ims-acceptance-"):
        raise RuntimeError(f"Canlı DB üzerinde acceptance çalıştırma engellendi: {db_path}")

    app = create_app(AcceptanceConfig)
    with app.app_context():
        requested_id = os.environ.get("IMS_ACCEPTANCE_UPLOAD_ID")
        query = IMSUpload.query.filter_by(status="COMPLETED")
        baseline_upload = (
            query.filter_by(id=int(requested_id)).first()
            if requested_id
            else query.order_by(IMSUpload.completed_at.desc(), IMSUpload.id.desc()).first()
        )
        if baseline_upload is None:
            raise RuntimeError("Acceptance için COMPLETED IMS upload bulunamadı.")

        source = _source_path(app, baseline_upload)
        stage_started = time.monotonic()
        before = _snapshot(baseline_upload)
        before_snapshot_seconds = time.monotonic() - stage_started
        print(
            "IMS_ACCEPTANCE_STAGE|"
            + json.dumps({"stage": "baseline_snapshot", "seconds": round(before_snapshot_seconds, 4)})
        )
        baseline_counters = {
            "upload_id": baseline_upload.id,
            "file_name": baseline_upload.file_name,
            "year": baseline_upload.year,
            "month": baseline_upload.month,
            "week_number": baseline_upload.week_number,
            "sheet_count": baseline_upload.sheet_count,
            "source_record_count": baseline_upload.source_record_count,
            "stored_source_record_count": baseline_upload.stored_source_record_count,
            "invalid_metric_count": baseline_upload.invalid_metric_count,
            "reconciliation_status": baseline_upload.reconciliation_status,
        }

        stage_started = time.monotonic()
        result = IMSImportService(str(source), uploaded_by="DEPLOY_ACCEPTANCE").run(
            baseline_upload.year,
            baseline_upload.month,
            clear_before_import=False,
            week_number=baseline_upload.week_number,
        )
        if not result.get("success"):
            raise AssertionError(f"Acceptance re-import FAILED: {result.get('errors')}")
        if result.get("final_result") != "PASS":
            raise AssertionError(f"Whole-workbook final_result PASS değil: {result.get('final_result')}")
        import_wall_seconds = time.monotonic() - stage_started
        print(
            "IMS_ACCEPTANCE_STAGE|"
            + json.dumps({"stage": "isolated_import", "seconds": round(import_wall_seconds, 4)})
        )

        new_upload = db.session.get(IMSUpload, int(result["upload_id"]))
        if new_upload is None or new_upload.status != "COMPLETED":
            raise AssertionError("Acceptance upload COMPLETED olmadı.")
        stage_started = time.monotonic()
        after = _snapshot(new_upload)
        after_snapshot_seconds = time.monotonic() - stage_started
        print(
            "IMS_ACCEPTANCE_STAGE|"
            + json.dumps({"stage": "acceptance_snapshot", "seconds": round(after_snapshot_seconds, 4)})
        )

        for domain in ("fact", "summary", "target", "official_brick_spread", "official_aggregates"):
            _assert_equal(domain, before[domain], after[domain])
        manifest = result.get("workbook_manifest", [])
        if not manifest or len(manifest) != int(new_upload.sheet_count or 0):
            raise AssertionError(
                f"Manifest sheet sayısı uyuşmuyor: manifest={len(manifest)}, upload={new_upload.sheet_count}"
            )
        manifest_names = {str(item.get("sheet_name") or "") for item in manifest}
        competition_coverage = _validate_competition_coverage(
            before, after, manifest_names
        )
        for total in ("summary_unit", "summary_tl", "target_unit", "target_tl"):
            if abs(float(before[total]) - float(after[total])) > 1e-6:
                raise AssertionError(f"{total} değişti: before={before[total]}, after={after[total]}")

        stats = result.get("statistics", {})
        blocking = {key: int(stats.get(key, 0) or 0) for key in BLOCKING_STATS}
        if any(blocking.values()):
            raise AssertionError(f"Blocking reconciliation counters sıfır değil: {blocking}")
        if new_upload.source_record_count != new_upload.stored_source_record_count:
            raise AssertionError(
                f"Source/stored reconciliation eşit değil: {new_upload.source_record_count}/{new_upload.stored_source_record_count}"
            )
        if new_upload.invalid_metric_count != 0 or new_upload.reconciliation_status != "PASSED":
            raise AssertionError(
                f"Upload reconciliation başarısız: invalid={new_upload.invalid_metric_count}, status={new_upload.reconciliation_status}"
            )

        stage_telemetry = stats.get("stage_telemetry") or {}
        missing_stages = [stage for stage in REQUIRED_IMPORT_STAGES if stage not in stage_telemetry]
        failed_stages = [
            stage
            for stage, telemetry in stage_telemetry.items()
            if telemetry.get("outcome") != "PASS" or float(telemetry.get("duration_seconds", -1)) < 0
        ]
        if missing_stages or failed_stages:
            raise AssertionError(
                f"Import stage telemetry eksik/geçersiz: missing={missing_stages}, failed={failed_stages}"
            )
        if Path("/proc/self/status").is_file() and any(
            stage_telemetry[stage].get("peak_rss_bytes_after") is None
            for stage in REQUIRED_IMPORT_STAGES
        ):
            raise AssertionError("Linux acceptance importunda peak RSS telemetry eksik.")

        report = {
            "result": "PASS",
            "baseline": baseline_counters,
            "acceptance_upload_id": new_upload.id,
            "manifest": {
                "verified": len(manifest),
                "total": new_upload.sheet_count,
                "unclassified_sheet": blocking["unclassified_sheet"],
                "unclassified_master_cell": blocking["unclassified_master_cell"],
            },
            "blocking": blocking,
            "counts": {
                "fact": after["fact"]["count"],
                "summary": after["summary"]["count"],
                "target": after["target"]["count"],
                "competition": after["competition"]["count"],
                "competition_baseline_physical": before["competition"]["count"],
                "competition_semantic": after["competition_semantic"]["count"],
                "competition_baseline_sheets_preserved": competition_coverage["baseline_sheet_count"],
                "competition_new_sheets": competition_coverage["new_sheets"],
                "competition_metadata_migrated_sheets": competition_coverage["metadata_migrated_sheets"],
                "official_brick_spread": after["official_brick_spread"]["count"],
                "official_aggregates": after["official_aggregates"]["count"],
                "source": new_upload.source_record_count,
                "stored": new_upload.stored_source_record_count,
            },
            "totals": {
                "summary_unit": after["summary_unit"],
                "summary_tl": after["summary_tl"],
                "target_unit": after["target_unit"],
                "target_tl": after["target_tl"],
            },
            "fingerprints": {
                domain: after[domain]["sha256"]
                for domain in ("fact", "summary", "target", "competition", "competition_semantic", "official_brick_spread", "official_aggregates")
            },
            "semantic_relationships": result.get("semantic_relationships", []),
            "previous_ims_delta": result.get("previous_ims_delta"),
            "import_telemetry": {
                "processing_seconds": result.get("processing_time"),
                "peak_rss_bytes": max(
                    (
                        int(telemetry.get("peak_rss_bytes_after") or 0)
                        for telemetry in stage_telemetry.values()
                    ),
                    default=0,
                ) or None,
                "stages": stage_telemetry,
            },
            "acceptance_telemetry": {
                "baseline_snapshot_seconds": round(before_snapshot_seconds, 4),
                "isolated_import_wall_seconds": round(import_wall_seconds, 4),
                "acceptance_snapshot_seconds": round(after_snapshot_seconds, 4),
            },
        }
        print("IMS_ACCEPTANCE|" + json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("IMS_ACCEPTANCE|" + json.dumps({"result": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
