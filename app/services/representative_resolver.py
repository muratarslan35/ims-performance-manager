"""Single deterministic representative resolver for every IMS parser.

Normal people use AliasService's persistent/exact/alias/normalized/fuzzy chain.
Explicit vacancy/headcount labels bypass accent-insensitive normalization so
BOS and BOŞ remain different stable slots. Ambiguous vacancy matches never
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


def install_representative_resolver():
    """Make IMS and target import paths use exactly the same resolver/cache key."""
    from app.services.ims_import_service import IMSImportService
    from app.services.target_import_service import TargetImportService

    if not getattr(IMSImportService, "_central_representative_resolver_installed", False):
        def resolve_ims(self, representative_name):
            key = RepresentativeResolver.cache_key(representative_name)
            if key not in self._representative_match_cache:
                self._representative_match_cache[key] = RepresentativeResolver.resolve(representative_name)
            return self._representative_match_cache[key]
        IMSImportService.resolve_representative_match = resolve_ims
        IMSImportService._central_representative_resolver_installed = True

    if not getattr(TargetImportService, "_central_representative_resolver_installed", False):
        def resolve_target(self, representative_name):
            key = RepresentativeResolver.cache_key(representative_name)
            if key not in self._representative_match_cache:
                result = RepresentativeResolver.resolve(representative_name)
                self._representative_match_cache[key] = result
                if result.get("matched"):
                    self.statistics["matched_representatives"] += 1
                else:
                    self.statistics["unmatched_representatives"] += 1
            return self._representative_match_cache[key]
        TargetImportService._resolve_representative_match = resolve_target
        TargetImportService._central_representative_resolver_installed = True
