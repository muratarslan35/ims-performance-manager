# Repository Analysis Baseline

## Architecture Map
- **Application entry**: `run.py` creates Flask app via `app.create_app`.
- **Composition root**: `app/__init__.py` registers extensions (`db`, `migrate`, auth) and blueprints (`ims`, `dashboard`, `products`, `representatives`, etc.).
- **Schema + ORM**: `app/models.py` defines core entities: `IMSUpload`, `IMSRawData`, `IMSFact`, `IMSSummary`, match tables, and business models (`Product`, `Representative`, `Target`).
- **Database bootstrap**: `app/database.py` enforces migration-first schema checks and seeds defaults; no runtime schema creation.
- **Import pipeline**: `app/services/ims_import_service.py` performs ETL in 3 stages:
  1. workbook analysis/staging (`IMSRawData`)
  2. transformation/matching (`IMSFact`)
  3. aggregation (`IMSSummary`)
- **Matching layer**: `app/services/alias_service.py` resolves representative/product labels (match table → exact/alias/contains/similarity → manual queue).
- **Read/report layer**:
  - dashboard: `app/dashboard.py` + `app/services/dashboard_service.py`
  - prime/simulation use `IMSSummary`: `app/prime_engine.py`, `app/prime_simulator.py`, `app/recovery_engine.py`, `app/quarter_engine.py`

## Dependency Map (Import-Critical)
- `app/ims.py` → `IMSImportService`
- `IMSImportService` → `pandas`, `AliasService`, ORM models (`IMSUpload`, `IMSRawData`, `IMSFact`, `IMSSummary`, `ImportAuditLog`, `Target`)
- `AliasService` → `Product`, `Representative`, alias/match models, `ManualMatchQueue`
- Reporting/prime modules consume **only** persisted data (`IMSUpload`, `IMSSummary`, `Target`, `RecoverySummary`) and are decoupled from parser implementation details.

## Data Flow Map (Upload → Parse → Persist → Dashboard/Prime/Report)
1. **Upload**
   - `POST /ims/upload` (`app/ims.py`) saves file and runs `IMSImportService.run(year, month, clear_before_import=True)`.
2. **Parse / Analyze**
   - Workbook loaded with `pd.read_excel(..., sheet_name=None, header=None)`.
   - Header row detected, headers normalized, representative/product/metric columns inferred.
3. **Persist Stage-1 (Raw)**
   - Parsed rows written to `IMSRawData` with traceable `raw_json`, sheet metadata, source row number.
4. **Persist Stage-2 (Fact)**
   - Matched rows transformed/upserted into `IMSFact` keyed by period/week+rep+product+report type.
5. **Persist Stage-3 (Summary)**
   - Monthly aggregate rebuilt into `IMSSummary`.
6. **Consumption**
   - Dashboard reads `IMSUpload` statistics and other aggregate/read models.
   - Prime/simulation engines read `IMSSummary` + `Target`.
   - Reports UI layer is template-driven and downstream of `IMSSummary`.

## Gap List (Prioritized)
1. **High**: Parser is primarily wide-table oriented (product encoded in column headers); weak support for Brick Analysis layouts where product group is row-level.
2. **High**: Header handling is mostly single-row; multi-row/header-band Excel formats are not robustly merged.
3. **High**: Sheet-type detection list does not explicitly model TL/BOX/MARKET normalization as one merged dataset for the same dimensional row.
4. **Medium**: Skipped-row reasons are tracked mostly via counters/warnings; structured per-row skip logs are limited.
5. **Medium**: Region/province/product-group contextual fields are not first-class in parser normalization flow.

## Risk List
1. **Backward-compatibility risk**: Replacing current wide parser path can break existing imports/tests if not dual-path.
2. **Matching risk**: Product group row-values may not map cleanly to existing master products; could increase unmatched/queued items.
3. **Data quality risk**: Aggressive auto-header detection may pick wrong row in noisy workbooks.
4. **Aggregation risk**: Merging TL/BOX/MARKET incorrectly can duplicate or drop metrics before `IMSRawData`/`IMSFact`.
5. **Operational risk**: Any schema changes would require migration checks; current Phase 1 should stay schema-neutral to avoid rollout complexity.
