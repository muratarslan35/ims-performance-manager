from datetime import datetime

from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(120), nullable=False)

    email = db.Column(db.String(120), unique=True, nullable=False)

    password = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(30), default="Representative")

    active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Representative(db.Model):

    __tablename__ = "representatives"

    id = db.Column(db.Integer, primary_key=True)

    rep_code = db.Column(db.String(20))

    rep_name = db.Column(db.String(120), nullable=False)

    region = db.Column(db.String(120))

    manager = db.Column(db.String(120))

    active = db.Column(db.Boolean, default=True)


class Product(db.Model):

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)

    product_name = db.Column(db.String(120), nullable=False)

    category = db.Column(db.String(100))

    prime_product = db.Column(db.Boolean, default=False)

    active = db.Column(db.Boolean, default=True)


class ProductPrice(db.Model):

    __tablename__ = "product_prices"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id")
    )

    unit_price = db.Column(db.Float)

    start_date = db.Column(db.Date)

    end_date = db.Column(db.Date)

    product = db.relationship("Product")

class Target(db.Model):

    __tablename__ = "targets"

    id = db.Column(db.Integer, primary_key=True)

    year = db.Column(db.Integer, nullable=False)

    month = db.Column(db.Integer, nullable=False)

    quarter = db.Column(db.String(5))

    representative_id = db.Column(
        db.Integer,
        db.ForeignKey("representatives.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    unit_target = db.Column(db.Float, default=0)

    tl_target = db.Column(db.Float, default=0)

    unit_realization = db.Column(db.Float, default=0)

    tl_realization = db.Column(db.Float, default=0)

    realization_percent = db.Column(db.Float, default=0)

    representative = db.relationship("Representative")

    product = db.relationship("Product")


class IMSUpload(db.Model):

    __tablename__ = "ims_uploads"

    id = db.Column(db.Integer, primary_key=True)

    file_name = db.Column(db.String(255))

    year = db.Column(db.Integer)

    month = db.Column(db.Integer)

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class Setting(db.Model):

    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)

    setting_key = db.Column(db.String(120), unique=True)

    setting_value = db.Column(db.String(255))


class AuditLog(db.Model):

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    action = db.Column(db.String(255))

    username = db.Column(db.String(120))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
