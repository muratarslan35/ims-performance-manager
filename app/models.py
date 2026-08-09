from datetime import date, datetime
from flask_login import UserMixin
from app.extensions import db

# --- RESTORED LEGACY MODELS & CONSTANTS ---
DEFAULT_SETTINGS = {
    "MAIN_PRIME": 50000,
    "CIRO_PRIME": 20000,
    "PRIME_STEP": 5,
    "STEP_AMOUNT": 2500,
    "MAX_PRIME_PERCENT": 140,
    "MIN_PRIME_PERCENT": 100,
    "TARGET_75": 75,
    "TARGET_90": 90,
    "TARGET_100": 100,
    "PRIME_PRODUCT_COUNT": 4,
    "REQUIRED_90_COUNT": 3
}

class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(150), unique=True, nullable=False)
    setting_value = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Setting {self.setting_key}={self.setting_value}>"


class PrimeRule(db.Model):
    __tablename__ = "prime_rules"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    required_percent = db.Column(db.Integer, default=0, nullable=False)
    include_in_prime = db.Column(db.Boolean, default=True, nullable=False)
    include_in_total_tl = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    valid_from = db.Column(db.Date, nullable=False, default=date.today)
    valid_to = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", backref="prime_rules")

    def __repr__(self):
        return f"<PrimeRule product_id={self.product_id}>"


# --- CORE & IMS ARCHITECTURE MODELS ---

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
    territory = db.Column(db.String(150), nullable=True)
    manager = db.Column(db.String(150), nullable=True)
    team = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Representative {self.rep_name}>"


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(30), unique=True)
    product_name = db.Column(db.String(150), nullable=False)
    ims_name = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(100))
    competitor_group = db.Column(db.String(100), nullable=True)
    molecule = db.Column(db.String(100), nullable=True)
    strength = db.Column(db.String(100), nullable=True)
    dosage_form = db.Column(db.String(100), nullable=True)
    unit_price = db.Column(db.Float, default=0.0, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_prime_product = db.Column(db.Boolean, default=False, nullable=False)
    required_percent = db.Column(db.Float, default=0.0, nullable=False)
    include_total_tl = db.Column(db.Boolean, default=True, nullable=False)
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


class RepresentativeBrickAssignment(db.Model):
    """Period-scoped brick membership; a brick may legitimately have co-workers."""

    __tablename__ = "representative_brick_assignments"
    __table_args__ = (
        db.UniqueConstraint("year", "month", "brick", "representative_id", name="uq_rep_brick_member_period"),
        db.Index("ix_rep_brick_assignment_rep_period", "representative_id", "year", "month"),
    )

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=True)
    brick = db.Column(db.String(150), nullable=False)
    territory = db.Column(db.String(150), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(20), nullable=False, default="AUTO")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref=db.backref("brick_assignments", lazy="dynamic"))


class Target(db.Model):
    __tablename__ = "targets"
    __table_args__ = (
        db.UniqueConstraint("year", "month", "representative_id", "product_id", name="uq_target_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    unit_target = db.Column(db.Float, default=0.0, nullable=False)
    tl_target = db.Column(db.Float, default=0.0, nullable=False)
    unit_realization = db.Column(db.Float, default=0.0, nullable=False)
    tl_realization = db.Column(db.Float, default=0.0, nullable=False)
    realization_percent = db.Column(db.Float, default=0.0, nullable=False)
    prime_percent = db.Column(db.Float, default=0.0, nullable=False)
    bonus_amount = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="targets")
    product = db.relationship("Product", backref="targets")

    @property
    def target_unit(self):
        """Compatibility alias used by existing target templates."""
        return self.unit_target or 0

    @target_unit.setter
    def target_unit(self, value):
        self.unit_target = value or 0

    @property
    def target_tl(self):
        """Compatibility alias used by existing target templates."""
        return self.tl_target or 0

    @target_tl.setter
    def target_tl(self, value):
        self.tl_target = value or 0


class IMSUpload(db.Model):
    __tablename__ = "ims_uploads"

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=True)
    week_number = db.Column(db.Integer)
    sheet_count = db.Column(db.Integer, default=0, nullable=False)
    raw_record_count = db.Column(db.Integer, default=0, nullable=False)
    fact_record_count = db.Column(db.Integer, default=0, nullable=False)
    summary_record_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(50), default="PENDING", nullable=False)
    processing_time = db.Column(db.Float, default=0.0, nullable=False)
    uploaded_by = db.Column(db.String(150))
    error_message = db.Column(db.Text, nullable=True)
    warning_message = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<IMSUpload {self.file_name} ({self.status})>"


