"""Run a production-shaped, non-production capacity soak against a temporary DB."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests
from flask_migrate import upgrade
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import create_app
from app.database import initialize_database
from app.extensions import db
from app.models import (
    CompetitionData,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Product,
    Representative,
    RepresentativeBrickAssignment,
    Target,
    User,
)


MIGRATIONS_DIR = str(REPO_ROOT / "migrations")
REGIONS = (
    "101 ISTANBUL",
    "201 KADIKOY",
    "301 BURSA",
    "401 IZMIR",
    "501 ANKARA",
    "601 SAMSUN",
    "602 TRABZON",
    "701 ADANA",
    "801 KONYA",
    "802 ANTALYA",
    "901 DIYARBAKIR",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[position]


def _seed_database(root: Path, history_count: int, representative_count: int) -> dict:
    database_path = root / "capacity.db"

    class CapacityConfig:
        TESTING = True
        SECRET_KEY = "capacity-seed-only"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = root / "uploads"
        REPORT_FOLDER = root / "reports"
        BACKUP_FOLDER = root / "backups"
        LOG_FOLDER = root / "logs"
        TEMP_FOLDER = root / "temp"

    app = create_app(CapacityConfig)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()

        password_hash = generate_password_hash("capacity-password")
        admin = User.query.filter_by(email="admin@ipm.local").one()
        admin.full_name = "Capacity Admin"
        admin.password = password_hash
        admin.role = "Admin"
        admin.active = True

        representatives = []
        users = []
        for index in range(representative_count):
            region = REGIONS[index % len(REGIONS)]
            email = f"capacity.rep.{index + 1:03d}@example.test"
            representatives.append(
                Representative(
                    rep_code=f"CAP-{index + 1:03d}",
                    ims_code=f"IMS-{index + 1:03d}",
                    rep_name=f"CAPACITY TEMSILCI {index + 1:03d}",
                    region=region,
                    city=region.split(" ", 1)[-1],
                    district=f"BRICK {index + 1:03d}",
                    territory=f"BRICK {index + 1:03d}",
                    team="TAYFUN-1",
                    email=email,
                    active=True,
                )
            )
            users.append(
                User(
                    full_name=f"Capacity Representative {index + 1:03d}",
                    email=email,
                    password=password_hash,
                    role="Representative",
                    active=True,
                )
            )
        db.session.add_all(representatives + users)
        db.session.flush()
        vacancies = []
        for index, region in enumerate(REGIONS):
            vacancies.append(
                Representative(
                    rep_code=f"UNASSIGNED-CAP-{index + 1:02d}",
                    ims_code=f"UNASSIGNED-IMS-{index + 1:02d}",
                    rep_name=f"{region} BOS",
                    region=region,
                    city=region.split(" ", 1)[-1],
                    district=region.split(" ", 1)[-1],
                    territory=f"VACANCY BRICK {index + 1:02d}",
                    team="TAYFUN-1",
                    active=True,
                )
            )
        db.session.add_all(vacancies)
        db.session.flush()
        all_representatives = representatives + vacancies

        base_time = datetime(2026, 1, 1, 8, 0)
        uploads = []
        for index in range(history_count):
            uploads.append(
                IMSUpload(
                    file_name=f"capacity-week-{index + 1:03d}.xlsx",
                    year=2026,
                    month=1,
                    quarter="Q1",
                    week_number=(index % 52) + 1,
                    sheet_count=16,
                    raw_record_count=28091,
                    summary_record_count=791,
                    source_record_count=28091,
                    stored_source_record_count=28091,
                    reconciliation_status="PASSED",
                    status="COMPLETED",
                    uploaded_by="Capacity Admin",
                    uploaded_at=base_time + timedelta(days=index),
                    completed_at=base_time + timedelta(days=index, minutes=4),
                )
            )
        db.session.add_all(uploads)
        db.session.flush()
        latest_upload_id = uploads[-1].id

        products = Product.query.filter_by(is_active=True).order_by(Product.id).all()
        for rep_index, representative in enumerate(all_representatives):
            db.session.add(
                RepresentativeBrickAssignment(
                    representative_id=representative.id,
                    year=2026,
                    month=1,
                    quarter="Q1",
                    brick=f"BRICK {rep_index + 1:03d}",
                    territory=representative.region,
                    city=representative.city,
                    source="AUTO",
                    active=True,
                )
            )
            for product_index, product in enumerate(products):
                target_tl = 100000.0 + rep_index * 100 + product_index * 1000
                target_unit = 1000.0 + product_index * 50
                actual_ratio = 0.85 + ((rep_index + product_index) % 25) / 100
                db.session.add(
                    Target(
                        year=2026,
                        month=1,
                        quarter="Q1",
                        representative_id=representative.id,
                        product_id=product.id,
                        unit_target=target_unit,
                        tl_target=target_tl,
                    )
                )
                db.session.add(
                    IMSSummary(
                        upload_id=latest_upload_id,
                        year=2026,
                        month=1,
                        quarter="Q1",
                        representative_id=representative.id,
                        product_id=product.id,
                        unit=target_unit * actual_ratio,
                        tl=target_tl * actual_ratio,
                        target_unit=target_unit,
                        target_tl=target_tl,
                        realization_percent=actual_ratio * 100,
                    )
                )
        db.session.commit()

        raw_batch = []
        for index in range(28091):
            representative = all_representatives[index % len(all_representatives)]
            product = products[index % len(products)]
            raw_batch.append(
                {
                    "upload_id": latest_upload_id,
                    "year": 2026,
                    "month": 1,
                    "quarter": "Q1",
                    "week_number": 5,
                    "sheet_name": "CAPACITY IMS",
                    "sheet_type": "dashboard_balance_region" if index % 5 == 0 else "weekly_sales",
                    "source_row": index + 2,
                    "representative_id": representative.id,
                    "product_id": product.id,
                    "representative": representative.rep_name,
                    "territory": representative.region,
                    "brick": representative.territory,
                    "product": product.product_name,
                    "unit": float((index % 50) + 1),
                    "tl": float((index % 50) + 1) * float(product.unit_price or 100),
                    "raw_json": "{}",
                }
            )
            if len(raw_batch) == 5000:
                db.session.bulk_insert_mappings(IMSRawData, raw_batch)
                db.session.commit()
                raw_batch.clear()
        if raw_batch:
            db.session.bulk_insert_mappings(IMSRawData, raw_batch)
            db.session.commit()

        competition_batch = []
        inserted = 0
        for sheet_index in range(16):
            for territory_index, territory in enumerate(REGIONS):
                for brick_index in range(len(all_representatives)):
                    for product_index, product in enumerate(products):
                        competition_batch.append(
                            {
                                "upload_id": latest_upload_id,
                                "year": 2026,
                                "month": 1,
                                "week_number": 5,
                                "sheet_name": f"CAPACITY COMP {sheet_index + 1:02d}",
                                "period_type": "MONTHLY",
                                "territory": territory,
                                "subterritory": f"BRICK {brick_index + 1:03d}",
                                "product_group": f"{product.product_name} PAZARI",
                                "product_name": f"RAKIP {product_index + 1:02d}",
                                "metric_type": "TL",
                                "metric_value": float(100 + (inserted % 5000)),
                                "is_company_product": False,
                                "is_competitor": True,
                                "is_subtotal": False,
                                "is_grand_total": False,
                                "source_row": brick_index + 2,
                            }
                        )
                        inserted += 1
                        if len(competition_batch) == 5000:
                            db.session.bulk_insert_mappings(CompetitionData, competition_batch)
                            db.session.commit()
                            competition_batch.clear()
                        if inserted == 100000:
                            break
                    if inserted == 100000:
                        break
                if inserted == 100000:
                    break
            if inserted == 100000:
                break
        if competition_batch:
            db.session.bulk_insert_mappings(CompetitionData, competition_batch)
            db.session.commit()

        integrity = db.session.execute(text("PRAGMA integrity_check")).scalar()
        counts = {
            "history": IMSUpload.query.count(),
            "representatives": Representative.query.filter_by(active=True).count(),
            "products": Product.query.filter_by(is_active=True).count(),
            "targets": Target.query.count(),
            "summaries": IMSSummary.query.count(),
            "raw": IMSRawData.query.count(),
            "competition": CompetitionData.query.count(),
            "integrity": integrity,
        }
    return {"database_path": str(database_path), "counts": counts}


def _request_user(base_url: str, index: int, request_rounds: int) -> list[dict]:
    is_admin = index == 0
    email = "admin@ipm.local" if is_admin else f"capacity.rep.{index:03d}@example.test"
    portal = "manager" if is_admin else "representative"
    results = []
    with requests.Session() as session:
        started = time.perf_counter()
        response = session.post(
            f"{base_url}/login",
            data={"email": email, "password": "capacity-password", "portal": portal},
            timeout=60,
        )
        results.append({"path": "/login", "status": response.status_code, "seconds": time.perf_counter() - started})
        for _ in range(request_rounds):
            for path in (("/ims/",) if is_admin else ("/dashboard/",)):
                started = time.perf_counter()
                response = session.get(f"{base_url}{path}", timeout=120)
                results.append({"path": path, "status": response.status_code, "seconds": time.perf_counter() - started})
    return results


def _wait_until_ready(base_url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/login", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise RuntimeError("Gunicorn did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=int, default=100)
    parser.add_argument("--representatives", type=int, default=102)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--max-p95", type=float, default=10.0)
    parser.add_argument("--max-latency", type=float, default=30.0)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="ims-capacity-") as temp_name:
        root = Path(temp_name)
        seeded = _seed_database(root, args.history, args.representatives)
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        environment = os.environ.copy()
        environment.update(
            {
                "APP_ENV": "development",
                "SECRET_KEY": "capacity-runtime-secret",
                "DATABASE_URL": f"sqlite:///{seeded['database_path']}",
                "USER_VAULT_PATH": str(root / "users.db"),
            }
        )
        command = [
            str(Path(os.sys.executable).parent / "gunicorn"),
            "--bind", f"127.0.0.1:{port}",
            "--workers", "2",
            "--threads", "3",
            "--timeout", "120",
            "--access-logfile", "/dev/null",
            "--error-logfile", str(root / "gunicorn.log"),
            "run:app",
        ]
        process = subprocess.Popen(command, cwd=REPO_ROOT, env=environment)
        try:
            _wait_until_ready(base_url)
            started = time.perf_counter()
            all_results = []
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [
                    executor.submit(_request_user, base_url, index, args.rounds)
                    for index in range(args.representatives + 1)
                ]
                for future in as_completed(futures):
                    all_results.extend(future.result())
            duration = time.perf_counter() - started
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        latencies = [item["seconds"] for item in all_results]
        errors = [item for item in all_results if item["status"] != 200]
        p95 = _percentile(latencies, 0.95)
        max_latency = max(latencies)
        passed = not errors and p95 <= args.max_p95 and max_latency <= args.max_latency
        result = {
            "result": "PASS" if passed else "FAIL",
            "shape": seeded["counts"],
            "gunicorn": {"workers": 2, "threads_per_worker": 3},
            "virtual_users": args.representatives + 1,
            "concurrency": args.concurrency,
            "requests": len(all_results),
            "errors": len(errors),
            "duration_seconds": round(duration, 3),
            "requests_per_second": round(len(all_results) / duration, 2),
            "latency_seconds": {
                "mean": round(statistics.mean(latencies), 3),
                "p50": round(_percentile(latencies, 0.50), 3),
                "p95": round(p95, 3),
                "p99": round(_percentile(latencies, 0.99), 3),
                "max": round(max_latency, 3),
            },
            "thresholds": {
                "max_p95_seconds": args.max_p95,
                "max_latency_seconds": args.max_latency,
            },
        }
        print("CAPACITY_SOAK|" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
