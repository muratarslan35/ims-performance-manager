from app.services.compact_brick_sales_metric_authority import (
    apply_compact_tl_metric_authority,
    is_compact_numbered_tl_layout,
)


def _product(product_id, code, header, metric="unit"):
    return {
        "product_id": product_id,
        "product_code": code,
        "product_name": code.title(),
        "ims_name": code,
        "columns": [{"index": product_id, "header": header, "metric": metric}],
    }


def _sheet(products):
    return {
        "sheet_name": "1001 BRICK SATIS",
        "sheet_type": "brick_sales",
        "mode": "wide",
        "products": {item["product_id"]: item for item in products},
    }


def test_numbered_bare_product_columns_are_tl_authority():
    sheet = _sheet([
        _product(1, "TRAVAZOL", "2 TRAVAZOL"),
        _product(2, "MONUROL", "4 MONUROL"),
        _product(3, "MIXOVUL", "6 MIXOVUL"),
        _product(4, "FENTIVAG", "8 FENTIVAG"),
        _product(5, "STIDERM", "10 STIDERM"),
        _product(6, "ACNEMIX", "12 ACNEMIX"),
        _product(7, "BRIMODER", "14 BRIMODER"),
    ])

    assert is_compact_numbered_tl_layout(sheet) is True
    result = apply_compact_tl_metric_authority(sheet)

    assert result["compact_metric_authority"] == "tl"
    assert {
        column["metric"]
        for product in result["products"].values()
        for column in product["columns"]
    } == {"tl"}


def test_explicit_box_and_tl_layout_is_unchanged():
    travazol = _product(1, "TRAVAZOL", "11 HAFTA KUTU CIKISI TRAVAZOL", metric="unit")
    travazol["columns"].append(
        {"index": 2, "header": "11 HAFTA TL CIKISI TRAVAZOL", "metric": "tl"}
    )
    sheet = _sheet([travazol])

    assert is_compact_numbered_tl_layout(sheet) is False
    result = apply_compact_tl_metric_authority(sheet)
    assert [column["metric"] for column in result["products"][1]["columns"]] == ["unit", "tl"]
    assert "compact_metric_authority" not in result


def test_ambiguous_bare_header_is_not_reclassified():
    sheet = _sheet([_product(1, "TRAVAZOL", "TRAVAZOL")])

    assert is_compact_numbered_tl_layout(sheet) is False
    result = apply_compact_tl_metric_authority(sheet)
    assert result["products"][1]["columns"][0]["metric"] == "unit"
    assert "compact_metric_authority" not in result


def test_numbered_header_must_match_canonical_product():
    sheet = _sheet([_product(1, "TRAVAZOL", "2 MONUROL")])

    assert is_compact_numbered_tl_layout(sheet) is False
    assert apply_compact_tl_metric_authority(sheet)["products"][1]["columns"][0]["metric"] == "unit"