class IMSRawData(db.Model):
    __tablename__ = "ims_raw_data"
    __table_args__ = (
        db.Index("ix_ims_raw_period", "year", "month"),
        db.Index("ix_ims_raw_upload", "upload_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    month = db.Column(db.Integer, nullable=True)
    quarter = db.Column(db.String(5), nullable=True)
    week_number = db.Column(db.Integer, nullable=True)
    sheet_name = db.Column(db.String(150), nullable=False)
    sheet_type = db.Column(db.String(50), nullable=True)
    source_row = db.Column(db.Integer, nullable=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    representative = db.Column(db.String(150), nullable=True)
    manager = db.Column(db.String(150), nullable=True)
    territory = db.Column(db.String(150), nullable=True)
    brick = db.Column(db.String(150), nullable=True)
    province = db.Column(db.String(100), nullable=True)
    product = db.Column(db.String(200), nullable=True)
    competitor = db.Column(db.String(200), nullable=True)
    market = db.Column(db.String(150), nullable=True)
    unit = db.Column(db.Float, default=0.0, nullable=False)
    tl = db.Column(db.Float, default=0.0, nullable=False)
    market_share = db.Column(db.Float, default=0.0, nullable=False)
    value_share = db.Column(db.Float, default=0.0, nullable=False)
    growth = db.Column(db.Float, default=0.0, nullable=False)
    raw_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="raw_data")


class IMSFact(db.Model):
    __tablename__ = "ims_facts"
    __table_args__ = (
        db.UniqueConstraint("year", "week_number", "representative_id", "product_id", "report_type", name="uq_ims_fact_week_period"),
        db.Index("ix_ims_fact_period", "year", "month"),
        db.Index("ix_ims_fact_rep_product", "representative_id", "product_id"),
        db.Index("ix_ims_fact_week", "year", "week_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=False)
    raw_data_id = db.Column(db.Integer, db.ForeignKey("ims_raw_data.id"), nullable=False)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=True)
    week_number = db.Column(db.Integer)
    report_type = db.Column(db.String(50), nullable=True)
    unit = db.Column(db.Float, default=0.0, nullable=False)
    tl = db.Column(db.Float, default=0.0, nullable=False)
    market_share = db.Column(db.Float, default=0.0, nullable=False)
    value_share = db.Column(db.Float, default=0.0, nullable=False)
    growth = db.Column(db.Float, default=0.0, nullable=False)
    metrics_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    upload = db.relationship("IMSUpload", backref="facts")
    representative = db.relationship("Representative", backref="ims_facts")
    product = db.relationship("Product", backref="ims_facts")


class IMSSummary(db.Model):
    __tablename__ = "ims_summary"
    __table_args__ = (
        db.UniqueConstraint("year", "month", "representative_id", "product_id", name="uq_ims_summary_period"),
        db.Index("ix_ims_summary_period", "year", "month"),
    )

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.String(5), nullable=True)
    unit = db.Column(db.Float, default=0.0, nullable=False)
    tl = db.Column(db.Float, default=0.0, nullable=False)
    market_share = db.Column(db.Float, default=0.0, nullable=False)
    value_share = db.Column(db.Float, default=0.0, nullable=False)
    growth = db.Column(db.Float, default=0.0, nullable=False)
    realization_percent = db.Column(db.Float, default=0.0, nullable=False)
    prime_percent = db.Column(db.Float, default=0.0, nullable=False)
    target_unit = db.Column(db.Float, default=0.0, nullable=False)
    target_tl = db.Column(db.Float, default=0.0, nullable=False)
    bonus_amount = db.Column(db.Float, default=0.0, nullable=False)
    rank = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(50), nullable=False, default="ACTIVE")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="summaries")
    product = db.relationship("Product", backref="summaries")


