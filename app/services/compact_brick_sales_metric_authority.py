"""Narrow metric authority for compact BRICK SATIS workbooks.

Some source workbooks expose the authoritative brick sales amount as exactly
one numbered product column per managed product (for example ``2 TRAVAZOL``)
without repeating a TL token in each column header.  The generic importer must
not treat those currency values as boxes merely because its historical default
for an unlabelled metric is ``unit``.

This hook is intentionally strict: it only applies to ``brick_sales`` wide
layouts where every matched product has exactly one column and every such
header is ``<column-number> <canonical-product-label>``.  Explicit TL/KUTU
layouts keep their existing behavior and mixed/ambiguous layouts are untouched.
"""

import re

from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService


_METRIC_TOKEN = re.compile(r"(?:^|\s)(?:TL|CIRO|VALUE|KUTU|BOX|UNIT|ADET)(?:\s|$)")
_NUMBERED_LABEL = re.compile(r"^\d+\s+(.+)$")
_INSTALLED = False


def _canonical_product_labels(product_info):
    return {
        AliasService.normalize(value)
        for value in (
            product_info.get("product_code"),
            product_info.get("product_name"),
            product_info.get("ims_name"),
        )
        if AliasService.normalize(value)
    }


def is_compact_numbered_tl_layout(prepared_sheet):
    """Return True only for the verified one-column-per-product TL layout."""
    if not prepared_sheet or prepared_sheet.get("sheet_type") != "brick_sales":
        return False
    if prepared_sheet.get("mode") != "wide":
        return False

    products = prepared_sheet.get("products") or {}
    if not products:
        return False

    for product_info in products.values():
        columns = product_info.get("columns") or []
        if len(columns) != 1:
            return False
        header = AliasService.normalize(columns[0].get("header"))
        if not header or _METRIC_TOKEN.search(header):
            return False
        match = _NUMBERED_LABEL.fullmatch(header)
        if match is None:
            return False
        if AliasService.normalize(match.group(1)) not in _canonical_product_labels(product_info):
            return False
    return True


def apply_compact_tl_metric_authority(prepared_sheet):
    """Mark compact numbered product columns as TL and return the sheet."""
    if not is_compact_numbered_tl_layout(prepared_sheet):
        return prepared_sheet
    for product_info in prepared_sheet["products"].values():
        product_info["columns"][0]["metric"] = "tl"
    prepared_sheet["compact_metric_authority"] = "tl"
    return prepared_sheet


def install_compact_brick_sales_metric_authority():
    """Install the narrow post-prepare authority exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_prepare_sheet = IMSImportService.prepare_sheet

    def prepare_sheet_with_compact_metric_authority(self, sheet):
        prepared = original_prepare_sheet(self, sheet)
        prepared = apply_compact_tl_metric_authority(prepared)
        if prepared and prepared.get("compact_metric_authority") == "tl":
            self.parser_decisions.append(
                {
                    "sheet_name": prepared.get("sheet_name"),
                    "sheet_type": prepared.get("sheet_type"),
                    "decision": "compact_numbered_product_columns",
                    "metric_authority": "tl",
                }
            )
        return prepared

    IMSImportService.prepare_sheet = prepare_sheet_with_compact_metric_authority
    _INSTALLED = True
