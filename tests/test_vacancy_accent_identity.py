import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_vacancy_tokens_are_accent_sensitive_and_bostanci_is_not_vacancy():
    from app.services.vacancy_matching import _canonical_text, _is_explicit_vacancy, _vacancy_identity

    assert _vacancy_identity("DIYARBAKIR BOS") == ("DIYARBAKIR BOS", "BOS")
    assert _vacancy_identity("DİYARBAKIR BOŞ") == ("DİYARBAKIR BOŞ", "BOŞ")
    assert _vacancy_identity("DIYARBAKIR BOS") != _vacancy_identity("DİYARBAKIR BOŞ")
    assert _canonical_text("BOŞ") != _canonical_text("BOS")
    assert _is_explicit_vacancy("BOSTANCI TEMSILCI") is False


def test_bos_and_bos_with_cedilla_resolve_to_different_representatives(resilient_app):
    from app.extensions import db
    from app.models import Representative
    from app.services.alias_service import AliasService
    from app.services.vacancy_matching import clear_vacancy_match_cache

    with resilient_app.app_context():
        bos = Representative(rep_code="UNASSIGNED901BOS", rep_name="ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS", region="901 DIYARBAKIR", city="DIYARBAKIR", active=False)
        bos_cedilla = Representative(rep_code="UNASSIGNED901BOSCEDILLA", rep_name="ATANMAMIŞ · 901 DİYARBAKIR · DİYARBAKIR BOŞ", region="901 DIYARBAKIR", city="DIYARBAKIR", active=False)
        db.session.add_all([bos, bos_cedilla])
        db.session.commit()
        AliasService.clear_cache()
        clear_vacancy_match_cache()

        first = AliasService.find_representative("DIYARBAKIR BOS")
        second = AliasService.find_representative("DİYARBAKIR BOŞ")
        assert first["matched"] is True
        assert second["matched"] is True
        assert first["object"].id == bos.id
        assert second["object"].id == bos_cedilla.id
        assert first["object"].id != second["object"].id
