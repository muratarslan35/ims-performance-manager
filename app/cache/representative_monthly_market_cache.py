"""Private, disposable monthly intermediates for snapshot composition.

One file per representative/month is replaced when its exact inputs change.
Cache misses always run the canonical market calculator. No business table or
published historical snapshot is written by this cache.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from functools import lru_cache
import hashlib
import gzip
import json
import os
from pathlib import Path
from threading import Lock
import uuid

from flask import current_app, has_request_context

from app.extensions import db
from app.models import Product, RepresentativeBrickAssignment


@lru_cache(maxsize=4)
def _code_revision(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*.py")):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    config = Path(root).parent / "config.py"
    if config.is_file():
        digest.update(config.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _box_type():
    from app.services.week8_read_path_repair import _TurkishBoxNumber
    return _TurkishBoxNumber


def _encode(value):

    if value is None or type(value) in (str, bool, int, float):
        return value
    if isinstance(value, Product):
        return {"__ims_cached_type__": "product", "id": int(value.id)}
    if isinstance(value, _box_type()):
        return {"__ims_cached_type__": "box", "value": float(value)}
    if isinstance(value, Decimal):
        return {"__ims_cached_type__": "decimal", "value": str(value)}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, tuple):
        return {"__ims_cached_type__": "tuple", "items": [_encode(item) for item in value]}
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _encode(item) for key, item in value.items()}
    raise TypeError("Unsupported monthly market cache value")


def _decode(value, products):
    if isinstance(value, list):
        return [_decode(item, products) for item in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("__ims_cached_type__")
    if kind == "product":
        return products[int(value["id"])]
    if kind == "box":
        return _box_type()(value["value"])
    if kind == "decimal":
        return Decimal(value["value"])
    if kind == "tuple":
        return tuple(_decode(item, products) for item in value["items"])
    if kind is not None:
        raise ValueError("Unknown monthly market cache value")
    return {key: _decode(item, products) for key, item in value.items()}


def _json(value, *, sort_keys=True):
    return json.dumps(value, sort_keys=sort_keys, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class RepresentativeMonthlyMarketCache:
    _stats = Counter()
    _lock = Lock()
    _MAX_FILE_BYTES = 16 * 1024 * 1024

    @classmethod
    def statistics(cls, *, reset=False):
        with cls._lock:
            result = dict(cls._stats)
            if reset:
                cls._stats.clear()
            return result

    @classmethod
    def _count(cls, name):
        with cls._lock:
            cls._stats[name] += 1

    @staticmethod
    def _inputs(representative, year, month, source_key):
        from app.services.production_result_service import ProductionResultService
        from app.services.representative_market_service import RepresentativeMarketService

        ordinal = int(year) * 12 + int(month) - 2
        previous = ordinal // 12, ordinal % 12 + 1
        periods = [(int(year), int(month)), previous]
        products = RepresentativeMarketService(representative, year, month)._products()
        material = {
            "code": _code_revision(str(Path(__file__).resolve().parents[1])),
            "database": str(Path(str(db.engine.url.database).removeprefix("file:")).resolve()),
            "source": source_key,
            "identity": [representative.id, representative.rep_name, representative.region, representative.city, representative.territory, representative.active],
            "catalog": [[p.id, p.product_name, p.product_code, p.ims_name, p.competitor_group, p.display_order, p.is_active] for p in products],
            "periods": [],
        }
        for y, m in periods:
            assignments = db.session.query(RepresentativeBrickAssignment.brick).filter_by(
                representative_id=representative.id, year=y, month=m, active=True
            ).order_by(RepresentativeBrickAssignment.brick).all()
            effective = ProductionResultService.effective_products(y, m, representative.id)
            material["periods"].append({
                "year": y, "month": m, "bricks": [row[0] for row in assignments],
                "effective": {
                    str(pid): {key: str(value) if isinstance(value, Decimal) else value for key, value in values.items()}
                    for pid, values in effective.items()
                },
            })
        fingerprint = hashlib.sha256(_json(material).encode()).hexdigest()
        return fingerprint, {int(p.id): p for p in products}

    @classmethod
    def get_or_compute(cls, representative, year, month, source_key, loader):
        from app.services.representative_query_optimizer import snapshot_build_active

        if has_request_context() or not snapshot_build_active() or not current_app.config.get(
            "REPRESENTATIVE_MONTHLY_MARKET_CACHE_ENABLED", not current_app.testing
        ):
            return loader()
        path = None
        fingerprint = None
        try:
            fingerprint, products = cls._inputs(representative, year, month, source_key)
            root = Path(current_app.instance_path) / "representative_monthly_market"
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = root / f"{int(year):04d}-{int(month):02d}-{int(representative.id)}.json.gz"
            if path.is_file() and path.stat().st_size <= cls._MAX_FILE_BYTES:
                with gzip.open(path, "rb") as source:
                    raw = source.read(cls._MAX_FILE_BYTES + 1)
                if len(raw) > cls._MAX_FILE_BYTES:
                    raise ValueError("Monthly market cache exceeds size limit")
                envelope = json.loads(raw)
                data = envelope["data"]
                if envelope["fingerprint"] == fingerprint and envelope["sha256"] == hashlib.sha256(_json(data, sort_keys=False).encode()).hexdigest():
                    result = _decode(data, products)
                    cls._count("hits")
                    return result
        except (OSError, EOFError, ValueError, TypeError, KeyError):
            cls._count("unavailable")
        cls._count("misses")
        result = loader()
        if path is None or fingerprint is None:
            return result
        temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        try:
            data = _encode(result)
            envelope = _json({"fingerprint": fingerprint, "sha256": hashlib.sha256(_json(data, sort_keys=False).encode()).hexdigest(), "data": data}, sort_keys=False).encode()
            if len(envelope) > cls._MAX_FILE_BYTES:
                return result
            descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(gzip.compress(envelope, compresslevel=1, mtime=0))
            os.replace(temporary, path)
            cls._count("writes")
        except (OSError, ValueError, TypeError):
            cls._count("unavailable")
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return result
