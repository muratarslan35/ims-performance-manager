from app.extensions import db, login_manager
from app.models import User


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def init_app(app):
    login_manager.init_app(app)
