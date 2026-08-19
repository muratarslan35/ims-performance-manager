"""Single deterministic representative resolver for every IMS parser.

Normal people use AliasService's persistent/exact/alias/normalized/fuzzy chain.
Explicit vacancy/headcount labels bypass accent-insensitive normalization so
BOS and BOŞ remain different stable slots.  Ambiguous vacancy matches never
fall back to a normal accent-insensitive guess.
"""
from __future__ import annotations

from app.services.alias_service import AliasService
from app.services.vacancy_matching import vacancy_identity, resolve_vacancy_match


class RepresentativeResolver:
    @staticmethod
    def cache_key(value):
        vacancy = vacancy_identity(value)
        if vacancy is not None:
            return ("VACANCY",) + vacancy
        return ("PERSON", AliasService.normalize(value))

    @classmethod
    def resolve(cls, value, minimum_score=None):
        if vacancy_identity(value) is not None:
            return resolve_vacancy_match(value)
        return AliasService.find_representative(value, minimum_score)
