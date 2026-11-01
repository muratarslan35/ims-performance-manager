"""Disposable source-versioned region/period availability metadata."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import CompetitionData, IMSUpload
from app.cache.representative_monthly_market_cache import _code_revision


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _read(path, fingerprint):
    try:
        with path.open("rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            return None
        data = json.loads(raw)
        regions = data["regions"]
        if (data["fingerprint"] == fingerprint and isinstance(regions, list)
                and all(isinstance(code, str) and re.fullmatch(r"[0-9]{3}", code) for code in regions)
                and data["sha256"] == hashlib.sha256(_json(regions).encode()).hexdigest()):
            return regions
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _write(path, fingerprint, regions):
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = dict(fingerprint=fingerprint, regions=regions,
                    sha256=hashlib.sha256(_json(regions).encode()).hexdigest())
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(_json(data))
        os.replace(temporary, path)
    except OSError:
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_period_catalog():
    """Preserve the legacy EXISTS predicate, reusing unchanged source months.

    Only exact three-ASCII-digit prefixes use this catalog. All UNIT rows and
    all COMPLETED uploads count, including subtotal-only sources. Metadata is
    grouped by the upload's year/month, exactly as the legacy query does.
    """
    enabled = current_app.config.get("REGION_PERIOD_CATALOG_CACHE_ENABLED", not current_app.testing)
    root = Path(current_app.instance_path) / "region_period_catalog"
    try:
        code_revision = _code_revision(str(Path(__file__).resolve().parents[1]))
    except OSError:
        enabled, code_revision = False, ""
    database = str(Path(str(db.engine.url.database).removeprefix("file:")).resolve())
    sources = defaultdict(list)
    for uid, year, month, completed_at in db.session.query(
        IMSUpload.id, IMSUpload.year, IMSUpload.month, IMSUpload.completed_at,
    ).filter(IMSUpload.status == "COMPLETED").order_by(IMSUpload.id).all():
        sources[(int(year), int(month))].append((int(uid), str(completed_at)))
    result, missing, versions = {}, {}, {}
    for period, uploads in sources.items():
        fingerprint = hashlib.sha256(_json((code_revision, database, period, uploads)).encode()).hexdigest()
        versions[period] = fingerprint
        value = _read(root / f"{period[0]:04d}-{period[1]:02d}.json", fingerprint) if enabled else None
        if value is None:
            missing[period] = uploads
        else:
            result[period] = set(value)
    if missing:
        period_by_upload = {uid: period for period, uploads in missing.items() for uid, _date in uploads}
        prefix = func.substr(CompetitionData.territory, 1, 3)
        for period in missing:
            result[period] = set()
        upload_ids = list(period_by_upload)
        for offset in range(0, len(upload_ids), 500):
            rows = db.session.query(CompetitionData.upload_id, prefix).filter(
                CompetitionData.upload_id.in_(upload_ids[offset:offset + 500]), CompetitionData.metric_type == "UNIT",
            ).distinct().all()
            for uid, code in rows:
                if isinstance(code, str) and re.fullmatch(r"[0-9]{3}", code):
                    result[period_by_upload[int(uid)]].add(code)
        if enabled:
            for period in missing:
                _write(root / f"{period[0]:04d}-{period[1]:02d}.json", versions[period], sorted(result[period]))
    return result


def generation_region_periods(region_key):
    from app.cache.ims_generation_reads import generation_reads
    reads = generation_reads()
    if reads is None or not re.fullmatch(r"[0-9]{3}", str(region_key)):
        return None
    key = ("region-period-catalog",)
    if key not in reads:
        reads[key] = load_period_catalog()
    return [dict(year=year, month=month, label=f"{month:02d}/{year}")
            for (year, month), codes in sorted(reads[key].items(), reverse=True)
            if str(region_key) in codes]
