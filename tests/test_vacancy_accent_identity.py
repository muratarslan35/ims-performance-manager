import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_vacancy_tokens_are_accent_sensitive_and_bostanci_is_not_vacancy():
    from app.services.vacancy_matching import _canonical_text, _is_explicit_vacancy, _vacancy_identity

    bos = _vacancy_identity("DIYARBAKIR BOS")
    bos_cedilla = _vacancy_identity("DİYARBAKIR BOŞ")

    assert bos == ("DIYARBAKIR BOS", "BOS")
    assert bos_cedilla == ("DİYARBAKIR BOŞ", "BOŞ")
    assert bos != bos_cedilla
    assert _canonical_text("BOŞ") != _canonical_text("BOS")
    assert _is_explicit_vacancy("BOSTANCI TEMSILCI") is False
    assert _is_explicit_vacancy("BOS") is True
    assert _is_explicit_vacancy("BOŞ") is True
