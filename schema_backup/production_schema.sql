CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
CREATE TABLE users (
	id INTEGER NOT NULL, 
	full_name VARCHAR(150) NOT NULL, 
	email VARCHAR(150) NOT NULL, 
	password VARCHAR(255) NOT NULL, 
	phone VARCHAR(30), 
	role VARCHAR(50) NOT NULL, 
	active BOOLEAN NOT NULL, 
	last_login DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);
CREATE TABLE products (
	id INTEGER NOT NULL, 
	product_code VARCHAR(30), 
	product_name VARCHAR(150) NOT NULL, 
	ims_name VARCHAR(200), 
	category VARCHAR(100), 
	competitor_group VARCHAR(100), 
	molecule VARCHAR(100), 
	strength VARCHAR(100), 
	dosage_form VARCHAR(100), 
	unit_price FLOAT NOT NULL, 
	display_order INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_prime_product BOOLEAN NOT NULL, 
	required_percent FLOAT NOT NULL, 
	include_total_tl BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (product_code)
);
CREATE TABLE prime_rules (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	required_percent INTEGER NOT NULL, 
	include_in_prime BOOLEAN NOT NULL, 
	include_in_total_tl BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	valid_from DATE NOT NULL, 
	valid_to DATE, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE TABLE targets (
	id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	quarter VARCHAR(5) NOT NULL, 
	representative_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	unit_target FLOAT NOT NULL, 
	tl_target FLOAT NOT NULL, 
	unit_realization FLOAT NOT NULL, 
	tl_realization FLOAT NOT NULL, 
	realization_percent FLOAT NOT NULL, 
	prime_percent FLOAT NOT NULL, 
	bonus_amount FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	CONSTRAINT uq_target_period UNIQUE (year, month, representative_id, product_id)
);
CREATE TABLE product_aliases (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	alias_name VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	CONSTRAINT uq_product_alias UNIQUE (product_id, alias_name)
);
CREATE TABLE representative_aliases (
	id INTEGER NOT NULL, 
	representative_id INTEGER NOT NULL, 
	alias_name VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	CONSTRAINT uq_representative_alias UNIQUE (representative_id, alias_name)
);
CREATE TABLE recovery_summary (
	id INTEGER NOT NULL, 
	representative_id INTEGER, 
	product_id INTEGER, 
	year INTEGER, 
	quarter INTEGER, 
	remaining_box FLOAT NOT NULL, 
	remaining_tl FLOAT NOT NULL, 
	carry_box FLOAT NOT NULL, 
	carry_tl FLOAT NOT NULL, 
	daily_need FLOAT NOT NULL, 
	projected_box FLOAT NOT NULL, 
	projected_percent FLOAT NOT NULL, 
	risk_score INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id)
);
CREATE TABLE ims_raw_data (
	id INTEGER NOT NULL, 
	upload_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	quarter VARCHAR(5) NOT NULL, 
	sheet_name VARCHAR(150) NOT NULL, 
	sheet_type VARCHAR(50) NOT NULL, 
	source_row INTEGER NOT NULL, 
	representative_id INTEGER, 
	product_id INTEGER, 
	representative VARCHAR(150), 
	manager VARCHAR(150), 
	product VARCHAR(150), 
	competitor VARCHAR(150), 
	brick VARCHAR(150), 
	market VARCHAR(150), 
	unit FLOAT NOT NULL, 
	tl FLOAT NOT NULL, 
	market_share FLOAT NOT NULL, 
	value_share FLOAT NOT NULL, 
	growth FLOAT NOT NULL, 
	raw_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, week_number INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id)
);
CREATE INDEX ix_ims_raw_period ON ims_raw_data (year, month);
CREATE INDEX ix_ims_raw_upload ON ims_raw_data (upload_id);
CREATE TABLE ims_facts (
	id INTEGER NOT NULL, 
	upload_id INTEGER NOT NULL, 
	raw_data_id INTEGER NOT NULL, 
	representative_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	quarter VARCHAR(5) NOT NULL, 
	report_type VARCHAR(50) NOT NULL, 
	unit FLOAT NOT NULL, 
	tl FLOAT NOT NULL, 
	market_share FLOAT NOT NULL, 
	value_share FLOAT NOT NULL, 
	growth FLOAT NOT NULL, 
	metrics_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, week_number INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(raw_data_id) REFERENCES ims_raw_data (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id), 
	CONSTRAINT uq_ims_fact_raw_data UNIQUE (raw_data_id)
);
CREATE INDEX ix_ims_fact_period ON ims_facts (year, month);
CREATE INDEX ix_ims_fact_rep_product ON ims_facts (representative_id, product_id);
CREATE TABLE ims_summary (
	id INTEGER NOT NULL, 
	upload_id INTEGER NOT NULL, 
	representative_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	quarter VARCHAR(5) NOT NULL, 
	unit FLOAT NOT NULL, 
	tl FLOAT NOT NULL, 
	market_share FLOAT NOT NULL, 
	value_share FLOAT NOT NULL, 
	growth FLOAT NOT NULL, 
	realization_percent FLOAT NOT NULL, 
	prime_percent FLOAT NOT NULL, 
	target_unit FLOAT NOT NULL, 
	target_tl FLOAT NOT NULL, 
	bonus_amount FLOAT NOT NULL, 
	rank INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id), 
	CONSTRAINT uq_ims_summary_period UNIQUE (year, month, representative_id, product_id)
);
CREATE INDEX ix_ims_summary_period ON ims_summary (year, month);
CREATE TABLE representative_matches (
	id INTEGER NOT NULL, 
	ims_name VARCHAR(200) NOT NULL, 
	representative_id INTEGER NOT NULL, 
	match_method VARCHAR(50) NOT NULL, 
	match_score FLOAT NOT NULL, 
	created_by VARCHAR(150), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(representative_id) REFERENCES representatives (id), 
	CONSTRAINT uq_rep_match_ims_name UNIQUE (ims_name)
);
CREATE INDEX ix_rep_match_rep_id ON representative_matches (representative_id);
CREATE TABLE product_matches (
	id INTEGER NOT NULL, 
	ims_name VARCHAR(200) NOT NULL, 
	product_id INTEGER NOT NULL, 
	match_method VARCHAR(50) NOT NULL, 
	match_score FLOAT NOT NULL, 
	created_by VARCHAR(150), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	CONSTRAINT uq_product_match_ims_name UNIQUE (ims_name)
);
CREATE INDEX ix_product_match_product_id ON product_matches (product_id);
CREATE INDEX ix_ims_fact_week ON ims_facts (year, week_number);
CREATE UNIQUE INDEX uq_ims_fact_week_period ON ims_facts (year, week_number, representative_id, product_id, report_type);
CREATE TABLE target_import_audits (
	id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	uploaded_by VARCHAR(150), 
	uploaded_at DATETIME NOT NULL, 
	rows_inserted INTEGER NOT NULL, 
	rows_updated INTEGER NOT NULL, 
	rows_skipped INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE ims_competition_data (
	id INTEGER NOT NULL, 
	upload_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	week_number INTEGER, 
	sheet_name VARCHAR(150) NOT NULL, 
	period_type VARCHAR(30) NOT NULL, 
	territory VARCHAR(150) NOT NULL, 
	subterritory VARCHAR(150) NOT NULL, 
	product_group VARCHAR(200) NOT NULL, 
	product_name VARCHAR(200) NOT NULL, 
	is_company_product BOOLEAN DEFAULT 0 NOT NULL, 
	is_competitor BOOLEAN DEFAULT 0 NOT NULL, 
	metric_type VARCHAR(30) NOT NULL, 
	metric_value FLOAT DEFAULT '0.0' NOT NULL, 
	is_subtotal BOOLEAN DEFAULT 0 NOT NULL, 
	is_grand_total BOOLEAN DEFAULT 0 NOT NULL, 
	source_row INTEGER NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id), 
	CONSTRAINT uq_competition_grain UNIQUE (upload_id, sheet_name, period_type, year, month, week_number, territory, subterritory, product_group, product_name, metric_type)
);
CREATE INDEX ix_competition_period ON ims_competition_data (year, month, week_number);
CREATE INDEX ix_competition_sheet ON ims_competition_data (sheet_name);
CREATE INDEX ix_competition_territory ON ims_competition_data (territory, subterritory);
CREATE INDEX ix_ims_competition_data_upload_id ON ims_competition_data (upload_id);
CREATE TABLE IF NOT EXISTS "audit_logs" (
	id INTEGER NOT NULL, 
	username VARCHAR(150), 
	module VARCHAR(100), 
	action VARCHAR(255) NOT NULL, 
	ip_address VARCHAR(50), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS "import_audit_logs" (
	id INTEGER NOT NULL, 
	upload_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	week_number INTEGER, 
	uploaded_by VARCHAR(150), 
	uploaded_at DATETIME NOT NULL, 
	rows_inserted INTEGER NOT NULL, 
	rows_updated INTEGER NOT NULL, 
	rows_skipped INTEGER NOT NULL, 
	rows_unmatched INTEGER NOT NULL, 
	rows_error INTEGER NOT NULL, 
	queued_for_manual INTEGER NOT NULL, 
	processing_time FLOAT NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id)
);
CREATE INDEX ix_import_audit_upload ON import_audit_logs (upload_id);
CREATE INDEX ix_import_audit_period ON import_audit_logs (year, week_number);
CREATE TABLE IF NOT EXISTS "ims_uploads" (
	id INTEGER NOT NULL, 
	file_name VARCHAR(255) NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	quarter VARCHAR(5), 
	sheet_count INTEGER NOT NULL, 
	raw_record_count INTEGER NOT NULL, 
	fact_record_count INTEGER NOT NULL, 
	summary_record_count INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	processing_time FLOAT NOT NULL, 
	uploaded_by VARCHAR(150), 
	error_message TEXT, 
	warning_message TEXT, 
	uploaded_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	week_number INTEGER, 
	PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS "manual_match_queue" (
	id INTEGER NOT NULL, 
	entity_type VARCHAR(50) NOT NULL, 
	ims_name VARCHAR(200) NOT NULL, 
	upload_id INTEGER, 
	best_candidate VARCHAR(200), 
	best_score FLOAT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	resolved_by VARCHAR(150), 
	resolved_at DATETIME, 
	created_at DATETIME NOT NULL, 
	source_value VARCHAR(255), 
	normalized_value VARCHAR(255), 
	import_id INTEGER, 
	worksheet VARCHAR(100), 
	row_number INTEGER, 
	confidence_score FLOAT DEFAULT '0' NOT NULL, 
	suggested_match VARCHAR(200), 
	reason VARCHAR(100), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_manual_match_entity UNIQUE (entity_type, ims_name), 
	FOREIGN KEY(upload_id) REFERENCES ims_uploads (id)
);
CREATE INDEX ix_match_queue_status ON manual_match_queue (status);
CREATE TABLE IF NOT EXISTS "representatives" (
	id INTEGER NOT NULL, 
	rep_code VARCHAR(30), 
	ims_code VARCHAR(30), 
	sap_code VARCHAR(30), 
	rep_name VARCHAR(150) NOT NULL, 
	region VARCHAR(100), 
	city VARCHAR(100), 
	district VARCHAR(100), 
	territory VARCHAR(150), 
	manager VARCHAR(150), 
	team VARCHAR(150), 
	email VARCHAR(150), 
	phone VARCHAR(30), 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rep_code)
);
CREATE TABLE IF NOT EXISTS "settings" (
	id INTEGER NOT NULL, 
	setting_key VARCHAR(150) NOT NULL, 
	setting_value VARCHAR(255), 
	description VARCHAR(255), 
	category VARCHAR(100) NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (setting_key)
);
