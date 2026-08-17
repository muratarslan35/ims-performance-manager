"""Deterministic matching for explicit empty-headcount representative labels."""

from __future__ import annotations

import threading

from app.models import Representative
from app.services.alias_service import AliasService


_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_FIND_REPRESENTATIVE = None
_VACANCY_CACHE = {}


def _is_explicit_vacancy(normalized: str) -> bool:
    tokens = set(normalized.split())
    return "BOS" in tokens or "KADRO" in tokens


def _vacancy_candidate(source_normalized: str):
    cached = _VACANCY_CACHE.get(source_normalized)
    if cached is not None:
        return cached

    scored = []
    for representative in Representative.query.all():
        rep_name = AliasService.normalize(representative.rep_name)
        territory = AliasService.normalize(representative.territory)
        code = AliasService.normalize(representative.rep_code)
        ims_code = AliasService.normalize(representative.ims_code)

        master_tokens = set(rep_name.split()) | set(territory.split())
        if "BOS" not in master_tokens and "KADRO" not in master_tokens and not code.startswith("UNASSIGNED"):
            continue

        labels = [label for label in (rep_name, territory, code, ims_code) if label]
        score = 0
        method = None
        if source_normalized in labels:
            score, method = 100, "VACANCY_EXACT"
        elif rep_name.endswith(" " + source_normalized):
            score, method = 99, "VACANCY_SUFFIX"
        elif territory and territory.endswith(" " + source_normalized):
            score, method = 98, "VACANCY_TERRITORY_SUFFIX"

        if score:
            scored.append((score, representative.id, method, representative))

    if not scored:
        result = None
    else:
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score = scored[0][0]
        best = [item for item in scored if item[0] == best_score]
        # Never guess between equally strong empty-headcount candidates.
        result = best[0] if len(best) == 1 else None

    _VACANCY_CACHE[source_normalized] = result
    return result


def install_vacancy_matcher() -> None:
    """Extend the central AliasService without changing normal-name matching.

    Only explicit BOS/KADRO source labels reach the fallback.  Normal employees,
    cities such as Bostancı, and fuzzy matches retain AliasService's existing
    behaviour.  Ambiguous vacancy matches remain unmatched instead of guessing.
    """
    global _INSTALLED, _ORIGINAL_FIND_REPRESENTATIVE
    if _INSTALLED:
        return

    with _INSTALL_LOCK:
        if _INSTALLED:
            return

        original = AliasService.find_representative
        _ORIGINAL_FIND_REPRESENTATIVE = original

        def find_representative_with_vacancies(cls, value, minimum_score=None):
            result = original(value, minimum_score)
            if result.get("matched"):
                return result

            normalized = AliasService.normalize(value)
            if not _is_explicit_vacancy(normalized):
                return result

            candidate = _vacancy_candidate(normalized)
            if candidate is None:
                return result

            score, _identifier, method, representative = candidate
            return AliasService.build_match(True, score, method, representative)

        AliasService.find_representative = classmethod(find_representative_with_vacancies)
        _INSTALLED = True


def clear_vacancy_match_cache() -> None:
    _VACANCY_CACHE.clear()
