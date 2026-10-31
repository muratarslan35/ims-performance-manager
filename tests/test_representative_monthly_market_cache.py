from decimal import Decimal
import json
import gzip
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import Product, Representative, RepresentativeBrickAssignment
from app.cache.representative_monthly_market_cache import RepresentativeMonthlyMarketCache as Cache
from app.services.production_result_service import ProductionResultService
from app.services.representative_query_optimizer import use_snapshot_upload_ids
from app.services.week8_read_path_repair import _TurkishBoxNumber


@pytest.fixture
def cache_context(tmp_path, monkeypatch):
    class Config:
        TESTING = True
        SECRET_KEY = "monthly-input-cache-test"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        REPRESENTATIVE_MONTHLY_MARKET_CACHE_ENABLED = True

    app = create_app(Config)
    app.instance_path = str(tmp_path / "instance")
    with app.app_context():
        db.create_all()
        rep = Representative(rep_code="CACHE", rep_name="BOŞ", region="901", active=False)
        product = Product(product_code="TRAVAZOL", product_name="Travazol", ims_name="TRAVAZOL", competitor_group="GROUP", unit_price=10, is_active=True)
        db.session.add_all([rep, product])
        db.session.commit()
        values = {product.id: {"source": "IMS", "complete": True, "target_tl": Decimal("10"), "actual_unit": Decimal("0")}}
        monkeypatch.setattr(ProductionResultService, "effective_products", classmethod(lambda *args, **kwargs: values))
        calls = []
        def load():
            calls.append(True)
            return {"rows": [{"product": product, "actual_unit": _TurkishBoxNumber(0), "large_unit": _TurkishBoxNumber(9360), "target_tl": Decimal("1.25"), "missing": None}]}
        yield app, rep, product, values, calls, load


def _read(rep, source, load):
    with use_snapshot_upload_ids({}):
        return Cache.get_or_compute(rep, 2025, 2, source, load)


def test_monthly_cache_survives_member_contexts_and_preserves_types_zero_and_identity(cache_context):
    app, rep, product, values, calls, load = cache_context
    first = _read(rep, "source-1", load)
    first["rows"][0]["actual_unit"] = 999
    product_id = product.id
    db.session.remove()
    restored_product = db.session.get(Product, product_id)
    second = _read(rep, "source-1", load)
    row = second["rows"][0]
    assert list(row) == ["product", "actual_unit", "large_unit", "target_tl", "missing"]
    assert calls == [True]
    assert row["product"] is restored_product
    assert row["product"] is not product
    assert row["actual_unit"] == 0
    assert type(row["actual_unit"]) is _TurkishBoxNumber
    assert format(row["large_unit"], ",.0f") == "9.360"
    assert row["target_tl"] == Decimal("1.25")
    assert row["missing"] is None
    assert len(list((Path(app.instance_path) / "representative_monthly_market").glob("*.json.gz"))) == 1


def test_monthly_cache_rotates_on_sources_effective_values_prior_scope_and_catalog(cache_context):
    app, rep, product, values, calls, load = cache_context
    _read(rep, "source-1", load)
    _read(rep, "source-2", load)
    values[product.id]["source"] = "PRODUCTION_2"
    _read(rep, "source-2", load)
    values[product.id]["actual_unit"] = None
    _read(rep, "source-2", load)
    db.session.add(RepresentativeBrickAssignment(representative_id=rep.id, year=2025, month=1, brick="PREVIOUS SCOPE", active=True))
    db.session.commit()
    _read(rep, "source-2", load)
    product.competitor_group = "NEW GROUP"
    db.session.commit()
    _read(rep, "source-2", load)
    assert len(calls) == 6
    assert len(list((Path(app.instance_path) / "representative_monthly_market").glob("*.json.gz"))) == 1


def test_corrupt_or_tampered_monthly_cache_recomputes_canonical_data(cache_context):
    app, rep, product, values, calls, load = cache_context
    _read(rep, "source-1", load)
    path = next((Path(app.instance_path) / "representative_monthly_market").glob("*.json.gz"))
    envelope = json.loads(gzip.decompress(path.read_bytes()))
    envelope["data"]["rows"][0]["missing"] = 777
    path.write_bytes(gzip.compress(json.dumps(envelope).encode()))
    assert _read(rep, "source-1", load)["rows"][0]["missing"] is None
    path.write_bytes(b"broken gzip")
    assert _read(rep, "source-1", load)["rows"][0]["actual_unit"] == 0
    assert len(calls) == 3


def test_monthly_cache_is_only_used_during_snapshot_build(cache_context):
    app, rep, product, values, calls, load = cache_context
    Cache.get_or_compute(rep, 2025, 2, "source-1", load)
    Cache.get_or_compute(rep, 2025, 2, "source-1", load)
    assert len(calls) == 2
    assert not (Path(app.instance_path) / "representative_monthly_market").exists()
    with app.test_request_context("/representatives/1"), use_snapshot_upload_ids({}):
        Cache.get_or_compute(rep, 2025, 2, "source-1", load)
    assert len(calls) == 3
    assert not (Path(app.instance_path) / "representative_monthly_market").exists()
