"""Deterministic, accent-sensitive matching for explicit vacancy/headcount labels.

Vacancy identity deliberately stays outside AliasService.normalize(): Turkish
BOS and BOŞ are distinct stable slots. KADRO is retained as a slot qualifier,
so BOS and BOS KADRO (and their BOŞ counterparts) never collapse.
"""
from __future__ import annotations
import re
import threading
import unicodedata
from app.models import Representative
from app.services.alias_service import AliasService

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_FIND_REPRESENTATIVE = None
_VACANCY_CACHE = {}


def canonical_vacancy_text(value) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).upper().strip()
    text = re.sub(r"[^0-9A-ZÇĞİÖŞÜ]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def vacancy_slot_token(value):
    """Return an accent-sensitive vacancy slot token, or None for normal names.

    BOS/BOŞ and their KADRO-qualified forms are intentionally distinct. BRICK is
    context only. A value containing both BOS and BOŞ is conflicting and is not
    resolved automatically. Token matching means BOSTANCI can never become BOS.
    """
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


def vacancy_stable_suffix(value) -> str:
    """Build a stable accent-sensitive code suffix without collapsing Ş to S."""
    identity = vacancy_identity(value)
    if identity is None:
        return "VACANCY"
    canonical, token = identity
    # ASCII rep_code-safe but explicitly encode BOŞ before stripping accents.
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
        result = None
    else:
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score = scored[0][0]
        best = [item for item in scored if item[0] == best_score]
        result = best[0] if len(best) == 1 else None
    _VACANCY_CACHE[identity] = result
    return result


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
                candidate = _vacancy_candidate(value)
                if candidate is None:
                    return AliasService.build_match(False, 0, "VACANCY_UNRESOLVED", None)
                score, _identifier, method, representative = candidate
                return AliasService.build_match(True, score, method, representative)
            return original(value, minimum_score)

        AliasService.find_representative = classmethod(find_representative_with_vacancies)

        # IMSImportService historically had local vacancy helpers that used
        # accent-insensitive AliasService.normalize(). Replace only those helper
        # seams so every importer shares the same vacancy identity semantics.
        from app.services.ims_import_service import IMSImportService

        def is_vacancy_representative(self, text):
            return vacancy_slot_token(text) is not None

        def vacancy_code(region, vacancy_name):
            return f"UNASSIGNED{region or 'GENERAL'}{vacancy_stable_suffix(vacancy_name)}"

        def find_vacancy_placeholder(self, vacancy_name):
            source_identity = vacancy_identity(vacancy_name)
            if source_identity is None:
                return None
            source_canonical, source_token = source_identity
            ignored = {"BOS", "BOŞ", "KADRO", "BRICK"}
            source_context = " ".join(t for t in source_canonical.split() if t not in ignored)
            matches = []
            for representative in Representative.query.filter(Representative.rep_code.like("UNASSIGNED%")).all():
                candidate_token = vacancy_slot_token(representative.rep_name) or vacancy_slot_token(representative.territory)
                if candidate_token != source_token:
                    continue
                city = canonical_vacancy_text(representative.city or "")
                if source_context and city and (city.startswith(source_context) or source_context.startswith(city)):
                    matches.append(representative)
            return matches[0] if len(matches) == 1 else None

        IMSImportService._is_vacancy_representative = is_vacancy_representative
        IMSImportService._vacancy_code = staticmethod(vacancy_code)
        IMSImportService._find_vacancy_placeholder = find_vacancy_placeholder
        _INSTALLED = True


def clear_vacancy_match_cache() -> None:
    _VACANCY_CACHE.clear()
