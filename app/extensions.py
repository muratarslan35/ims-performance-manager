from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

migrate = Migrate()

login_manager = LoginManager()

login_manager.login_view = "auth.login"

login_manager.login_message = "Lütfen giriş yapınız."

login_manager.login_message_category = "warning"

login_manager.session_protection = "strong"

login_manager.refresh_view = "auth.login"
