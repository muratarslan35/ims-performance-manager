"""Row-semantic NATIONAL/region identity for dynamic IMS workbooks.

IMS pivot exports may repeat hierarchy columns for each metric block and may move,
insert or remove those columns between weeks.  Aggregate identity therefore must
come from the row's semantic grain, not from one selected representative/location
column pair.  This refinement changes only aggregate-row discovery; business
source priority and NATIONAL/region reconciliation remain fail-closed.
"""
from __future__ import annotations

import re

from app.services import dynamic_import_contract as base


_PLACEHOLDERS = {
    "", "0", "0.0", "-", "—", "N/A", "NA", "NULL", "NONE", "NAN",
}
_AGGREGATE_MARKERS = {
    "TOPLAM", "TOTAL", "SUBTOTAL", "GRAND TOTAL", "GENEL TOPLAM",
}
_NUMERIC_TEXT_RE = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")


def _row_text_tokens(row):
    """Return meaningful textual cells without depending on coordinates."""
    tokens = []
    for value in row.tolist():
        if value is None:
            continue
        # Numeric observations are metrics, not dimensions.  Numeric-looking
        # text such as a pivot placeholder is treated the same way.  Region
        # labels (for example ``201 KADIKOY``) remain textual and are retained.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            continue
        text = str(value).strip()
        normalized = base._norm(text)
        if not normalized or normalized in _PLACEHOLDERS:
            continue
        if _NUMERIC_TEXT_RE.fullmatch(normalized):
            continue
        tokens.append((text, normalized))
    return tokens


def row_semantic_aggregate_identity(profile, row):
    """Resolve only explicit NATIONAL or pure region-subtotal rows.

    A region subtotal may repeat the same region label in multiple pivot blocks.
    A representative row contains that region label *plus* a person/vacancy
    identity.  By examining every textual cell, the latter can never be promoted
    to a region aggregate merely because two physical hierarchy columns happen
    to contain the same region code.
    """
    del profile  # Identity is intentionally independent of physical coordinates.
    tokens = _row_text_tokens(row)
    if not tokens:
        return None

    normalized_values = [normalized for _text, normalized in tokens]
    non_markers = [
        (text, normalized)
        for text, normalized in tokens
        if normalized not in _AGGREGATE_MARKERS
    ]
    if not non_markers:
        return None

    # NATIONAL is authoritative only when the row contains no competing
    # semantic identity.  Repeated NATIONAL labels across pivot blocks are fine.
    if any(normalized == "NATIONAL" for _text, normalized in non_markers):
        if all(normalized == "NATIONAL" for _text, normalized in non_markers):
            return "NATIONAL", "NATIONAL"
        return None

    region_tokens = []
    other_tokens = []
    for text, normalized in non_markers:
        code = base._region_code(normalized)
        if code:
            region_tokens.append((code, text, normalized))
        else:
            other_tokens.append((text, normalized))

    # A true region subtotal contains one semantic region identity, possibly
    # repeated in several metric blocks, and no representative/product text.
    if not region_tokens or other_tokens:
        return None
    codes = {code for code, _text, _normalized in region_tokens}
    if len(codes) != 1:
        return None

    code = next(iter(codes))
    representative = next(
        text.strip()
        for region_code, text, _normalized in region_tokens
        if region_code == code
    )
    return code, representative


def install_aggregate_identity_refinement():
    """Install row-semantic aggregate discovery after locator refinements."""
    from app.services.dynamic_import_refinement import FlexibleSemanticLocator
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_aggregate_identity_refinement_installed", False):
        return

    # install_dynamic_import_refinement() replaces base.WorkbookSemanticLocator
    # with FlexibleSemanticLocator. Patch both references explicitly so tests or
    # callers holding either class receive the same content-first behavior.
    base.WorkbookSemanticLocator.aggregate_identity = staticmethod(
        row_semantic_aggregate_identity
    )
    FlexibleSemanticLocator.aggregate_identity = staticmethod(
        row_semantic_aggregate_identity
    )
    IMSImportService._aggregate_identity_refinement_installed = True
