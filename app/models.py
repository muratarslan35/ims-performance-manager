from datetime import datetime

from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    full_name = db.Column(
        db.String(150),
        nullable=False
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    phone = db.Column(
        db.String(30)
    )

    role = db.Column(
        db.String(50),
        default="Representative"
    )

    active = db.Column(
        db.Boolean,
        default=True
    )

    last_login = db.Column(
        db.DateTime
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):

        return f"<User {self.full_name}>"


class Representative(db.Model):

    __tablename__ = "representatives"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    rep_code = db.Column(
        db.String(30),
        unique=True
    )

    ims_code = db.Column(
        db.String(30)
    )

    sap_code = db.Column(
        db.String(30)
    )

    rep_name = db.Column(
        db.String(150),
        nullable=False
    )

    region = db.Column(
        db.String(100)
    )

    city = db.Column(
        db.String(100)
    )

    district = db.Column(
        db.String(100)
    )

    manager = db.Column(
        db.String(120)
    )

    team = db.Column(
        db.String(100)
    )

    territory = db.Column(
        db.String(100)
    )

    email = db.Column(
        db.String(150)
    )

    phone = db.Column(
        db.String(30)
    )

    active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):

        return f"<Representative {self.rep_name}>"


class Product(db.Model):

    __tablename__ = "products"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    product_code = db.Column(
        db.String(30),
        unique=True
    )

    product_name = db.Column(
        db.String(150),
        nullable=False
    )

    ims_name = db.Column(
        db.String(200)
    )

    category = db.Column(
        db.String(100)
    )

    competitor_group = db.Column(
        db.String(100)
    )

    molecule = db.Column(
        db.String(100)
    )

    strength = db.Column(
        db.String(100)
    )

    dosage_form = db.Column(
        db.String(100)
    )

    unit_price = db.Column(
        db.Float,
        default=0
    )

    is_prime_product = db.Column(
        db.Boolean,
        default=False
    )

    display_order = db.Column(
        db.Integer,
        default=0
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):

        return f"<Product {self.product_name}>"


class Target(db.Model):

    __tablename__ = "targets"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    year = db.Column(
        db.Integer,
        nullable=False
    )

    month = db.Column(
        db.Integer,
        nullable=False
    )

    quarter = db.Column(
        db.String(5),
        nullable=False
    )

    representative_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "representatives.id"
        ),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "products.id"
        ),
        nullable=False
    )

    representative = db.relationship(
        "Representative"
    )

    product = db.relationship(
        "Product"
    )

    unit_target = db.Column(
        db.Float,
        default=0
    )

    tl_target = db.Column(
        db.Float,
        default=0
    )

    unit_realization = db.Column(
        db.Float,
        default=0
    )

    tl_realization = db.Column(
        db.Float,
        default=0
    )

    realization_percent = db.Column(
        db.Float,
        default=0
    )

    prime_percent = db.Column(
        db.Float,
        default=0
    )

    bonus_amount = db.Column(
        db.Float,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

class IMSUpload(db.Model):

    __tablename__ = "ims_uploads"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    file_name = db.Column(
        db.String(255),
        nullable=False
    )

    year = db.Column(
        db.Integer
    )

    month = db.Column(
        db.Integer
    )

    quarter = db.Column(
        db.String(5)
    )

    sheet_count = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(30),
        default="Yüklendi"
    )

    processing_time = db.Column(
        db.Float,
        default=0
    )

    uploaded_by = db.Column(
        db.String(120)
    )

    error_message = db.Column(
        db.Text
    )

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):

        return f"<IMSUpload {self.file_name}>"


class IMSRawData(db.Model):

    __tablename__ = "ims_raw_data"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    upload_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "ims_uploads.id"
        )
    )

    sheet_name = db.Column(
        db.String(150)
    )

    representative = db.Column(
        db.String(150)
    )

    manager = db.Column(
        db.String(150)
    )

    product = db.Column(
        db.String(150)
    )

    competitor = db.Column(
        db.String(150)
    )

    brick = db.Column(
        db.String(150)
    )

    market = db.Column(
        db.String(150)
    )

    unit = db.Column(
        db.Float,
        default=0
    )

    tl = db.Column(
        db.Float,
        default=0
    )

    market_share = db.Column(
        db.Float,
        default=0
    )

    value_share = db.Column(
        db.Float,
        default=0
    )

    growth = db.Column(
        db.Float,
        default=0
    )

    source_row = db.Column(
        db.Integer
    )

    raw_json = db.Column(
        db.Text
    )

    upload = db.relationship(
        "IMSUpload"
    )


class IMSSummary(db.Model):

    __tablename__ = "ims_summary"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    upload_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "ims_uploads.id"
        )
    )

    representative_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "representatives.id"
        )
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "products.id"
        )
    )

    year = db.Column(
        db.Integer
    )

    month = db.Column(
        db.Integer
    )

    quarter = db.Column(
        db.String(5)
    )

    unit = db.Column(
        db.Float,
        default=0
    )

    tl = db.Column(
        db.Float,
        default=0
    )

    market_share = db.Column(
        db.Float,
        default=0
    )

    realization_percent = db.Column(
        db.Float,
        default=0
    )

    prime_percent = db.Column(
        db.Float,
        default=0
    )

    target_unit = db.Column(
        db.Float,
        default=0
    )

    target_tl = db.Column(
        db.Float,
        default=0
    )

    bonus_amount = db.Column(
        db.Float,
        default=0
    )

    rank = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(30),
        default="Hazır"
    )

    upload = db.relationship(
        "IMSUpload"
    )

    representative = db.relationship(
        "Representative"
    )

    product = db.relationship(
        "Product"
    )

class Setting(db.Model):

    __tablename__ = "settings"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    setting_key = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    setting_value = db.Column(
        db.String(255)
    )

    description = db.Column(
        db.String(255)
    )

    category = db.Column(
        db.String(100),
        default="Genel"
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def __repr__(self):

        return f"<Setting {self.setting_key}>"


class AuditLog(db.Model):

    __tablename__ = "audit_logs"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(150)
    )

    module = db.Column(
        db.String(100)
    )

    action = db.Column(
        db.String(255)
    )

    ip_address = db.Column(
        db.String(50)
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):

        return f"<AuditLog {self.id}>"


class ProductAlias(db.Model):

    __tablename__ = "product_aliases"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "products.id"
        ),
        nullable=False
    )

    alias_name = db.Column(
        db.String(200),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    product = db.relationship(
        "Product"
    )

    def __repr__(self):

        return f"<ProductAlias {self.alias_name}>"


class RepresentativeAlias(db.Model):

    __tablename__ = "representative_aliases"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    representative_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "representatives.id"
        ),
        nullable=False
    )

    alias_name = db.Column(
        db.String(200),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    representative = db.relationship(
        "Representative"
    )

    def __repr__(self):

        return f"<RepresentativeAlias {self.alias_name}>"