class ProductMatch(db.Model):
    __tablename__ = "product_matches"

    id = db.Column(db.Integer, primary_key=True)
    ims_name = db.Column(db.String(200), nullable=False, unique=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    match_method = db.Column(db.String(50), nullable=True)
    match_score = db.Column(db.Float, default=0.0, nullable=False)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", backref="matches")


class RepresentativeMatch(db.Model):
    __tablename__ = "representative_matches"

    id = db.Column(db.Integer, primary_key=True)
    ims_name = db.Column(db.String(150), nullable=False, unique=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"), nullable=False)
    match_method = db.Column(db.String(50), nullable=True)
    match_score = db.Column(db.Float, default=0.0, nullable=False)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    representative = db.relationship("Representative", backref="matches")


class ManualMatchQueue(db.Model):
    __tablename__ = "manual_match_queue"
    __table_args__ = (
        db.UniqueConstraint("entity_type", "ims_name", name="uq_manual_match_entity"),
        db.Index("ix_match_queue_status", "status"),
    )

    STATUS_PENDING = "PENDING"
    STATUS_RESOLVED = "RESOLVED"
    STATUS_IGNORED = "IGNORED"

    ENTITY_REPRESENTATIVE = "REPRESENTATIVE"
    ENTITY_PRODUCT = "PRODUCT"
    ENTITY_REGION = "REGION"
    ENTITY_PROVINCE = "PROVINCE"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False)
    ims_name = db.Column(db.String(200), nullable=False)
    upload_id = db.Column(db.Integer, db.ForeignKey("ims_uploads.id"), nullable=True)
    source_value = db.Column(db.String(255), nullable=True)
    normalized_value = db.Column(db.String(255), nullable=True)
    import_id = db.Column(db.Integer, nullable=True)
    worksheet = db.Column(db.String(100), nullable=True)
    row_number = db.Column(db.Integer, nullable=True)
    confidence_score = db.Column(db.Float, default=0.0, nullable=False)
    suggested_match = db.Column(db.String(200), nullable=True)
    reason = db.Column(db.String(100), nullable=True)
    best_candidate = db.Column(db.String(200), nullable=True)
    best_score = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), default="PENDING", nullable=False)
    resolved_by = db.Column(db.String(150), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
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
    status = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    upload = db.relationship("IMSUpload", backref="audit_logs")


class RecoverySummary(db.Model):
    __tablename__ = "recovery_summary"

    id = db.Column(db.Integer, primary_key=True)
    representative_id = db.Column(db.Integer, db.ForeignKey("representatives.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    year = db.Column(db.Integer)
    quarter = db.Column(db.Integer)
    remaining_box = db.Column(db.Float, default=0.0)
    remaining_tl = db.Column(db.Float, default=0.0)
    carry_box = db.Column(db.Float, default=0.0)
    carry_tl = db.Column(db.Float, default=0.0)
    daily_need = db.Column(db.Float, default=0.0)
    projected_box = db.Column(db.Float, default=0.0)
    projected_percent = db.Column(db.Float, default=0.0)
    risk_score = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    representative = db.relationship("Representative", backref="recovery_summaries")
    product = db.relationship("Product", backref="recovery_summaries")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=True)
    module = db.Column(db.String(100), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# --- COMPETITION IMPORT FEATURE (NOT IN PRODUCTION MIGRATION) ---
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
