#!/usr/bin/env python
"""Runtime verification for deployable migration-first IMS environment."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from flask_migrate import upgrade
from sqlalchemy import inspect

from app import create_app
from app.database import initialize_database
from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload, Product, Representative
from app.models import PrimeRule, Setting, User
from app.services.ims_import_service import IMSImportService
from app.services.region_box_authority_guard import audit_all_regions
from config import Config


REPO_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"
ALEMBIC_INI = MIGRATIONS_DIR / "alembic.ini"
DEFAULT_DB_URL = f"sqlite:///{(REPO_ROOT / 'instance' / 'ipm.db').resolve()}"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


class RuntimeCheckConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def _run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _alembic_head_revision() -> str | None:
    config = AlembicConfig(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config).get_current_head()


def _alembic_current_revision() -> str | None:
    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def _sqlite_db_path(uri: str) -> Path | None:
    if not uri.startswith("sqlite:///"):
        return None
    return Path(uri.removeprefix("sqlite:///")).resolve()


def run_checks() -> tuple[list[Check], dict]:
    checks: list[Check] = []
    diagnostics: dict = {}

    branch = _run_git("branch", "--show-current")
    commit = _run_git("rev-parse", "HEAD")
    diagnostics["git"] = {"branch": branch, "commit": commit}
    checks.append(Check("git.branch", bool(branch), branch or "missing"))
    checks.append(Check("git.commit", len(commit) == 40, commit))
    checks.append(Check("working_directory", Path.cwd().resolve() == REPO_ROOT.resolve(), f"cwd={Path.cwd()} expected={REPO_ROOT}"))
    checks.append(Check("python.version", sys.version_info >= (3, 10), platform.python_version()))

    app = create_app(RuntimeCheckConfig)
    checks.append(Check("flask.app_load", app is not None, "create_app() ok"))
    diagnostics["sqlalchemy_uri"] = app.config["SQLALCHEMY_DATABASE_URI"]

    with app.app_context():
        upgrade(directory=str(MIGRATIONS_DIR))
        initialize_database()
        current_revision = _alembic_current_revision()
        head_revision = _alembic_head_revision()
        diagnostics["alembic"] = {"current": current_revision, "head": head_revision}
        checks.append(Check("alembic.current_revision", bool(current_revision), str(current_revision)))
        checks.append(Check("alembic.head_revision", bool(head_revision), str(head_revision)))
        checks.append(Check("alembic.current_equals_head", current_revision == head_revision, f"current={current_revision}, head={head_revision}"))

        db_path = _sqlite_db_path(app.config["SQLALCHEMY_DATABASE_URI"])
        diagnostics["db_file_path"] = str(db_path) if db_path else "<non-sqlite>"
        if db_path:
            checks.append(Check("db.path_target", db_path == (REPO_ROOT / "instance" / "ipm.db").resolve(), str(db_path)))
            checks.append(Check("db.file_exists", db_path.exists(), str(db_path)))

        inspector = inspect(db.engine)
        required_models = {"representatives": Representative, "products": Product, "ims_uploads": IMSUpload, "ims_raw_data": IMSRawData, "ims_facts": IMSFact, "ims_summary": IMSSummary}
        schema_drift = {}
        schema_ok = True
        for table_name, model in required_models.items():
            model_columns = {column.name for column in model.__table__.columns}
            db_columns = {column["name"] for column in inspector.get_columns(table_name)}
            missing = sorted(model_columns - db_columns)
            extra = sorted(db_columns - model_columns)
            schema_drift[table_name] = {"missing_columns": missing, "extra_columns": extra}
            if missing or extra:
                schema_ok = False
        diagnostics["schema_drift"] = schema_drift
        checks.append(Check("schema_drift.required_ims_tables", schema_ok, json.dumps(schema_drift, ensure_ascii=False)))

        required_columns = {"ims_uploads": {"week_number", "raw_record_count", "fact_record_count", "summary_record_count"}, "ims_raw_data": {"week_number", "value_share"}, "ims_facts": {"week_number", "value_share"}, "ims_summary": {"value_share"}}
        missing_required = {}
        required_ok = True
        for table_name, columns in required_columns.items():
            db_columns = {column["name"] for column in inspector.get_columns(table_name)}
            missing = sorted(columns - db_columns)
            if missing:
                required_ok = False
            missing_required[table_name] = missing
        diagnostics["required_columns_missing"] = missing_required
        checks.append(Check("required_columns_presence", required_ok, json.dumps(missing_required, ensure_ascii=False)))

        clean_counts = {"representatives": db.session.query(Representative).count(), "ims_uploads": db.session.query(IMSUpload).count(), "ims_raw_data": db.session.query(IMSRawData).count(), "ims_facts": db.session.query(IMSFact).count(), "ims_summary": db.session.query(IMSSummary).count()}
        diagnostics["row_counts_clean_state"] = clean_counts
        checks.append(Check("clean_state.row_counts", True, str(clean_counts)))

        seed_counts = {"admin_users": db.session.query(User).filter_by(email="admin@ipm.local").count(), "settings": db.session.query(Setting).count(), "products": db.session.query(Product).count(), "prime_rules": db.session.query(PrimeRule).count()}
        diagnostics["seed_counts"] = seed_counts
        checks.append(Check("seed.admin_exists", seed_counts["admin_users"] >= 1, str(seed_counts["admin_users"])))
        checks.append(Check("seed.settings_exist", seed_counts["settings"] > 0, str(seed_counts["settings"])))
        checks.append(Check("seed.products_exist", seed_counts["products"] > 0, str(seed_counts["products"])))
        checks.append(Check("seed.prime_rules_consistency", seed_counts["prime_rules"] >= seed_counts["products"], str(seed_counts)))

        # Production verification must validate the live import service and live
        # database, not a historical workbook that is intentionally not tracked.
        import_ready = {"service_health": IMSImportService.health(), "supported_reports_count": len(IMSImportService.supported_reports())}
        diagnostics["import_readiness"] = import_ready
        checks.append(Check("import.service_health", import_ready["service_health"].get("status") == "READY", json.dumps(import_ready["service_health"], ensure_ascii=False)))
        checks.append(Check("import.supported_reports", import_ready["supported_reports_count"] > 0, str(import_ready["supported_reports_count"])))

        region_box_audit = audit_all_regions()
        diagnostics["region_box_authority"] = region_box_audit
        checks.append(Check(
            "region.box_authority_all_regions",
            not region_box_audit.get("failures"),
            json.dumps(region_box_audit, ensure_ascii=False),
        ))

    return checks, diagnostics


def main() -> int:
    checks, diagnostics = run_checks()
    failed = [check for check in checks if not check.passed]
    print("=== verify_runtime.py ===")
    for check in checks:
        print(f"[{'PASS' if check.passed else 'FAIL'}] {check.name} :: {check.detail}")
    print("\n=== diagnostics ===")
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False))
    if failed:
        print(f"\nRuntime verification failed: {len(failed)} check(s) failed.", file=sys.stderr)
        return 1
    print("\nRuntime verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
