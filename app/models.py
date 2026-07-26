from datetime import date, datetime

from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    role = db.Column(db.String(50), default="Representative", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<User {self.full_name}>"


class Representative(db.Model):
    __tablename__ = "representatives"

    id = db.Column(db.Integer, primary_key=True)
    rep_code = db.Column(db.String(30), unique=True)
    ims_code = db.Column(db.String(30))
    sap_code = db.Column(db.String(30))
    rep_name = db.Column(db.String(150), nullable=False)
    region = db.Column(db.String(100))
    city = db.Column(db.String(100))
    district = db.Column(db.String(100))
    territory = db.Column(db.String(100))
    manager = db.Column(db.String(120))
    team = db.Column(db.String(100))
    email = db.Column(db.String(150))
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Representative {self.rep_name}>"


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(30), unique=True)
    product_name = db.Column(db.String(150), nullable=False)
    ims_name = db.Column(db.String(200))
    category = db.Column(db.String(100))
    competitor_group = db.Column(db.String(100))
    molecule = db.Column(db.String(100))
    strength = db.Column(db.String(100))
    dosage_form = db.Column(db.String(100))
    unit_price = db.Column(db.Float, default=0, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_prime_product = db.Column(db.Boolean, default=False, nullable=False)
    required_percent = db.Column(db.Float, default=0, nullable=False)
    include_total_tl = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Product {self.product_name}>"


class Target(db.Model):
    __tablename__ = "targets"
    __table_args__ = (
        db.UniqueConstraint(
            "year", "month", "representative_id", "product_id", name="uq_target_period"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=False, default="Q1")
    representative_id = db.Column(
        db.Integer, db.ForeignKey("representatives.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    unit_target = db.Column(db.Float, default=0, nullable=False)
    tl_target = db.Column(db.Float, default=0, nullable=False)
    unit_realization = db.Column(db.Float, default=0, nullable=False)
    tl_realization = db.Column(db.Float, default=0, nullable=False)
    realization_percent = db.Column(db.Float, default=0, nullable=False)
    prime_percent = db.Column(db.Float, default=0, nullable=False)
    bonus_amount = db.Column(db.Float, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative")
    product = db.relationship("Product")

    @property
    def target_unit(self):
        return self.unit_target

    @target_unit.setter
    def target_unit(self, value):
        self.unit_target = value

    @property
    def target_tl(self):
        return self.tl_target

    @target_tl.setter
    def target_tl(self, value):
        self.tl_target = value


class IMSUpload(db.Model):
    __tablename__ = "ims_uploads"

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=False)
    sheet_count = db.Column(db.Integer, default=0, nullable=False)
    raw_record_count = db.Column(db.Integer, default=0, nullable=False)
    fact_record_count = db.Column(db.Integer, default=0, nullable=False)
    summary_record_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(30), default="PROCESSING", nullable=False)
    processing_time = db.Column(db.Float, default=0, nullable=False)
    uploaded_by = db.Column(db.String(120))
    error_message = db.Column(db.Text)
    warning_message = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<IMSUpload {self.file_name}>"


class IMSRawData(db.Model):
    """Immutable staging records created directly from an IMS workbook."""

    __tablename__ = "ims_raw_data"
    __table_args__ = (
        db.Index("ix_ims_raw_period", "year", "month"),
        db.Index("ix_ims_raw_upload", "upload_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=False)
    sheet_name = db.Column(db.String(150), nullable=False)
    sheet_type = db.Column(db.String(50), nullable=False, default="unknown")
    source_row = db.Column(db.Integer, nullable=False)

    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    representative = db.Column(db.String(150))
    manager = db.Column(db.String(150))
    product = db.Column(db.String(150))
    competitor = db.Column(db.String(150))
    brick = db.Column(db.String(150))
    market = db.Column(db.String(150))

    unit = db.Column(db.Float, default=0, nullable=False)
    tl = db.Column(db.Float, default=0, nullable=False)
    market_share = db.Column(db.Float, default=0, nullable=False)
    value_share = db.Column(db.Float, default=0, nullable=False)
    growth = db.Column(db.Float, default=0, nullable=False)
    raw_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="raw_records")
    representative_ref = db.relationship("Representative")
    product_ref = db.relationship("Product")

    def __repr__(self):
        return f"<IMSRawData {self.sheet_name}:{self.source_row}>"


class IMSFact(db.Model):
    """Validated and matched IMS facts transformed from IMSRawData."""

    __tablename__ = "ims_facts"
    __table_args__ = (
        db.UniqueConstraint("raw_data_id", name="uq_ims_fact_raw_data"),
        db.Index("ix_ims_fact_period", "year", "month"),
        db.Index("ix_ims_fact_rep_product", "representative_id", "product_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    raw_data_id = db.Column(db.Integer, db.ForeignKey("ims_raw_data.id"), nullable=False)
    representative_id = db.Column(
        db.Integer, db.ForeignKey("representatives.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=False)
    report_type = db.Column(db.String(50), nullable=False)
    unit = db.Column(db.Float, default=0, nullable=False)
    tl = db.Column(db.Float, default=0, nullable=False)
    market_share = db.Column(db.Float, default=0, nullable=False)
    value_share = db.Column(db.Float, default=0, nullable=False)
    growth = db.Column(db.Float, default=0, nullable=False)
    metrics_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="fact_records")
    raw_data = db.relationship("IMSRawData", backref=db.backref("fact_record", uselist=False))
    representative = db.relationship("Representative")
    product = db.relationship("Product")

    def __repr__(self):
        return f"<IMSFact {self.representative_id}:{self.product_id}>"


class IMSSummary(db.Model):
    """Period aggregate produced exclusively from validated IMSFact records."""

    __tablename__ = "ims_summary"
    __table_args__ = (
        db.UniqueConstraint(
            "year", "month", "representative_id", "product_id", name="uq_ims_summary_period"
        ),
        db.Index("ix_ims_summary_period", "year", "month"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    representative_id = db.Column(
        db.Integer, db.ForeignKey("representatives.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=False)
    unit = db.Column(db.Float, default=0, nullable=False)
    tl = db.Column(db.Float, default=0, nullable=False)
    market_share = db.Column(db.Float, default=0, nullable=False)
    value_share = db.Column(db.Float, default=0, nullable=False)
    growth = db.Column(db.Float, default=0, nullable=False)
    realization_percent = db.Column(db.Float, default=0, nullable=False)
    prime_percent = db.Column(db.Float, default=0, nullable=False)
    target_unit = db.Column(db.Float, default=0, nullable=False)
    target_tl = db.Column(db.Float, default=0, nullable=False)
    bonus_amount = db.Column(db.Float, default=0, nullable=False)
    rank = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(30), default="READY", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="summaries")
    representative = db.relationship("Representative")
    product = db.relationship("Product")

    def __repr__(self):
        return f"<IMSSummary {self.year}-{self.month}:{self.id}>"


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(120), unique=True, nullable=False)
    setting_value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    category = db.Column(db.String(100), default="Genel", nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self):
        return f"<Setting {self.setting_key}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150))
    module = db.Column(db.String(100))
    action = db.Column(db.String(255))
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuditLog {self.id}>"


class ProductAlias(db.Model):
    __tablename__ = "product_aliases"
    __table_args__ = (
        db.UniqueConstraint("product_id", "alias_name", name="uq_product_alias"),
    )

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    alias_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    product = db.relationship("Product", backref="aliases")

    def __repr__(self):
        return f"<ProductAlias {self.alias_name}>"


class PrimeRule(db.Model):
    __tablename__ = "prime_rules"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    required_percent = db.Column(db.Integer, nullable=False, default=90)
    include_in_prime = db.Column(db.Boolean, default=True, nullable=False)
    include_in_total_tl = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    valid_from = db.Column(db.Date, default=date.today, nullable=False)
    valid_to = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    product = db.relationship("Product", backref="prime_rules")

    def __repr__(self):
        return f"<PrimeRule {self.product_id}>"


class RepresentativeAlias(db.Model):
    __tablename__ = "representative_aliases"
    __table_args__ = (
        db.UniqueConstraint("representative_id", "alias_name", name="uq_representative_alias"),
    )

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(
        db.Integer, db.ForeignKey("representatives.id"), nullable=False
    )
    alias_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    representative = db.relationship("Representative", backref="aliases")

    def __repr__(self):
        return f"<RepresentativeAlias {self.alias_name}>"


class RecoverySummary(db.Model):
    __tablename__ = "recovery_summary"

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    year = db.Column(db.Integer)
    quarter = db.Column(db.Integer)
    remaining_box = db.Column(db.Float, default=0, nullable=False)
    remaining_tl = db.Column(db.Float, default=0, nullable=False)
    carry_box = db.Column(db.Float, default=0, nullable=False)
    carry_tl = db.Column(db.Float, default=0, nullable=False)
    daily_need = db.Column(db.Float, default=0, nullable=False)
    projected_box = db.Column(db.Float, default=0, nullable=False)
    projected_percent = db.Column(db.Float, default=0, nullable=False)
    risk_score = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(30), default="Takip", nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    representative = db.relationship("Representative")
    product = db.relationship("Product")

    def __repr__(self):
        return f"<RecoverySummary {self.id}>"
