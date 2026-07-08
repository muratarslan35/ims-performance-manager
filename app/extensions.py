from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

migrate = Migrate()

login_manager = LoginManager()

login_manager.login_view = "main.login"

login_manager.login_message = "Please login first."

login_manager.login_message_category = "warning"
