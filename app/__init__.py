from flask import Flask
from flask import render_template
from pathlib import Path
from datetime import timezone
from zoneinfo import ZoneInfo
import os

from sqlalchemy.pool import NullPool

from config import Config

from app.extensions import db
from app.extensions import migrate
from app.extensions import login_manager

import app.login_manager

from app.database import initialize_database
from app.services.sqlite_runtime import (
    configure_sqlite_runtime,
    install_sqlite_connection_pragmas,
)
from app.services.sqlite_import_maintenance import install_sqlite_import_maintenance
from app.services.vacancy_matching import install_vacancy_matcher
from app.services.representative_resolver import install_representative_resolver
from app.services.semantic_import_discovery import install_semantic_import_discovery
from app.services.dynamic_import_contract import install_dynamic_import_contract
from app.services.dynamic_import_refinement import install_dynamic_import_refinement
from app.services.aggregate_identity_refinement import install_aggregate_identity_refinement
from app.services.ims_summary_integrity import install_ims_summary_integrity
from app.services.workbook_preflight import install_workbook_preflight
from app.services.official_brick_spread_atomic import install_official_brick_spread_atomic
from app.services.derived_master_verification import install_derived_verification_gate
from app.services.ims_delta_audit import install_previous_ims_delta_audit
from app.services.import_result_report import (
    install_import_result_reporting,
    latest_import_report,
)
from app.services.manager_import_report_alignment import install_manager_import_report_alignment
from app.services.dashboard_runtime_optimizer import install_dashboard_runtime_optimizer
from app.services.ims_upload_lifecycle_hooks import install_ims_upload_lifecycle
from app.services.ims_upload_lifecycle_ui import install_ims_upload_lifecycle_ui
from app.services.production_result_retry_ui import install_production_result_retry_ui
from app.services.production_result_reconciliation_gate import install_production_result_reconciliation_gate
from app.access_control import register_access_control

from app.routes import main_bp
from app.auth import auth_bp
from app.products import products_bp
from app.routes.settings import settings_bp
from app.routes.targets import targets_bp
from app.routes.matching import matching_bp
from app.routes.ims_progress import ims_progress_bp
from app.competition.api import competition_bp
from app.ims import ims_bp
from app.dashboard import dashboard_bp
from app.representatives import representatives_bp
from app.simulation import simulation_bp
from app.regions import regions_bp


def register_template_context(app):
    """Expose current IMS period and compact import audit report consistently."""
    @app.template_filter("istanbul_datetime")
    def istanbul_datetime(value, format_string="%d.%m.%Y %H:%M"):
        """Render UTC database timestamps in the application's local timezone."""
        if value is None:
            return "—"
        aware_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware_value.astimezone(ZoneInfo("Europe/Istanbul")).strftime(format_string)

    @app.context_processor
    def shell_context():
        try:
            from app.models import IMSUpload
            from app.services.period_service import PeriodService
            period = PeriodService.get_active_period()
            upload = IMSUpload.query.filter_by(status="COMPLETED").order_by(IMSUpload.uploaded_at.desc()).first()
            period_label = f"{period['year']}/{int(period['month']):02d} - {period.get('week_number') or '-'}. Hafta"
            upload_label = upload.uploaded_at.strftime("%d.%m.%Y") if upload and upload.uploaded_at else "—"
            return {
                "active_period": period_label,
                "latest_upload_date": upload_label,
                "latest_import_report": latest_import_report(),
            }
        except Exception:
            return {
                "active_period": "—",
                "latest_upload_date": "—",
                "latest_import_report": None,
            }


def register_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Bu sayfayı görüntülemek için giriş yapın."
    login_manager.login_message_category = "warning"


def register_blueprints(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(targets_bp)
    app.register_blueprint(matching_bp)
    app.register_blueprint(competition_bp)
    app.register_blueprint(ims_bp)
    app.register_blueprint(ims_progress_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(representatives_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(regions_bp)


def create_directories(app):
    folders = [
        app.config["UPLOAD_FOLDER"], app.config["REPORT_FOLDER"],
        app.config["BACKUP_FOLDER"], app.config["LOG_FOLDER"],
        app.config.get("TEMP_FOLDER", Path(app.instance_path) / "temp"),
    ]
    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_uri.startswith("sqlite:///") and database_uri != "sqlite:///":
        folders.append(Path(database_uri.removeprefix("sqlite:///" )).parent)
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)


def register_error_handlers(app):
    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        template = app.jinja_env.get_template("errors/500.html")
        return template.render(), 500


def create_database(app):
    from app.services.startup_coordinator import StartupCoordinator

    # Gunicorn boots workers concurrently. Keep the existing initialization
    # contract, but serialize its small idempotent writes so two workers cannot
    # create the same seed user/setting at the same instant.
    with StartupCoordinator.acquire(app):
        with app.app_context():
            initialize_database()
            from app.services.user_vault_service import UserVaultService
            UserVaultService.reconcile()


def create_app(config_object=Config):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)
    database_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if (
        app.config.get("TESTING", False)
        and os.name == "nt"
        and database_uri.startswith("sqlite:///")
        and database_uri != "sqlite:///"
    ):
        # Windows does not allow a TemporaryDirectory to remove a SQLite file
        # while QueuePool retains an idle handle. Test-only NullPool keeps each
        # file-backed database isolated and makes teardown deterministic; the
        # production WAL/single-writer connection policy is unchanged.
        engine_options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
        engine_options["poolclass"] = NullPool
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
    create_directories(app)

    install_sqlite_connection_pragmas()
    register_extensions(app)
    configure_sqlite_runtime(app)

    install_vacancy_matcher()
    install_representative_resolver()
    install_semantic_import_discovery()
    install_dynamic_import_contract()
    install_dynamic_import_refinement()
    install_aggregate_identity_refinement()
    install_ims_summary_integrity()
    install_workbook_preflight()
    install_official_brick_spread_atomic()
    install_derived_verification_gate()
    install_previous_ims_delta_audit()
    install_import_result_reporting()
    install_manager_import_report_alignment()
    install_sqlite_import_maintenance()
    install_dashboard_runtime_optimizer()
    install_ims_upload_lifecycle()
    install_production_result_reconciliation_gate()

    register_template_context(app)
    register_blueprints(app)
    install_ims_upload_lifecycle_ui(app)
    install_production_result_retry_ui(app)
    register_access_control(app)
    register_error_handlers(app)

    if not app.config.get("TESTING", False):
        create_database(app)

    return app
