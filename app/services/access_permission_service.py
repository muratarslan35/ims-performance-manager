"""Database-backed role permission matrix with secure live defaults."""

from flask import g, has_request_context, session

from app.extensions import db
from app.models import Setting


SUBJECTS = {
    "representative": "Temsilciler",
    "region": "Bölge Müdürleri",
    "promotion": "Tanıtım Müdürleri",
    "product": "Ürün Müdürleri",
    "marketing": "Pazarlama Müdürleri",
}

PERMISSIONS = {
    "cross_region_details": ("Farklı bölge detayları", "Kendi bölgesi dışındaki bölge ve temsilci analizlerini açabilir."),
    "market_analysis": ("Türkiye Pazar Analizi", "Türkiye Pazar Analizi ekranını açabilir."),
    "ims_center": ("IMS Merkezi", "IMS yükleme ve geçmiş ekranlarını açabilir."),
    "region_assignments": ("Bölge Atamaları", "Brick/bölge atama ekranını açabilir."),
    "cross_region_assignments": ("Farklı bölge brick ataması", "Başka bölgedeki brick atamalarını değiştirebilir."),
    "products": ("Ürünler", "Ürün yönetimi ekranlarını açabilir."),
    "targets": ("Hedefler", "Hedef yönetimi ekranlarını açabilir."),
    "manual_matching": ("Manuel Eşleştirme", "Manuel eşleştirme ekranını açabilir."),
    "prime_center": ("Prim Merkezi", "Prim Merkezi ekranını açabilir."),
    "prime_simulation": ("Prim Simülasyonu", "Prim Simülasyonu ekranını açabilir."),
    "q_analysis": ("Q Dönem Analizi", "Q Dönem Analizi ekranını açabilir."),
    "recovery": ("Telafi Takibi", "Telafi Takibi ekranını açabilir."),
    "reports": ("Raporlar", "Raporlar ekranını açabilir."),
    "manager_module": ("Yönetici Modülü", "Yönetici listesini görüntüleyebilir."),
    "manage_managers": ("Yönetici ekleme/düzenleme", "Yönetici hesabı oluşturabilir ve düzenleyebilir."),
}

_FIELD_DEFAULTS = {
    "cross_region_details": False, "market_analysis": False, "ims_center": False,
    "region_assignments": False, "cross_region_assignments": False,
    "products": False, "targets": False, "manual_matching": False,
    "prime_center": True, "prime_simulation": True, "q_analysis": True,
    "recovery": True, "reports": True, "manager_module": False,
    "manage_managers": False,
}
_REGION_DEFAULTS = {
    **_FIELD_DEFAULTS, "market_analysis": True, "region_assignments": True,
    "manager_module": True,
}
_FUNCTIONAL_DEFAULTS = {key: True for key in PERMISSIONS}
_FUNCTIONAL_DEFAULTS["manage_managers"] = False

DEFAULTS = {
    "representative": _FIELD_DEFAULTS,
    "region": _REGION_DEFAULTS,
    "promotion": {**_FUNCTIONAL_DEFAULTS, "manage_managers": True},
    "product": _FUNCTIONAL_DEFAULTS,
    "marketing": {**_FUNCTIONAL_DEFAULTS, "manage_managers": True},
}

# Representatives may only receive analytical/navigation capabilities. Master
# data and assignment permissions remain manager-only, including against a
# crafted settings form submission.
APPLICABLE = {subject: set(PERMISSIONS) for subject in SUBJECTS}
APPLICABLE["representative"] = {
    "cross_region_details", "market_analysis", "prime_center",
    "prime_simulation", "q_analysis", "recovery", "reports",
}


def setting_key(subject, permission):
    return f"ACCESS.{subject}.{permission}"


def _bool(value):
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on", "aktif"}


def subject_for(user):
    role = str(getattr(user, "role", "") or "").strip().casefold()
    if has_request_context() and session.get("portal") == "representative" and session.get("portal_explicit", False):
        return "representative"
    if role in {"admin", "administrator"}:
        return "admin"
    if role not in {"manager", "yönetici", "yonetici"}:
        return "representative"
    from app.region_manager import manager_type
    kind = manager_type(user)
    if kind == "privileged":
        return "admin"
    return kind if kind in SUBJECTS else "region"


def _stored_values():
    cache_name = "_access_permission_values"
    if has_request_context() and hasattr(g, cache_name):
        return getattr(g, cache_name)
    prefix = "ACCESS.%"
    values = {row.setting_key: _bool(row.setting_value) for row in Setting.query.filter(Setting.setting_key.like(prefix)).all()}
    if has_request_context():
        setattr(g, cache_name, values)
    return values


def enabled(user, permission):
    if permission not in PERMISSIONS or not getattr(user, "is_authenticated", False):
        return False
    subject = subject_for(user)
    if subject == "admin":
        return True
    if permission not in APPLICABLE.get(subject, set()):
        return False
    default = DEFAULTS.get(subject, {}).get(permission, False)
    return _stored_values().get(setting_key(subject, permission), default)


def matrix():
    stored = _stored_values()
    return {
        subject: {
            permission: stored.get(setting_key(subject, permission), default)
            for permission, default in defaults.items()
        }
        for subject, defaults in DEFAULTS.items()
    }


def save_matrix(form):
    existing = {row.setting_key: row for row in Setting.query.filter(Setting.setting_key.like("ACCESS.%")).all()}
    for subject, defaults in DEFAULTS.items():
        for permission in defaults:
            key = setting_key(subject, permission)
            value = "1" if permission in APPLICABLE[subject] and form.get(key) == "1" else "0"
            row = existing.get(key)
            if row is None:
                row = Setting(setting_key=key, setting_value=value, category="Erişim Yetkisi", description=PERMISSIONS[permission][0])
                db.session.add(row)
            else:
                row.setting_value = value
    db.session.commit()
