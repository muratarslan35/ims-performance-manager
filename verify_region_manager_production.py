"""Read-only production acceptance for regional-manager access boundaries."""

import json
import sqlite3
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, Representative, User
from app.region_manager import (
    RegionManagerScope, assigned_region, can_access_region,
    can_access_representative, is_privileged_manager, is_regional_manager, region_code,
)

DENIED_REGION = "Bu bölgenin yöneticisi değilsiniz."
DENIED_SYSTEM = "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız."


def _login_as(client, user_id):
    # This CLI runs in its own process and has no browser fingerprint. Disable
    # only the test client's session-fingerprint check; authorization remains
    # fully active and the production web process is untouched.
    client.application.login_manager.session_protection = None
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["portal"] = "manager"


def _check(condition, label, failures):
    if not condition:
        failures.append(label)


def main():
    app = create_app()
    failures = []
    database = Path("instance/ipm.db")
    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='region_manager_scopes'"
        ).fetchone()
        indexes = {row[1] for row in connection.execute(
            "PRAGMA index_list('region_manager_scopes')"
        )} if table else set()
    finally:
        connection.close()

    _check(str(journal_mode).lower() == "wal", "sqlite_wal", failures)
    _check(int(busy_timeout) == 30000, "sqlite_busy_timeout", failures)
    _check(bool(table), "scope_table_missing", failures)
    _check("ix_region_manager_scopes_user_id" in indexes, "scope_user_index_missing", failures)
    _check("ix_region_manager_scopes_region_code" in indexes, "scope_region_index_missing", failures)

    with app.app_context():
        processing = IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_PROCESSING).count()
        _check(processing == 0, "ims_processing", failures)
        scoped = (
            db.session.query(User, RegionManagerScope)
            .join(RegionManagerScope, RegionManagerScope.user_id == User.id)
            .filter(db.func.lower(User.role) == "manager", User.active.is_(True))
            .order_by(User.id.asc()).all()
        )
        _check(bool(scoped), "no_active_scoped_manager", failures)
        admin = User.query.filter(db.func.lower(User.email) == "admin@ipm.local").one_or_none()
        murat = User.query.filter(db.func.lower(User.email) == "murat.asan@bilimilac.com").one_or_none()
        _check(admin is not None and is_privileged_manager(admin), "admin_access", failures)
        _check(murat is not None and is_privileged_manager(murat) and not is_regional_manager(murat),
               "murat_unrestricted", failures)

        manager = scoped[0][0] if scoped else None
        own_code = assigned_region(manager) if manager else None
        representatives = Representative.query.order_by(Representative.id.asc()).all()
        own_rep = next((row for row in representatives if region_code(row.region) == own_code), None)
        other_rep = next((row for row in representatives if region_code(row.region)
                          and region_code(row.region) != own_code), None)
        if manager:
            _check(is_regional_manager(manager), "scoped_user_not_regional", failures)
            _check(bool(own_code and own_rep and other_rep), "representative_scope_fixture", failures)
        if manager and own_rep and other_rep:
            _check(can_access_region(manager, own_code), "own_region_policy", failures)
            _check(not can_access_region(manager, other_rep.region), "other_region_policy", failures)
            _check(can_access_representative(manager, own_rep), "own_rep_policy", failures)
            _check(not can_access_representative(manager, other_rep), "other_rep_policy", failures)

            client = app.test_client()
            _login_as(client, manager.id)
            _check(client.get("/dashboard/").status_code == 200, "dashboard_general", failures)
            _check(client.get(f"/regions/{own_code}").status_code == 200, "own_region_route", failures)
            denied = client.get(f"/regions/{region_code(other_rep.region)}", follow_redirects=True)
            _check(DENIED_REGION in denied.get_data(as_text=True), "other_region_route", failures)
            _check(client.get(f"/representatives/view/{own_rep.id}").status_code == 200,
                   "own_rep_route", failures)
            denied = client.get(f"/representatives/view/{other_rep.id}", follow_redirects=True)
            _check(DENIED_REGION in denied.get_data(as_text=True), "other_rep_route", failures)
            search = client.get("/representatives/search?q=Temsilci")
            urls = [str(item.get("url") or "") for item in
                    (search.get_json(silent=True) or {}).get("results", [])]
            _check(all(f"/representatives/view/{other_rep.id}" not in url for url in urls),
                   "search_scope", failures)
            _check(client.get("/simulation/").status_code == 200, "simulation_index", failures)
            _check(client.get(f"/simulation/representative/{other_rep.id}").status_code == 403,
                   "simulation_scope", failures)
            _check(client.get("/quarter").status_code == 200, "quarter_index", failures)
            denied = client.get(f"/quarter?representative_id={other_rep.id}", follow_redirects=True)
            _check(DENIED_REGION in denied.get_data(as_text=True), "quarter_scope", failures)
            for path in ("/ims/", "/settings/", "/targets/", "/matching/", "/products/", "/manager-users/"):
                denied = client.get(path, follow_redirects=True)
                _check(DENIED_SYSTEM in denied.get_data(as_text=True), f"system_scope:{path}", failures)

        evidence = {
            "result": "PASS" if not failures else "FAIL", "failures": failures,
            "journal_mode": journal_mode, "busy_timeout": busy_timeout,
            "processing_jobs": processing, "scope_table": bool(table),
            "scope_count": len(scoped), "tested_manager_id": manager.id if manager else None,
            "tested_region": own_code, "admin_preserved": admin is not None,
            "murat_unrestricted": bool(murat and is_privileged_manager(murat)),
        }
    print("REGION_MANAGER_ACCEPTANCE|" + json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
