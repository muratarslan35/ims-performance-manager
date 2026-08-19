"""Strict evidence gate for derived/pivot workbook sheets.

A derived cell is never considered VERIFIED_DERIVED merely because its sheet was
classified. Verification evidence must be registered by a sheet-specific verifier.
Until evidence exists, meaningful derived cells remain blocking. This intentionally
fails closed rather than guessing relationships between unrelated workbook pivots.
"""

DERIVED_TYPES = {"master_pivot_derived", "brick_realization"}


def apply_derived_verification_gate(importer):
    """Require explicit evidence for every meaningful derived cell.

    Sheet-specific parsers/verifiers may populate ``derived_verification_evidence``
    with keys ``(sheet_name, row, column)`` after comparing a derived value to its
    authoritative source. Numeric zero is represented normally and is not exempt.
    """
    evidence = getattr(importer, "derived_verification_evidence", {}) or {}
    ledger = getattr(importer, "workbook_cell_ledger", []) or []
    unresolved = []
    verified = 0
    for cell in ledger:
        if cell.get("classification") != "VERIFIED_DERIVED":
            continue
        key = (cell["sheet_name"], cell["row"], cell["column"])
        proof = evidence.get(key)
        if proof and proof.get("matched") is True:
            cell["verification"] = proof
            verified += 1
        else:
            cell["classification"] = "UNCLASSIFIED_MASTER_CELL"
            cell["verification"] = proof or {"matched": False, "reason": "NO_VALUE_LEVEL_EVIDENCE"}
            unresolved.append(cell)
    importer.statistics["verified_derived_cells"] = verified
    importer.statistics["unverified_derived_cells"] = len(unresolved)
    importer.statistics["unclassified_master_cell"] = int(importer.statistics.get("unclassified_master_cell", 0) or 0) + len(unresolved)
    if unresolved:
        raise ValueError(
            "Derived/master doğrulaması başarısız; "
            f"{len(unresolved)} anlamlı hücre için değer-seviyesi master kanıtı yok"
        )
    return {"verified": verified, "unverified": 0}


def install_derived_verification_gate():
    """Run after workbook processing but before transaction commit/publish."""
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_derived_verification_gate_installed", False):
        return
    original_process = IMSImportService.process_workbook

    def process_with_derived_gate(self, year, month, week_number=None):
        result = original_process(self, year, month, week_number=week_number)
        apply_derived_verification_gate(self)
        return result

    IMSImportService.process_workbook = process_with_derived_gate
    IMSImportService._derived_verification_gate_installed = True
