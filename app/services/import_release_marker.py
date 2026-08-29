"""Release classification marker for IMS lifecycle/import safety.

This module intentionally contains no runtime behavior. Changes that affect queued IMS
replacement/duplicate handling must travel through the import-class production gates
(worker idle, SQLite, live IMS reconciliation, and resource acceptance).
"""
