"""Deterministic, accent-sensitive matching for explicit vacancy/headcount labels.

Vacancy identity is deliberately kept outside AliasService.normalize(): Turkish
``BOS`` and ``BOŞ`` are different stable slots and must never collapse into the
same representative. Normal employee matching keeps the existing AliasService
behaviour.
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
_VACANCY_TOKENS = {"BOS", "BOŞ", "KADRO"}


def _canonical_text(value) -> str:
    """Normalize spacing/case while preserving Turkish accents."""
    text = unicodedata.normalize("NFC", str(value or "")).upper().strip()
    text = re.sub(r"[^0-9A-ZÇĞİÖŞÜ]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _vacancy_token(value) -> str | None:
    tokens = _canonical_text(value).split()
    found = [token for token in tokens if token in _VACANCY_TOKENS]
    if not found:
        return None
    # BOS and BOŞ are separate identities. Multiple vacancy tokens are
    # intentionally considered ambiguous rather than guessed.
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else None


def _is_explicit_vacancy(value) -> bool:
    return _vacancy_token(value) is not None


def _vacancy_identity(value) -> tuple[str, str] | None:
    canonical = _canonical_text(value)
    token = _vacancy_token(canonical)
    if token is None:
        return None
    return canonical, token


def _candidate_labels(representative):
    return tuple(
        label
        for label in (
            _canonical_text(representative.rep_name),
            _canonical_text(representative.territory),
            _canonical_text(representative.rep_code),
            _canonical_text(representative.ims_code),
        )
        if label
    )


def _vacancy_candidate(source_value):
    identity = _vacancy_identity(source_value)
    if identity is None:
        return None
    source_canonical, source_token = identity
    cached = _VACANCY_CACHE.get(identity)
    if cached is not None:
        return cached

    scored = []
    for representative in Representative.query.all():
        labels = _candidate_labels(representative)
        label_tokens = {_vacancy_token(label) for label in labels}
        label_tokens.discard(None)
        code = _canonical_text(representative.rep_code)

        # A vacancy candidate must carry the exact accent-sensitive vacancy
        # token. Thus BOŞ can never match BOS, and BOSTANCI is never a vacancy.
        if source_token not in label_tokens and not (
            source_token == "KADRO" and code.startswith("UNASSIGNED")
        ):
            continue

        score = 0
        method = None
        if source_canonical in labels:
            score, method = 100, f"VACANCY_{source_token}_EXACT"
        else:
            suffix = " " + source_canonical
            rep_name = _canonical_text(representative.rep_name)
            territory = _canonical_text(representative.territory)
            if rep_name.endswith(suffix):
                score, method = 99, f"VACANCY_{source_token}_SUFFIX"
            elif territory.endswith(suffix):
                score, method = 98, f"VACANCY_{source_token}_TERRITORY_SUFFIX"

        if score:
            scored.append((score, representative.id, method, representative))

    if not scored:
        result = None
    else:
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score = scored[0][0]
        best = [item for item in scored if item[0] == best_score]
        # Never guess between equally strong vacancy candidates.
        result = best[0] if len(best) == 1 else None

    _VACANCY_CACHE[identity] = result
    return result


def install_vacancy_matcher() -> None:
    """Extend central representative matching without altering normal names."""
    global _INSTALLED, _ORIGINAL_FIND_REPRESENTATIVE
    if _INSTALLED:
        return

    with _INSTALL_LOCK:
        if _INSTALLED:
            return

        original = AliasService.find_representative
        _ORIGINAL_FIND_REPRESENTATIVE = original

        def find_representative_with_vacancies(cls, value, minimum_score=None):
            # Explicit vacancies MUST bypass accent-insensitive AliasService;
            # otherwise BOŞ is normalized to BOS before vacancy resolution.
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
