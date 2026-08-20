"""Deterministic, accent-sensitive matching for explicit vacancy/headcount labels.

Vacancy identity deliberately stays outside AliasService.normalize(): Turkish
BOS and BOŞ are distinct stable slots. KADRO is retained as a slot qualifier,
so BOS and BOS KADRO (and their BOŞ counterparts) never collapse. Existing
legacy UNASSIGNED vacancy rows are reused by primary key when their token and
location context are uniquely deterministic; ambiguity always fails closed.
"""
from __future__ import annotations
import re
import threading
import unicodedata
from app.extensions import db
from app.models import Representative
from app.services.alias_service import AliasService

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_FIND_REPRESENTATIVE = None
_VACANCY_CACHE = {}
VACANCY_TEAM = "TAYFUN-1"


def canonical_vacancy_text(value) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).upper().strip()
    text = re.sub(r"[^0-9A-ZÇĞİÖŞÜ]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def vacancy_slot_token(value):
    tokens = canonical_vacancy_text(value).split()
    has_bos = "BOS" in tokens
    has_bos_cedilla = "BOŞ" in tokens
    if has_bos and has_bos_cedilla:
        return None
    if has_bos_cedilla:
        return "BOŞ_KADRO" if "KADRO" in tokens else "BOŞ"
    if has_bos:
        return "BOS_KADRO" if "KADRO" in tokens else "BOS"
    if "KADRO" in tokens:
        return "KADRO"
    return None


def vacancy_identity(value):
    canonical = canonical_vacancy_text(value)
    token = vacancy_slot_token(canonical)
    return (canonical, token) if token else None


def _canonical_text(value) -> str:
    return canonical_vacancy_text(value)


def _vacancy_identity(value):
    return vacancy_identity(value)


def vacancy_stable_suffix(value) -> str:
    identity = vacancy_identity(value)
    if identity is None:
        return "VACANCY"
    canonical, token = identity
    encoded = canonical.replace("BOŞ", "BOSH").replace("Ş", "SH")
    encoded = re.sub(r"[^A-Z0-9]+", "", encoded)[:40]
    qualifier = re.sub(r"[^A-Z0-9]+", "", token.replace("Ş", "SH"))
    return f"{qualifier}{encoded}"[:48] or "VACANCY"


def _is_explicit_vacancy(value) -> bool:
    return vacancy_slot_token(value) is not None


def _candidate_labels(representative):
    return tuple(label for label in (
        canonical_vacancy_text(representative.rep_name),
        canonical_vacancy_text(representative.territory),
        canonical_vacancy_text(representative.rep_code),
        canonical_vacancy_text(representative.ims_code),
    ) if label)


def _vacancy_candidate(source_value):
    identity = vacancy_identity(source_value)
    if identity is None:
        return None
    source_canonical, source_token = identity
    if identity in _VACANCY_CACHE:
        return _VACANCY_CACHE[identity]
    scored = []
    for representative in Representative.query.all():
        labels = _candidate_labels(representative)
        label_tokens = {vacancy_slot_token(label) for label in labels}
        label_tokens.discard(None)
        code = canonical_vacancy_text(representative.rep_code)
        if source_token not in label_tokens and not (source_token == "KADRO" and code.startswith("UNASSIGNED")):
            continue
        score = 0
        method = None
        if source_canonical in labels:
            score, method = 100, "VACANCY_EXACT"
        else:
            for label in labels:
                if label.endswith(" " + source_canonical):
                    score, method = 98, "VACANCY_SUFFIX"
                    break
        if score:
            scored.append((score, representative.id, method, representative))
    if not scored:
        # A miss is intentionally NOT cached. During one IMS transaction
        # BAKIYE/bootstrap may create the deterministic slot after an earlier
        # parser first asked for it. Successful stable matches remain cacheable.
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored[0][0]
    best = [item for item in scored if item[0] == best_score]
    result = best[0] if len(best) == 1 else None
    if result is not None:
        _VACANCY_CACHE[identity] = result
    return result


def _legacy_placeholder_candidates(vacancy_name):
    """Find legacy UNASSIGNED rows for exactly the same accent-sensitive slot."""
    source_identity = vacancy_identity(vacancy_name)
    if source_identity is None:
        return []
    source_canonical, source_token = source_identity
    ignored = {"BOS", "BOŞ", "KADRO", "BRICK"}
    source_context = " ".join(token for token in source_canonical.split() if token not in ignored)
    matches = []
    for representative in Representative.query.filter(Representative.rep_code.like("UNASSIGNED%")).all():
        candidate_token = vacancy_slot_token(representative.rep_name) or vacancy_slot_token(representative.territory)
        if candidate_token != source_token:
            continue
        city = canonical_vacancy_text(representative.city or "")
        territory = canonical_vacancy_text(representative.territory or "")
        labels = _candidate_labels(representative)
        exact_or_suffix = source_canonical in labels or any(label.endswith(" " + source_canonical) for label in labels)
        context_match = bool(
            source_context
            and (
                (city and (city.startswith(source_context) or source_context.startswith(city)))
                or (territory and source_context in territory)
            )
        )
        if exact_or_suffix or context_match:
            matches.append(representative)
    # A repeated SQLAlchemy object must not make an otherwise deterministic
    # candidate look ambiguous.
    return list({representative.id: representative for representative in matches}.values())


def _apply_active_cadre_profile(representative, *, region=None, city=None):
    """Backfill organisational metadata without changing stable slot identity."""
    if region and not representative.region:
        representative.region = region
    if city and not representative.city:
        representative.city = city
    if not representative.territory:
        representative.territory = city or representative.city
    if not representative.team:
        representative.team = VACANCY_TEAM
    representative.active = True
    return representative


def resolve_vacancy_match(value):
    """Resolve only explicit vacancy labels, never normal people or place names."""
    if vacancy_identity(value) is None:
        return AliasService.build_match(False, 0, "NOT_VACANCY", None)
    candidate = _vacancy_candidate(value)
    if candidate is None:
        return AliasService.build_match(False, 0, "VACANCY_UNRESOLVED", None)
    score, _identifier, method, representative = candidate
    return AliasService.build_match(True, score, method, representative)


def install_vacancy_matcher() -> None:
    global _INSTALLED, _ORIGINAL_FIND_REPRESENTATIVE
    if _INSTALLED:
        return
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        original = AliasService.find_representative
        _ORIGINAL_FIND_REPRESENTATIVE = original

        def find_representative_with_vacancies(cls, value, minimum_score=None):
            if _is_explicit_vacancy(value):
                return resolve_vacancy_match(value)
            return original(value, minimum_score)

        AliasService.find_representative = classmethod(find_representative_with_vacancies)
        from app.services.ims_import_service import IMSImportService
        original_ensure_vacancy = IMSImportService._ensure_vacancy_representative

        def is_vacancy_representative(self, text):
            return vacancy_slot_token(text) is not None

        def vacancy_code(region, vacancy_name):
            return f"UNASSIGNED{region or 'GENERAL'}{vacancy_stable_suffix(vacancy_name)}"

        def find_vacancy_placeholder(self, vacancy_name):
            matches = _legacy_placeholder_candidates(vacancy_name)
            return matches[0] if len(matches) == 1 else None

        def ensure_vacancy_representative(self, region_value=None, city=None, vacancy_name=None):
            """Preserve an existing stable slot ID before creating a new canonical code."""
            region, location_city = self._region_context(region_value, city)
            code = self._vacancy_code(region, vacancy_name)
            by_code = Representative.query.filter_by(rep_code=code).first()
            if by_code is not None:
                _apply_active_cadre_profile(by_code, region=region, city=location_city)
                return by_code.id

            legacy = _legacy_placeholder_candidates(vacancy_name)
            if len(legacy) > 1:
                ids = ", ".join(str(item.id) for item in sorted(legacy, key=lambda item: item.id))
                raise ValueError(
                    f"Belirsiz vacancy slot eşleşmesi: {vacancy_name} birden fazla stable ID ile eşleşiyor ({ids})"
                )
            if len(legacy) == 1:
                representative = legacy[0]
                # Preserve the primary key/history. Only backfill missing
                # organisational metadata; do not rewrite prior IMS ownership.
                _apply_active_cadre_profile(representative, region=region, city=location_city)
                _VACANCY_CACHE.pop(vacancy_identity(vacancy_name), None)
                return representative.id

            representative = original_ensure_vacancy(
                self,
                region_value=region_value,
                city=city,
                vacancy_name=vacancy_name,
            )
            _apply_active_cadre_profile(
                db.session.get(Representative, representative),
                region=region,
                city=location_city,
            )
            _VACANCY_CACHE.pop(vacancy_identity(vacancy_name), None)
            return representative

        IMSImportService._is_vacancy_representative = is_vacancy_representative
        IMSImportService._vacancy_code = staticmethod(vacancy_code)
        IMSImportService._find_vacancy_placeholder = find_vacancy_placeholder
        IMSImportService._ensure_vacancy_representative = ensure_vacancy_representative
        _INSTALLED = True


def clear_vacancy_match_cache() -> None:
    _VACANCY_CACHE.clear()
