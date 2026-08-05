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
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Representative {self.rep_name}>"


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(50), unique=True)
    product_name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(100))
    category = db.Column(db.String(100))
    is_company_product = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Product {self.product_name}>"


class ProductAlias(db.Model):
    __tablename__ = "product_aliases"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    alias_name = db.Column(db.String(200), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", backref=db.backref("aliases", lazy="dynamic"))


class RepresentativeAlias(db.Model):
    __tablename__ = "representative_aliases"

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    alias_name = db.Column(db.String(150), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref=db.backref("aliases", lazy="dynamic"))


class Target(db.Model):
    __tablename__ = "targets"

    __table_args__ = (
        db.UniqueConstraint("representative_id", "product_id", "year", "month", name="uq_representative_product_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    target_units = db.Column(db.Float, default=0.0, nullable=False)
    target_revenue = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="targets")
    product = db.relationship("Product", backref="targets")


class IMSUpload(db.Model):
    __tablename__ = "ims_uploads"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer)
    status = db.Column(db.String(50), default="PENDING", nullable=False)
    uploaded_by = db.Column(db.String(150))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    row_count = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<IMSUpload {self.filename} ({self.status})>"


class IMSRawData(db.Model):
    __tablename__ = "ims_raw_data"

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False)
    row_index = db.Column(db.Integer, nullable=False)
    raw_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="raw_data")


class IMSFact(db.Model):
    __tablename__ = "ims_facts"

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer)
    brick_code = db.Column(db.String(50))
    brick_name = db.Column(db.String(150))
    units = db.Column(db.Float, default=0.0, nullable=False)
    revenue = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="facts")
    representative = db.relationship("Representative", backref="ims_facts")
    product = db.relationship("Product", backref="ims_facts")


class IMSSummary(db.Model):
    __tablename__ = "ims_summaries"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    total_units = db.Column(db.Float, default=0.0, nullable=False)
    total_revenue = db.Column(db.Float, default=0.0, nullable=False)
    realization_rate = db.Column(db.Float, default=0.0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="summaries")
    product = db.relationship("Product", backref="summaries")


class ProductMatch(db.Model):
    __tablename__ = "product_matches"

    id = db.Column(db.Integer, primary_key=True)
    raw_name = db.Column(db.String(200), nullable=False, unique=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    match_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", backref="matches")


class RepresentativeMatch(db.Model):
    __tablename__ = "representative_matches"

    id = db.Column(db.Integer, primary_key=True)
    raw_name = db.Column(db.String(150), nullable=False, unique=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    match_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="matches")


class ManualMatchQueue(db.Model):
    __tablename__ = "manual_match_queue"

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)  # 'product' or 'representative'
    raw_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default="PENDING", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="manual_queue_items")


class TargetImportAudit(db.Model):
    __tablename__ = "target_import_audits"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(db.String(150))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rows_inserted = db.Column(db.Integer, default=0, nullable=False)
    rows_updated = db.Column(db.Integer, default=0, nullable=False)
    rows_skipped = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(50), default="SUCCESS", nullable=False)


class ImportAuditLog(db.Model):
    """Per-import audit record capturing counts, actors, and outcomes."""

    __tablename__ = "import_audit_logs"
    __table_args__ = (
        db.Index("ix_import_audit_upload", "upload_id"),
        db.Index("ix_import_audit_period", "year", "week_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer)
    uploaded_by = db.Column(db.String(150))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rows_inserted = db.Column(db.Integer, default=0, nullable=False)
    rows_updated = db.Column(db.Integer, default=0, nullable=False)
    rows_skipped = db.Column(db.Integer, default=0, nullable=False)
    rows_unmatched = db.Column(db.Integer, default=0, nullable=False)
    rows_error = db.Column(db.Integer, default=0, nullable=False)
    queued_for_manual = db.Column(db.Integer, default=0, nullable=False)
    processing_time = db.Column(db.Float, default=0.0, nullable=False)
    success = db.Column(db.Boolean, default=True, nullable=False)
    error_message = db.Column(db.Text)

    upload = db.relationship("IMSUpload", backref="audit_logs")


class CompetitionData(db.Model):
    """Normalized store for market, weekly/monthly units, values, and competitor IMS data."""

    __tablename__ = "ims_competition_data"
    
    __table_args__ = (
        db.UniqueConstraint(
            "upload_id",
            "sheet_name",
            "period_type",
            "year",
            "month",
            "week_number",
            "territory",
            "subterritory",
            "product_group",
            "product_name",
            "metric_type",
            name="uq_competition_grain",
        ),
        db.Index("ix_competition_period", "year", "month", "week_number"),
        db.Index("ix_competition_sheet", "sheet_name"),
        db.Index("ix_competition_territory", "territory", "subterritory"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False, index=True)
    
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer, nullable=True)
    sheet_name = db.Column(db.String(150), nullable=False)
    period_type = db.Column(db.String(30), nullable=False)
    
    territory = db.Column(db.String(150), nullable=False)
    subterritory = db.Column(db.String(150), nullable=False)
    
    product_group = db.Column(db.String(200), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    
    is_company_product = db.Column(db.Boolean, server_default=db.false(), default=False, nullable=False)
    is_competitor = db.Column(db.Boolean, server_default=db.false(), default=False, nullable=False)
    
    metric_type = db.Column(db.String(30), nullable=False)
    metric_value = db.Column(db.Float, server_default="0.0", default=0.0, nullable=False)
    
    is_subtotal = db.Column(db.Boolean, server_default=db.false(), default=False, nullable=False)
    is_grand_total = db.Column(db.Boolean, server_default=db.false(), default=False, nullable=False)
    
    source_row = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp(), default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="competition_records")

    def __repr__(self):
        return f"<CompetitionData {self.sheet_name}:{self.product_name}={self.metric_value}>"
