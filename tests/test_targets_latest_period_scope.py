from types import SimpleNamespace

from flask import render_template

from app import create_app


def test_targets_template_shows_only_latest_period():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    rep = SimpleNamespace(id=1, rep_name="TEST TEMSILCI", region="901", city="DIYARBAKIR")
    product = SimpleNamespace(id=1, product_name="TEST URUN", display_order=1)
    old = SimpleNamespace(
        id=11, year=2026, month=2, representative=rep, representative_id=1,
        product=product, product_id=1, tl_target=111.0, target_tl=111.0,
        unit_target=11.0, target_unit=11.0,
    )
    current = SimpleNamespace(
        id=12, year=2026, month=3, representative=rep, representative_id=1,
        product=product, product_id=1, tl_target=222.0, target_tl=222.0,
        unit_target=22.0, target_unit=22.0,
    )

    with app.test_request_context("/targets/"):
        html = render_template(
            "targets.html",
            targets=[current, old],
            representatives=[rep],
            products=[product],
            target_groups=[{"representative": rep, "targets": [old, current]}],
        )

    assert "03/2026" in html
    assert "· 1 ürün" in html
    assert "222 ₺" in html
    assert "111 ₺" not in html
    assert 'value="3" selected' in html
    assert 'name="year" value="2026"' in html
