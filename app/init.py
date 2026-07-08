from flask import Flask

from config import Config

from app.extensions import db
from app.extensions import login_manager

from app.routes import main_bp


def create_app():

    app = Flask(__name__)

    app.config.from_object(Config)

    db.init_app(app)

    login_manager.init_app(app)

    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    return app
