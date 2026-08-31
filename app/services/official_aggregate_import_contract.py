"""Deployment classification marker for official IMS aggregate import behavior.

This module intentionally has no runtime side effects. Its import-named path makes
changes to official aggregate parsing go through the import CI/deploy gates so the
IMS worker is refreshed safely.
"""

OFFICIAL_AGGREGATE_IMPORT_CONTRACT = True
