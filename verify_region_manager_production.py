"""Read-only production acceptance for manager access boundaries.

The verifier also guards the dashboard, region and representative steady-state
read paths so deploy completion never depends on historical source workbooks.
"""

import json
import sqlite3
import time
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, Representative, User
from app.region_manager import (
    RegionManagerScope,
    assigned_region,
    can_access_region,
    can_access_representative,
    can_manage_managers,
    can_view_manager_module,
    is_privileged_manager,
    is_regional_manager,
    manager_type,
    region_code,
)
from app.services.access_permission_service import enabled as access_enabled
from sqlalchemy import event

DENIED_REGION = "Bu bölgenin yöneticisi değilsiniz."
DENIED_SYSTEM = "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız."


def _login_as(client, user_id):
    client.application.login_manager.session_protection = None
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["portal"] = "manager"


def _check(condition, label, failures):
    if not condition:
        failures.append(label)


HEAVY_READ_TABLES = (
    " IMS_SUMMARY ",
    " IMS_RAW_DATA ",
    " IMS_FACTS ",
    " IMS_COMPETITION_DATA ",
    " TARGETS ",
    " PRODUCTION_RESULTS ",
    " PRODUCTION_REGION_PRODUCT_RESULTS ",
)


def _measure_route(client, path, *, follow_redirects=False):
    """Measure the steady-state HTTP read path and capture heavy source reads."""
    selects = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " " + " ".join(str(statement).upper().split()) + " "
        if normalized.lstrip().startswith("SELECT"):
            selects.append(normalized)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        started = time.perf_counter()
        response = client.get(path, follow_redirects=follow_redirects)
        seconds = round(time.perf_counter() - started, 4)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    heavy = [
        table.strip()
        for statement in selects
        for table in HEAVY_READ_TABLES
        if table in statement
    ]
    return response, {
        "seconds": seconds,
        "selects": len(selects),
        "heavy_reads": sorted(set(heavy)),
    }


