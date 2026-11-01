# Source-scoped monthly IMS computation

The normal Week 41 replay (job 46) took 2,895.972 seconds to publish, including
277.495 seconds importing and 2,238.739 seconds preparing representatives.
It recalculated ten source months for all 113 representatives on each upload.

The publication sequence remains semantic discovery, atomic import and
reconciliation, dashboard/region/representative generation, enrichment and
atomic publication. Interactive routes continue reading published snapshots.

## Computation changes

- Competition SQL returns the existing representative-first aggregate and exact
  brick detail without fetching unrelated rows from the whole region.
- Label/product matching is memoized inside one representative build. Immutable
  scalar query projections can be shared safely instead of recursively cloned.
- Intermediate memory caches end with each member. The small authority map is
  resolved once for the accepted upload IDs in one generation and copied into
  its readers; no business-source boolean survives into another generation.
- Region enrichment checks coverage with IDs, decodes current/prior workspaces
  one region at a time, and pins their generation IDs. Missing/corrupt members
  or a generation change prevent the entire enrichment update.

## Reuse unchanged months

`RepresentativeMonthlyMarketCache` stores disposable monthly market results in
`instance/representative_monthly_market`. Each representative/month has one
compressed JSON slot, replaced atomically when its fingerprint changes. Weekly
uploads do not append a new cache file for every historical month.

The fingerprint includes the existing exact IMS/current-production source key,
current/prior effective P2/P1/IMS values, both months' active brick scopes, exact
representative identity, managed-product matching metadata, database identity,
and the application/configuration source-code digest. A source, target, actual,
scope, matching rule or calculation-code change invalidates reuse. Existing
locked price resolution supplies the effective box values in that fingerprint.

The payload retains product identity, Decimal values, localized box-number
types, dictionary order, explicit zero and missing values. Products are resolved
in the reader's own DB session. Files use a private directory and mode 0600,
bounded decompression and a payload checksum. Invalid/unavailable cache data
falls back to the canonical calculator. The cache writes no business rows or
published historical snapshots and is only used inside snapshot construction.

The first historical-cache bootstrap is an explicit rollout operation, measured
separately while the previous verified publication stays visible. Subsequent
normal imports still parse/reconcile the full workbook and recompute changed
source months. Unchanged historical months are composed from verified cached
intermediates. Code changes invalidate affected cache entries and require
bootstrap/verification before claiming the steady-state publication budget.

## Acceptance

Measure queue entry through the durable `publication_ready` flag and completed
progress, including all mandatory generations/enrichment. Import DB completion
alone is insufficient. Separate archive queue replay from browser file-transfer
time and rollout/bootstrap time. The requested normal publication budget is
600 seconds; confirm it on the real file through the normal queue.

Compare canonical and optimized payloads before release, run the complete Linux
suite, then verify official Excel/DB/snapshot values and historical protection.
Keep financial/person-level details in private server artifacts; public logs
contain statuses, counts, hashes and timings only.

## First optimized normal replay and region follow-up

Job 47 (source 56 -> upload 57) published in 682.312 seconds: 0.506 seconds
queue wait, 274.012 seconds importing and 407.794 seconds after import. This
reduces the 2,895.972-second baseline by 76.44%, but exceeds the 600-second
budget. Peak worker RSS was 510,533,632 bytes and minimum available memory
225,902,592 bytes. These are real normal-queue measurements, not a projection.

Post-publication profiling identified repeated `_latest_authority_upload`
discovery in the region wrapper chain and repeated product-label matching.
Region generation now reuses the selected source ID (including absence) only
inside one sequential build. ORM rows are resolved in the current session;
normal readers, subsequent builds, nested builds and other threads do not share
the memo. Product matches are bounded and confined to one region service, keyed
by exact labels and catalog identity/values. Original lookup order, source
selection and matching formulas are retained. Complete region payload equality
and another normal queue measurement are required before completion.
