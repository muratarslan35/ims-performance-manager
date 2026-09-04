from pathlib import Path

from app.presentation import representative_display_name


def test_vacancy_prefix_is_hidden_without_changing_normal_names():
    assert representative_display_name("ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS") == "901 DIYARBAKIR BOS"
    assert representative_display_name("ATANMAMIS-901 DIYARBAKIR BOS") == "901 DIYARBAKIR BOS"
    assert representative_display_name("ATANMAMIŞ · 101 ISTANBUL · ISTANBUL BOŞ") == "101 ISTANBUL BOŞ"
    assert representative_display_name("BOSTANCI TEMSILCI") == "BOSTANCI TEMSILCI"
    assert representative_display_name("MURAT ARSLAN") == "MURAT ARSLAN"


def test_global_ui_scrubber_is_loaded_for_all_base_template_screens():
    base = Path("app/templates/base.html").read_text(encoding="utf-8")
    app_js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "filename='js/app.js'" in base
    assert "initializeRepresentativeDisplayNames" in app_js
    assert "representativeDisplayName" in app_js
    assert 'observer.observe(document.body,{childList:true,subtree:true})' in app_js


def test_known_representative_selects_use_server_side_display_filter():
    quarter = Path("app/templates/quarter.html").read_text(encoding="utf-8")
    targets = Path("app/templates/targets.html").read_text(encoding="utf-8")
    assert "rep.rep_name|representative_display_name" in quarter
    assert "representative.rep_name|representative_display_name" in targets
