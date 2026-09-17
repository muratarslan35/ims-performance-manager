from pathlib import Path
from types import SimpleNamespace

import app.auth as auth
from app.services.alias_service import AliasService


ROOT = Path(__file__).resolve().parents[1]


def test_registration_email_accepts_only_exact_bilim_ilac_domain():
    assert auth._is_corporate_registration_email("ad.soyad@bilimilac.com") is True
    assert auth._is_corporate_registration_email("AD.SOYAD@BILIMILAC.COM") is True
    assert auth._is_corporate_registration_email("ad.soyad@gmail.com") is False
    assert auth._is_corporate_registration_email("ad.soyad@bilimilac.com.tr") is False
    assert auth._is_corporate_registration_email("ad.soyad@sub.bilimilac.com") is False
    assert auth._is_corporate_registration_email("ad.soyad@bilimilac.com.evil.test") is False


def test_registration_ui_explains_corporate_email_requirement():
    template = (ROOT / "app/templates/register.html").read_text(encoding="utf-8")

    assert 'placeholder="ad.soyad@bilimilac.com"' in template
    assert "@bilimilac.com kurumsal e-posta adresi" in template
    assert "bilimilac\\.com" in template


def test_registration_region_filter_removes_only_602_artvin_choice():
    source = (ROOT / "app/auth.py").read_text(encoding="utf-8")

    assert 'str(region).strip() == "602"' in source
    assert 'str(city).strip().casefold() == "artvin"' in source
    assert "db.session.delete" not in source


def test_registration_representative_resolution_is_region_scoped_and_canonical(monkeypatch):
    canonical = SimpleNamespace(
        id=17,
        rep_name="Ayşe Yılmaz",
        region="602",
        active=True,
    )

    class FakeQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {"active": True, "region": "602"}
            return self

        def all(self):
            return [canonical]

    class FakeRepresentative:
        query = FakeQuery()

    monkeypatch.setattr(auth, "Representative", FakeRepresentative)
    monkeypatch.setattr(
        AliasService,
        "find_representative",
        classmethod(lambda cls, value, minimum_score=None: {
            "matched": False,
            "score": 0,
            "method": "NONE",
            "object": None,
        }),
    )

    resolved = auth._resolve_registration_representative("Ayse Yilmaz", "602")
    assert resolved is canonical

    source = (ROOT / "app/auth.py").read_text(encoding="utf-8")
    assert "representative = _resolve_registration_representative(full_name, selected_region)" in source
    assert "if representative is None:" in source
    assert "full_name=representative.rep_name" in source
    assert "representative.email = email" in source
