from app.services.vacancy_matching import (
    canonical_vacancy_text,
    vacancy_identity,
    vacancy_slot_token,
    vacancy_stable_suffix,
)


def test_bos_and_bos_cedilla_are_distinct_slots():
    assert vacancy_slot_token("DIYARBAKIR BOS") == "BOS"
    assert vacancy_slot_token("DİYARBAKIR BOŞ") == "BOŞ"
    assert vacancy_identity("DIYARBAKIR BOS") != vacancy_identity("DİYARBAKIR BOŞ")
    assert vacancy_stable_suffix("DIYARBAKIR BOS") != vacancy_stable_suffix("DİYARBAKIR BOŞ")


def test_kadro_qualifier_preserves_distinct_slot_identity():
    assert vacancy_slot_token("DIYARBAKIR BOS KADRO") == "BOS_KADRO"
    assert vacancy_slot_token("DİYARBAKIR BOŞ KADRO") == "BOŞ_KADRO"
    assert vacancy_slot_token("DIYARBAKIR BOS") != vacancy_slot_token("DIYARBAKIR BOS KADRO")
    assert vacancy_slot_token("DİYARBAKIR BOŞ") != vacancy_slot_token("DİYARBAKIR BOŞ KADRO")


def test_bostanci_is_not_vacancy_and_brick_is_context_only():
    assert vacancy_slot_token("BOSTANCI") is None
    assert vacancy_slot_token("BOSTANCI BRICK") is None
    assert vacancy_slot_token("DIYARBAKIR BOS BRICK") == "BOS"
    assert vacancy_slot_token("DİYARBAKIR BOŞ BRICK") == "BOŞ"


def test_conflicting_bos_and_bos_cedilla_is_never_guessed():
    assert vacancy_slot_token("DIYARBAKIR BOS BOŞ") is None
    assert vacancy_identity("DIYARBAKIR BOS BOŞ") is None


def test_canonical_text_keeps_turkish_cedilla():
    assert "BOŞ" in canonical_vacancy_text("Diyarbakır boş")
    assert "BOS" in canonical_vacancy_text("Diyarbakir bos")
