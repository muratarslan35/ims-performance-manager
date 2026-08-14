"""Create or update an admin without storing its password in source control."""

from getpass import getpass

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User
from app.services.user_vault_service import UserVaultService


def main():
    email = input("Admin e-posta: ").strip().lower()
    full_name = input("Ad soyad: ").strip()
    password = getpass("Parola (ekranda görünmez): ")
    if not email or not full_name or len(password) < 8:
        raise SystemExit("E-posta, ad soyad ve en az 8 karakterli parola zorunludur.")

    app = create_app()
    with app.app_context():
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user is None:
            user = User(email=email, full_name=full_name, password="", role="Admin")
            db.session.add(user)
        user.full_name = full_name
        user.password = generate_password_hash(password)
        user.role = "Admin"
        user.active = True
        db.session.commit()
        UserVaultService.sync_from_primary()
        print("Admin hesabı oluşturuldu ve kalıcı kullanıcı kasasına kaydedildi.")


if __name__ == "__main__":
    main()