def main():
    app = create_app()
    failures = []
    own_region_seconds = None
    other_region_seconds = None
    dashboard_read = None
    region_read = None
    representative_read = None
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
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info('region_manager_scopes')"
        )} if table else set()
    finally:
        connection.close()

    _check(str(journal_mode).lower() == "wal", "sqlite_wal", failures)
    _check(int(busy_timeout) == 30000, "sqlite_busy_timeout", failures)
    _check(bool(table), "scope_table_missing", failures)
    _check("manager_type" in columns, "manager_type_column_missing", failures)
    _check("ix_region_manager_scopes_user_id" in indexes, "scope_user_index_missing", failures)
    _check("ix_region_manager_scopes_region_code" in indexes, "scope_region_index_missing", failures)
    _check("ix_region_manager_scopes_manager_type" in indexes, "scope_manager_type_index_missing", failures)

    with app.app_context():
        processing = IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_PROCESSING).count()
        _check(processing == 0, "ims_processing", failures)
        scoped = (
            db.session.query(User, RegionManagerScope)
            .join(RegionManagerScope, RegionManagerScope.user_id == User.id)
            .filter(
                db.func.lower(User.role) == "manager",
                User.active.is_(True),
                RegionManagerScope.manager_type == "region",
            )
            .order_by(User.id.asc()).all()
        )
        _check(bool(scoped), "no_active_regional_manager", failures)
        admin = User.query.filter(db.func.lower(User.email) == "admin@ipm.local").one_or_none()
        murat = User.query.filter(db.func.lower(User.email) == "murat.asan@bilimilac.com").one_or_none()
        _check(admin is not None and is_privileged_manager(admin), "admin_access", failures)
        _check(bool(admin and can_manage_managers(admin)), "admin_manager_mutation", failures)
        _check(murat is not None and is_privileged_manager(murat) and not is_regional_manager(murat),
               "murat_unrestricted", failures)

        manager = scoped[0][0] if scoped else None
        own_code = assigned_region(manager) if manager else None
        representatives = Representative.query.order_by(Representative.id.asc()).all()
        own_rep = next((row for row in representatives if region_code(row.region) == own_code), None)
        other_rep = next((row for row in representatives if region_code(row.region)
                          and region_code(row.region) != own_code), None)
        if manager:
            permission_state = {
                key: access_enabled(manager, key)
                for key in (
                    "cross_region_details", "manager_module", "manage_managers",
                    "prime_simulation", "q_analysis", "ims_center", "targets",
                    "manual_matching", "products",
                )
            }
            _check(is_regional_manager(manager), "scoped_user_not_regional", failures)
            _check(manager_type(manager) == "region", "regional_type", failures)
            _check(can_view_manager_module(manager) == permission_state["manager_module"],
                   "regional_manager_module_policy", failures)
            expected_manage = permission_state["manager_module"] and permission_state["manage_managers"]
            _check(can_manage_managers(manager) == expected_manage,
                   "regional_manager_mutation_policy", failures)
            _check(bool(own_code and own_rep and other_rep), "representative_scope_fixture", failures)
        if manager and own_rep and other_rep:
            cross_region = permission_state["cross_region_details"]
            _check(can_access_region(manager, own_code), "own_region_policy", failures)
            _check(can_access_region(manager, other_rep.region) == cross_region,
                   "other_region_policy", failures)
            _check(can_access_representative(manager, own_rep), "own_rep_policy", failures)
            _check(can_access_representative(manager, other_rep) == cross_region,
                   "other_rep_policy", failures)

            client = app.test_client()
            _login_as(client, manager.id)

            # One warm read may perform a compatibility upgrade for an older
            # persisted payload. The measured second read must stay on read
            # models only and must never hit IMS/target/competition source data.
            _check(client.get("/dashboard/").status_code == 200, "dashboard_general", failures)
            dashboard_response, dashboard_read = _measure_route(client, "/dashboard/")
            _check(dashboard_response.status_code == 200, "dashboard_hot_route", failures)
            _check(not dashboard_read["heavy_reads"], "dashboard_heavy_source_read", failures)
            _check(dashboard_read["seconds"] <= 2.0, "dashboard_hot_route_slow", failures)

            manager_page = client.get("/manager-users/", follow_redirects=True)
            _check(("Kayıtlı Yöneticiler" in manager_page.get_data(as_text=True)) == permission_state["manager_module"],
                   "manager_module_read", failures)
            # Warm once to allow a one-time read-model enrichment after an
            # older deployment, then measure the steady-state snapshot route.
            own_region_response = client.get(f"/regions/{own_code}")
            _check(own_region_response.status_code == 200, "own_region_route", failures)
            own_region_response, region_read = _measure_route(
                client, f"/regions/{own_code}"
            )
            own_region_seconds = region_read["seconds"]
            _check(own_region_response.status_code == 200, "own_region_hot_route", failures)
            _check(not region_read["heavy_reads"], "region_heavy_source_read", failures)
            _check(region_read["seconds"] <= 2.0, "region_hot_route_slow", failures)
            other_region_started = time.perf_counter()
            other_region_response = client.get(
                f"/regions/{region_code(other_rep.region)}", follow_redirects=True
            )
            other_region_seconds = round(time.perf_counter() - other_region_started, 4)
            _check((DENIED_REGION not in other_region_response.get_data(as_text=True)) == cross_region,
                   "other_region_route", failures)
            _check(client.get(f"/representatives/view/{own_rep.id}").status_code == 200,
                   "own_rep_route", failures)
            own_rep_response, representative_read = _measure_route(
                client, f"/representatives/view/{own_rep.id}"
            )
            _check(own_rep_response.status_code == 200, "own_rep_hot_route", failures)
            _check(
                not representative_read["heavy_reads"],
                "representative_heavy_source_read",
                failures,
            )
            _check(
                representative_read["seconds"] <= 2.0,
                "representative_hot_route_slow",
                failures,
            )
            other_rep_response = client.get(f"/representatives/view/{other_rep.id}", follow_redirects=True)
            _check((DENIED_REGION not in other_rep_response.get_data(as_text=True)) == cross_region,
                   "other_rep_route", failures)
            search = client.get("/representatives/search?q=Temsilci")
            urls = [str(item.get("url") or "") for item in
                    (search.get_json(silent=True) or {}).get("results", [])]
            if not cross_region:
                _check(all(f"/representatives/view/{other_rep.id}" not in url for url in urls),
                       "search_scope", failures)
            simulation = client.get("/simulation/", follow_redirects=True)
            _check((DENIED_SYSTEM not in simulation.get_data(as_text=True)) == permission_state["prime_simulation"],
                   "simulation_index", failures)
            if permission_state["prime_simulation"]:
                simulation_detail = client.get(f"/simulation/representative/{other_rep.id}")
                _check((simulation_detail.status_code != 403) == cross_region,
                       "simulation_scope", failures)
            quarter = client.get("/quarter", follow_redirects=True)
            _check((DENIED_SYSTEM not in quarter.get_data(as_text=True)) == permission_state["q_analysis"],
                   "quarter_index", failures)
            if permission_state["q_analysis"]:
                quarter_detail = client.get(f"/quarter?representative_id={other_rep.id}", follow_redirects=True)
                _check((DENIED_REGION not in quarter_detail.get_data(as_text=True)) == cross_region,
                       "quarter_scope", failures)
            for path, permission in (
                ("/ims/", "ims_center"), ("/targets/", "targets"),
                ("/matching/", "manual_matching"), ("/products/", "products"),
            ):
                response = client.get(path, follow_redirects=True)
                _check((DENIED_SYSTEM not in response.get_data(as_text=True)) == permission_state[permission],
                       f"system_scope:{path}", failures)
            settings_response = client.get("/settings/", follow_redirects=True)
            _check(DENIED_SYSTEM in settings_response.get_data(as_text=True),
                   "system_scope:/settings/", failures)

        evidence = {
            "result": "PASS" if not failures else "FAIL",
            "failures": failures,
            "journal_mode": journal_mode,
            "busy_timeout": busy_timeout,
            "processing_jobs": processing,
            "scope_table": bool(table),
            "regional_scope_count": len(scoped),
            "own_region_seconds": own_region_seconds,
            "other_region_seconds": other_region_seconds,
            "dashboard_read": dashboard_read,
            "region_read": region_read,
            "representative_read": representative_read,
            "tested_manager_id": manager.id if manager else None,
            "tested_region": own_code,
            "admin_preserved": admin is not None,
            "admin_can_manage": bool(admin and can_manage_managers(admin)),
            "murat_unrestricted": bool(murat and is_privileged_manager(murat)),
            "regional_permissions": permission_state if manager else {},
        }
    print("REGION_MANAGER_ACCEPTANCE|" + json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
