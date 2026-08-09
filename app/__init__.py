from flask import Flask
from flask import render_template
from pathlib import Path

from config import Config

from app.extensions import db
from app.extensions import migrate
from app.extensions import login_manager

import app.login_manager

from app.database import initialize_database

from app.routes import main_bp
from app.auth import auth_bp
from app.products import products_bp
from app.routes.settings import settings_bp
from app.routes.targets import targets_bp
from app.routes.matching import matching_bp
from app.competition.api import competition_bp
from app.ims import ims_bp
from app.dashboard import dashboard_bp
from app.representatives import representatives_bp
from app.simulation import simulation_bp

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

    app.register_blueprint(dashboard_bp)

    app.register_blueprint(representatives_bp)

    app.register_blueprint(simulation_bp)


def create_directories(app):

    folders = [

        app.config["UPLOAD_FOLDER"],

        app.config["REPORT_FOLDER"],

        app.config["BACKUP_FOLDER"],

        app.config["LOG_FOLDER"]

    ]

    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]

    if database_uri.startswith("sqlite:///") and database_uri != "sqlite:///":

        folders.append(
            Path(database_uri.removeprefix("sqlite:///" )).parent
        )

    for folder in folders:

        folder.mkdir(
            parents=True,
            exist_ok=True
        )


def register_error_handlers(app):

    @app.errorhandler(404)
    def page_not_found(error):

        return render_template(
            "errors/404.html"
        ), 404


    @app.errorhandler(500)
    def internal_error(error):

        return render_template(
            "errors/500.html"
        ), 500


def create_database(app):

    with app.app_context():

        initialize_database()


def create_app(config_object=Config):

    app = Flask(

        __name__,

        template_folder="templates",

        static_folder="static"

    )

    app.config.from_object(config_object)

    create_directories(app)

    register_extensions(app)

    register_blueprints(app)

    register_error_handlers(app)

    if not app.config.get("TESTING", False):
        create_database(app)

    return app
