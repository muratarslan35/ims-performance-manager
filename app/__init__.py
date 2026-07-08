from flask import Flask
from flask import render_template

from config import Config

from app.extensions import db
from app.extensions import migrate
from app.extensions import login_manager

import app.login_manager

from app.database import initialize_database

from app.routes import main_bp
from app.auth import auth_bp
from app.products import products_bp
from app.targets import targets_bp
from app.ims import ims_bp
from app.dashboard import dashboard_bp

def register_extensions(app):

    db.init_app(app)

    migrate.init_app(app, db)

    login_manager.init_app(app)


def register_blueprints(app):

    app.register_blueprint(main_bp)

    app.register_blueprint(auth_bp)

    app.register_blueprint(products_bp)

    app.register_blueprint(targets_bp)

    app.register_blueprint(ims_bp)

    app.register_blueprint(dashboard_bp)


def create_directories(app):

    folders = [

        app.config["UPLOAD_FOLDER"],

        app.config["REPORT_FOLDER"],

        app.config["BACKUP_FOLDER"],

        app.config["LOG_FOLDER"]

    ]

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
