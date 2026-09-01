from pathlib import Path

import pytest
from openpyxl import Workbook

from app import create_app
from app.extensions import db
from app.models import Product, Representative, Target
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


class GuardConfig:
    TESTING = True
    SECRET_KEY = "production-stale-zero-guard"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/production-stale-zero-guard/uploads")
    REPORT_FOLDER = Path("/tmp/production-stale-zero-guard/reports")
    BACKUP_FOLDER = Path("/tmp/production-stale-zero-guard/backups")
    LOG_FOLDER = Path("/tmp/production-stale-zero-guard/logs")


PRODUCTS = ["TRAVAZOL", "MONUROL", "MIXOVUL", "FENTIVAG", "STIDERM", "ACNEMIX", "BRIMODER"]


def _make_sheet(metric="KUTU", stale_actual=0, stale_name="ILAYDA NUR VARSAK"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"TTS REALIZASYONLARI {metric}"
    header = ["SICIL", "BOLGE", "TEMSILCI"] + PRODUCTS + [f"{metric} HEDEF", "", ""]
    header += PRODUCTS + [f"{metric} CIKIS", "", ""] + PRODUCTS + ["REA"]
    sheet.append(header)

    active = ["", "501 ANKARA", "AKTIF TEMSILCI"] + [10] * 7 + [70, "", ""]
    active += [1] * 7 + [7, "", ""] + [10] * 7 + [10]
    sheet.append(active)

    stale_values = [stale_actual] + [0] * 6
    stale_total = sum(stale_values)
    stale_percentages = [stale_actual * 10] + [0] * 6
    stale_total_percent = stale_total * 100 / 70
    stale = ["", "501 ANKARA", stale_name] + [10] * 7 + [70, "", ""]
    stale += stale_values + [stale_total, "", ""] + stale_percentages + [stale_total_percent]
    sheet.append(stale)
    return workbook, sheet


def _seed_scope(app):
    with app.app_context():
        db.create_all()
        db.session.query(Target).delete()
        db.session.query(Representative).delete()

        active = Representative(
            rep_code="AKTIFTEMSILCI",
            rep_name="AKTIF TEMSILCI",
            region="501",
            city="ANKARA",
            active=True,
        )
        departed = Representative(
            rep_code="ILAYDANURVARSAK",
            rep_name="ILAYDA NUR VARSAK",
            region="501",
            city="ANKARA",
            active=False,
        )
        db.session.add_all([active, departed])
        db.session.flush()

        products = []
        for position, code in enumerate(PRODUCTS, start=1):
            product = Product.query.filter_by(product_code=code).first()
            if product is None:
                product = Product(
                    product_code=code,
                    product_name=code.title(),
                    is_active=True,
                    display_order=position,
                )
                db.session.add(product)
            products.append(product)
        db.session.flush()

        for product in products:
            db.session.add(
                Target(
                    year=2026,
                    month=3,
                    representative_id=active.id,
                    product_id=product.id,
                    tl_target=100,
                    unit_target=10,
                )
            )
        db.session.commit()
        return active.id, departed.id


def test_zero_only_departed_kutu_row_is_ignored_without_reassignment():
    app = create_app(GuardConfig)
    active_id, departed_id = _seed_scope(app)
    _, sheet = _make_sheet(metric="KUTU", stale_actual=0)

    with app.app_context():
        service = ProductionResultImportService("/tmp/not-used.xlsx", 2026, 3, production_stage=2)
        service._load_master_maps()
        rows = service._read_sheet(sheet, "KUTU")

        assert set(rows) == {active_id}
        assert departed_id not in rows
        assert rows[active_id]["values"] == [1.0] * 7


@pytest.mark.parametrize(
    ("metric", "stale_actual", "stale_name"),
    [
        ("KUTU", 1, "ILAYDA NUR VARSAK"),
        ("KUTU", 0, "BILINMEYEN TEMSILCI"),
        ("TL", 0, "ILAYDA NUR VARSAK"),
    ],
)
def test_guard_remains_fail_closed_for_unsafe_unmatched_rows(metric, stale_actual, stale_name):
    app = create_app(GuardConfig)
    _seed_scope(app)
    _, sheet = _make_sheet(metric=metric, stale_actual=stale_actual, stale_name=stale_name)

    with app.app_context():
        service = ProductionResultImportService("/tmp/not-used.xlsx", 2026, 3, production_stage=2)
        service._load_master_maps()
        with pytest.raises(ProductionWorkbookValidationError, match="Eşleşmeyen temsilci"):
            service._read_sheet(sheet, metric)


def test_departed_row_with_current_period_target_is_not_ignored():
    app = create_app(GuardConfig)
    _, departed_id = _seed_scope(app)
    _, sheet = _make_sheet(metric="KUTU", stale_actual=0)

    with app.app_context():
        product = Product.query.filter_by(product_code=PRODUCTS[0]).first()
        db.session.add(
            Target(
                year=2026,
                month=3,
                representative_id=departed_id,
                product_id=product.id,
                tl_target=100,
                unit_target=10,
            )
        )
        db.session.commit()

        service = ProductionResultImportService("/tmp/not-used.xlsx", 2026, 3, production_stage=2)
        service._load_master_maps()
        with pytest.raises(ProductionWorkbookValidationError, match="Eşleşmeyen temsilci"):
            service._read_sheet(sheet, "KUTU")


def _append_semantic_row(sheet, region, name, target, actual, metric):
    targets = [target] * 7
    actuals = [actual] * 7
    percentages = [(actual * 100 / target) if target else 0] * 7
    total_target = sum(targets)
    total_actual = sum(actuals)
    total_percent = total_actual * 100 / total_target if total_target else 0
    row = ["", region, name] + targets + [total_target, "", ""]
    row += actuals + [total_actual, "", ""] + percentages + [total_percent]
    sheet.append(row)


def _make_metric_sheet(metric, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"URETIM {metric}"
    header = ["SICIL", "BOLGE", "TEMSILCI"] + PRODUCTS + [f"{metric} HEDEF", "", ""]
    header += PRODUCTS + [f"{metric} CIKIS", "", ""] + PRODUCTS + ["REA"]
    sheet.append(header)
    for item in rows:
        _append_semantic_row(sheet, *item, metric)
    return sheet


def test_zero_departed_box_row_maps_to_unique_vacancy_when_workbook_signature_proves_succession():
    app = create_app(GuardConfig)
    with app.app_context():
        db.create_all()
        db.session.query(Target).delete()
        db.session.query(Representative).delete()

        active_reps = []
        for idx in range(3):
            rep = Representative(
                rep_code=f"ACTIVE{idx}", rep_name=f"ACTIVE {idx}", region="501", city="ANKARA", active=True
            )
            db.session.add(rep)
            active_reps.append(rep)
        vacancy = Representative(
            rep_code="UNASSIGNED501ANKARABOSKADRO",
            rep_name="ATANMAMIŞ · 501 ANKARA · ANKARA BOS KADRO",
            region="501",
            city="ANKARA",
            active=True,
        )
        departed = Representative(
            rep_code="ILAYDANURVARSAK",
            rep_name="ILAYDA NUR VARSAK",
            region="501",
            city="ANKARA",
            active=False,
        )
        db.session.add_all([vacancy, departed])
        db.session.flush()

        products = []
        for position, code in enumerate(PRODUCTS, start=1):
            product = Product.query.filter_by(product_code=code).first()
            if product is None:
                product = Product(product_code=code, product_name=code.title(), is_active=True, display_order=position)
                db.session.add(product)
            products.append(product)
        db.session.flush()

        for rep in [*active_reps, vacancy]:
            for product in products:
                db.session.add(Target(year=2026, month=3, representative_id=rep.id, product_id=product.id, tl_target=120, unit_target=0))
        db.session.commit()

        tl_rows = [("501 ANKARA", rep.rep_name, 100, 50) for rep in active_reps]
        tl_rows.append(("501 ANKARA", vacancy.rep_name, 120, 60))
        kutu_rows = [("501 ANKARA", rep.rep_name, 10, 5) for rep in active_reps]
        kutu_rows.append(("501 ANKARA", departed.rep_name, 12, 0))
        tl_sheet = _make_metric_sheet("TL", tl_rows)
        kutu_sheet = _make_metric_sheet("KUTU", kutu_rows)

        service = ProductionResultImportService("/tmp/not-used.xlsx", 2026, 3, production_stage=2)
        service._load_master_maps()
        parsed_tl = service._read_sheet(tl_sheet, "TL")
        parsed_kutu = service._read_sheet(kutu_sheet, "KUTU")

        assert set(parsed_tl) == set(parsed_kutu)
        assert vacancy.id in parsed_kutu
        assert departed.id not in parsed_kutu
        assert parsed_kutu[vacancy.id]["targets"] == [12.0] * 7
        assert parsed_kutu[vacancy.id]["values"] == [0.0] * 7


def test_vacancy_succession_remains_fail_closed_when_more_than_one_vacancy_matches():
    app = create_app(GuardConfig)
    with app.app_context():
        db.create_all()
        db.session.query(Target).delete()
        db.session.query(Representative).delete()

        active_reps = []
        for idx in range(3):
            rep = Representative(rep_code=f"ACTIVE{idx}", rep_name=f"ACTIVE {idx}", region="501", city="ANKARA", active=True)
            db.session.add(rep)
            active_reps.append(rep)
        vacancies = [
            Representative(rep_code="UNASSIGNED501A", rep_name="ATANMAMIŞ · 501 ANKARA · BOS A", region="501", city="ANKARA", active=True),
            Representative(rep_code="UNASSIGNED501B", rep_name="ATANMAMIŞ · 501 ANKARA · BOS B", region="501", city="ANKARA", active=True),
        ]
        departed = Representative(rep_code="ILAYDANURVARSAK", rep_name="ILAYDA NUR VARSAK", region="501", city="ANKARA", active=False)
        db.session.add_all([*vacancies, departed])
        db.session.flush()

        products = []
        for position, code in enumerate(PRODUCTS, start=1):
            product = Product.query.filter_by(product_code=code).first()
            if product is None:
                product = Product(product_code=code, product_name=code.title(), is_active=True, display_order=position)
                db.session.add(product)
            products.append(product)
        db.session.flush()
        for rep in [*active_reps, *vacancies]:
            for product in products:
                db.session.add(Target(year=2026, month=3, representative_id=rep.id, product_id=product.id, tl_target=120, unit_target=0))
        db.session.commit()

        tl_rows = [("501 ANKARA", rep.rep_name, 100, 50) for rep in active_reps]
        tl_rows.extend(("501 ANKARA", vacancy.rep_name, 120, 60) for vacancy in vacancies)
        kutu_rows = [("501 ANKARA", rep.rep_name, 10, 5) for rep in active_reps]
        kutu_rows.append(("501 ANKARA", departed.rep_name, 12, 0))
        tl_sheet = _make_metric_sheet("TL", tl_rows)
        kutu_sheet = _make_metric_sheet("KUTU", kutu_rows)

        service = ProductionResultImportService("/tmp/not-used.xlsx", 2026, 3, production_stage=2)
        service._load_master_maps()
        service._read_sheet(tl_sheet, "TL")
        with pytest.raises(ProductionWorkbookValidationError, match="tekil olarak kanıtlanamadı"):
            service._read_sheet(kutu_sheet, "KUTU")
