# IMS replay cache regression

This branch fixes only the persistent worker alias/master cache boundary. A successful IMS job must not leave SQLAlchemy ORM objects in the process-wide AliasService caches for the next queued workbook. The worker clears AliasService before constructing each IMSImportService and again in `finally` after success/failure.
