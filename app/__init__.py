from flask import Flask
from pathlib import Path

from config import Config
from app.extensions import db, migrate, login_manager
import app.login_manager

from app.database import initialize_database
BASE_DIR = Path(__file__).resolve().parent


def register_blueprints(app):
    from app.routes import main_bp

    app.register_blueprint(main_bp)


def register_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)


def create_directories(app):
    folders = [
        app.config["UPLOAD_FOLDER"],
        app.config["REPORT_FOLDER"],
        app.config["BACKUP_FOLDER"],
        app.config["LOG_FOLDER"],
    ]

    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)


def create_database(app):

    with app.app_context():

        initialize_database()


def create_app():

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config.from_object(Config)

    create_directories(app)

    register_extensions(app)

    register_blueprints(app)

    create_database(app)

    return app

from flask import render_template


def register_error_handlers(app):

    @app.errorhandler(404)
    def page_not_found(error):
        return (
            render_template(
                "errors/404.html"
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error):
        return (
            render_template(
                "errors/500.html"
            ),
            500,
        )


def create_app():

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config.from_object(Config)

    create_directories(app)

    register_extensions(app)

    register_blueprints(app)

    register_error_handlers(app)

    create_database(app)

    return app
