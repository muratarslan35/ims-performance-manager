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


def _canonical_text(value) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).upper().strip()
    text = re.sub(r"[^0-9A-ZÇĞİÖŞÜ]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _vacancy_token(value):
    tokens = _canonical_text(value).split()
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


def _is_explicit_vacancy(value) -> bool:
    return _vacancy_token(value) is not None


def _vacancy_identity(value):
    canonical = _canonical_text(value)
    token = _vacancy_token(canonical)
    return (canonical, token) if token else None


def _candidate_labels(representative):
    return tuple(label for label in (
        _canonical_text(representative.rep_name),
        _canonical_text(representative.territory),
        _canonical_text(representative.rep_code),
        _canonical_text(representative.ims_code),
    ) if label)


def _vacancy_candidate(source_value):
    identity = _vacancy_identity(source_value)
    if identity is None:
        return None
    source_canonical, source_token = identity
    if identity in _VACANCY_CACHE:
        return _VACANCY_CACHE[identity]
    scored = []
    for representative in Representative.query.all():
        labels = _candidate_labels(representative)
        label_tokens = {_vacancy_token(label) for label in labels}
        label_tokens.discard(None)
        code = _canonical_text(representative.rep_code)
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
        _INSTALLED = True


def clear_vacancy_match_cache() -> None:
    _VACANCY_CACHE.clear()
