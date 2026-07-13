import re
import unicodedata
import threading
from difflib import SequenceMatcher

from app.extensions import db

from app.models import (
    Product,
    ProductAlias,
    Representative,
    RepresentativeAlias
)


class AliasService:

    _lock = threading.Lock()

    _initialized = False

    _cache_version = 1

    _product_cache = {}

    _product_alias_cache = {}

    _representative_cache = {}

    _representative_alias_cache = {}

    _statistics = {

        "product": 0,

        "product_alias": 0,

        "representative": 0,

        "representative_alias": 0,

        "cache_hits": 0,

        "cache_miss": 0

    }

    SIMILARITY_LIMIT = 0.90

    @classmethod
    def normalize(

        cls,

        value

    ):

        if value is None:

            return ""

        value = str(

            value

        ).strip()

        value = value.upper()

        value = unicodedata.normalize(

            "NFKD",

            value

        )

        value = "".join(

            c

            for c in value

            if not unicodedata.combining(

                c

            )

        )

        replacements = {

            "İ": "I",

            "İ": "I",

            "Ş": "S",

            "Ğ": "G",

            "Ü": "U",

            "Ö": "O",

            "Ç": "C"

        }

        for old, new in replacements.items():

            value = value.replace(

                old,

                new

            )

        value = re.sub(

            r"[^A-Z0-9 ]",

            " ",

            value

        )

        value = re.sub(

            r"\s+",

            " ",

            value

        )

        return value.strip()

      @classmethod
    def similarity(

        cls,

        first,

        second

    ):

        return SequenceMatcher(

            None,

            cls.normalize(

                first

            ),

            cls.normalize(

                second

            )

        ).ratio()

    @classmethod
    def exact(

        cls,

        first,

        second

    ):

        return (

            cls.normalize(

                first

            )

            ==

            cls.normalize(

                second

            )

        )

    @classmethod
    def contains(

        cls,

        source,

        target

    ):

        return (

            cls.normalize(

                target

            )

            in

            cls.normalize(

                source

            )

        )

    @classmethod
    def startswith(

        cls,

        source,

        target

    ):

        return cls.normalize(

            source

        ).startswith(

            cls.normalize(

                target

            )

        )

    @classmethod
    def endswith(

        cls,

        source,

        target

    ):

        return cls.normalize(

            source

        ).endswith(

            cls.normalize(

                target

            )

        )

    @classmethod
    def refresh(

        cls

    ):

        with cls._lock:

            cls._initialized = False

            cls.load_cache()


    @classmethod
    def load_cache(

        cls

    ):

        with cls._lock:

            if cls._initialized:

                return

            cls._product_cache.clear()

            cls._product_alias_cache.clear()

            cls._representative_cache.clear()

            cls._representative_alias_cache.clear()

            cls._statistics["product"] = 0

            cls._statistics["product_alias"] = 0

            cls._statistics["representative"] = 0

            cls._statistics["representative_alias"] = 0

            products = Product.query.filter_by(

                is_active=True

            ).all()

            for product in products:

                cls._statistics["product"] += 1

                if product.product_name:

                    cls._product_cache[

                        cls.normalize(

                            product.product_name

                        )

                    ] = product

                if product.product_code:

                    cls._product_cache[

                        cls.normalize(

                            product.product_code

                        )

                    ] = product

                if product.ims_name:

                    cls._product_cache[

                        cls.normalize(

                            product.ims_name

                        )

                    ] = product


                      aliases = ProductAlias.query.all()

            for alias in aliases:

                cls._statistics["product_alias"] += 1

                cls._product_alias_cache[

                    cls.normalize(

                        alias.alias_name

                    )

                ] = alias.product


            aliases = RepresentativeAlias.query.all()

            for alias in aliases:

                cls._statistics[

                    "representative_alias"

                ] += 1

                cls._representative_alias_cache[

                    cls.normalize(

                        alias.alias_name

                    )

                ] = alias.representative

            cls._initialized = True

          @classmethod
    def cache_loaded(

        cls

    ):

        return cls._initialized

      @classmethod
    def cache_version(

        cls

    ):

        return cls._cache_version

    @classmethod
    def cache_statistics(

        cls

    ):

        return dict(

            cls._statistics

        )

    @classmethod
    def clear_cache(

        cls

    ):

        with cls._lock:

            cls._initialized = False

            cls._product_cache.clear()

            cls._product_alias_cache.clear()

            cls._representative_cache.clear()

            cls._representative_alias_cache.clear()

          @classmethod
    def clean_name(

        cls,

        value

    ):

        value = cls.normalize(

            value

        )

        removable = [

            " TABLET",

            " TAB",

            " FILM TABLET",

            " KAPSUL",

            " KAPSÜL",

            " SASE",

            " SAŞE",

            " AMPUL",

            " AMPOL",

            " FLAKON",

            " KREM",

            " JEL",

            " LOSYON",

            " SOLUSYON",

            " SOLÜSYON",

            " SURUP",

            " ŞURUP",

            " MG",

            " G",

            " GR",

            " ML",

            " IU",

            " IUML",

            " %",

            "®",

            "™"

        ]

        for item in removable:

            value = value.replace(

                item,

                ""

            )

        value = re.sub(

            r"\d+",

            "",

            value

        )

        value = re.sub(

            r"\s+",

            " ",

            value

        )

        return value.strip()


    @classmethod
    def build_match(

        cls,

        matched,

        score,

        method,

        obj

    ):

        return {

            "matched": matched,

            "score": round(

                score,

                2

            ),

            "method": method,

            "object": obj

        }


    @classmethod
    def exact_match(

        cls,

        source,

        cache

    ):

        key = cls.normalize(

            source

        )

        if key in cache:

            cls._statistics["cache_hits"] += 1

            return cls.build_match(

                True,

                100,

                "EXACT",

                cache[key]

            )

        cls._statistics["cache_miss"] += 1

        return None


    @classmethod
    def contains_match(

        cls,

        source,

        cache

    ):

        source = cls.clean_name(

            source

        )

        for key, obj in cache.items():

            if source in key:

                return cls.build_match(

                    True,

                    96,

                    "CONTAINS",

                    obj

                )

        return None


    @classmethod
    def startswith_match(

        cls,

        source,

        cache

    ):

        source = cls.clean_name(

            source

        )

        for key, obj in cache.items():

            if key.startswith(

                source

            ):

                return cls.build_match(

                    True,

                    95,

                    "STARTSWITH",

                    obj

                )

        return None


    @classmethod
    def endswith_match(

        cls,

        source,

        cache

    ):

        source = cls.clean_name(

            source

        )

        for key, obj in cache.items():

            if key.endswith(

                source

            ):

                return cls.build_match(

                    True,

                    95,

                    "ENDSWITH",

                    obj

                )

        return None


    @classmethod
    def similarity_match(

        cls,

        source,

        cache,

        minimum=None

    ):

        minimum = minimum or cls.SIMILARITY_LIMIT

        best_score = 0

        best_object = None

        for key, obj in cache.items():

            score = cls.similarity(

                source,

                key

            )

            if score > best_score:

                best_score = score

                best_object = obj

        if best_score >= minimum:

            return cls.build_match(

                True,

                best_score * 100,

                "SIMILARITY",

                best_object

            )

        return None

    @classmethod
    def find_product(

        cls,

        value,

        minimum_score=None

    ):

        cls.load_cache()

        if not value:

            return cls.build_match(

                False,

                0,

                "EMPTY",

                None

            )

        minimum = (

            minimum_score

            if minimum_score is not None

            else cls.SIMILARITY_LIMIT

        )

        normalized = cls.normalize(

            value

        )

        cleaned = cls.clean_name(

            value

        )

        searches = [

            normalized,

            cleaned

        ]

        for search in searches:

            result = cls.exact_match(

                search,

                cls._product_cache

            )

            if result:

                return result

        for search in searches:

            result = cls.exact_match(

                search,

                cls._product_alias_cache

            )

            if result:

                result["method"] = "ALIAS"

                return result

        for search in searches:

            result = cls.contains_match(

                search,

                cls._product_cache

            )

            if result:

                return result

        for search in searches:

            result = cls.contains_match(

                search,

                cls._product_alias_cache

            )

            if result:

                result["method"] = "ALIAS_CONTAINS"

                return result

        for search in searches:

            result = cls.startswith_match(

                search,

                cls._product_cache

            )

            if result:

                return result

        for search in searches:

            result = cls.endswith_match(

                search,

                cls._product_cache

            )

            if result:

                return result

        best = cls.similarity_match(

            normalized,

            cls._product_cache,

            minimum

        )

        alias_best = cls.similarity_match(

            normalized,

            cls._product_alias_cache,

            minimum

        )

        if alias_best:

            if (

                best is None

                or

                alias_best["score"] >

                best["score"]

            ):

                alias_best["method"] = "ALIAS_SIMILARITY"

                best = alias_best

        if best:

            return best

        return cls.build_match(

            False,

            0,

            "NO_MATCH",

            None

            )

    @classmethod
    def find_representative(

        cls,

        value,

        minimum_score=None

    ):

        cls.load_cache()

        if not value:

            return cls.build_match(

                False,

                0,

                "EMPTY",

                None

            )

        minimum = (

            minimum_score

            if minimum_score is not None

            else cls.SIMILARITY_LIMIT

        )

        normalized = cls.normalize(

            value

        )

        cleaned = cls.clean_name(

            value

        )

        searches = [

            normalized,

            cleaned

        ]

        for search in searches:

            result = cls.exact_match(

                search,

                cls._representative_cache

            )

            if result:

                return result

        for search in searches:

            result = cls.exact_match(

                search,

                cls._representative_alias_cache

            )

            if result:

                result["method"] = "ALIAS"

                return result

        for search in searches:

            result = cls.contains_match(

                search,

                cls._representative_cache

            )

            if result:

                return result

        for search in searches:

            result = cls.contains_match(

                search,

                cls._representative_alias_cache

            )

            if result:

                result["method"] = "ALIAS_CONTAINS"

                return result

        best = cls.similarity_match(

            normalized,

            cls._representative_cache,

            minimum

        )

        alias_best = cls.similarity_match(

            normalized,

            cls._representative_alias_cache,

            minimum

        )

        if alias_best:

            if (

                best is None

                or

                alias_best["score"] >

                best["score"]

            ):

                alias_best["method"] = "ALIAS_SIMILARITY"

                best = alias_best

        if best:

            return best

        return cls.build_match(

            False,

            0,

            "NO_MATCH",

            None

        )

    @classmethod
    def product_id(

        cls,

        value

    ):

        result = cls.find_product(

            value

        )

        if result["matched"]:

            return result["object"].id

        return None


    @classmethod
    def representative_id(

        cls,

        value

    ):

        result = cls.find_representative(

            value

        )

        if result["matched"]:

            return result["object"].id

        return None


    @classmethod
    def exists_product(

        cls,

        value

    ):

        return cls.find_product(

            value

        )["matched"]


    @classmethod
    def exists_representative(

        cls,

        value

    ):

        return cls.find_representative(

            value

        )["matched"]

      @classmethod
    def match_product_list(

        cls,

        values,

        minimum_score=None

    ):

        cls.load_cache()

        matched = []

        unmatched = []

        for value in values:

            result = cls.find_product(

                value,

                minimum_score

            )

            if result["matched"]:

                matched.append(

                    {

                        "source": value,

                        "product_id": result["object"].id,

                        "product_name": result["object"].product_name,

                        "score": result["score"],

                        "method": result["method"]

                    }

                )

            else:

                unmatched.append(

                    value

                )

        return {

            "matched": matched,

            "unmatched": unmatched,

            "matched_count": len(

                matched

            ),

            "unmatched_count": len(

                unmatched

            )

        }


    @classmethod
    def match_representative_list(

        cls,

        values,

        minimum_score=None

    ):

        cls.load_cache()

        matched = []

        unmatched = []

        for value in values:

            result = cls.find_representative(

                value,

                minimum_score

            )

            if result["matched"]:

                matched.append(

                    {

                        "source": value,

                        "representative_id": result["object"].id,

                        "representative_name": result["object"].rep_name,

                        "score": result["score"],

                        "method": result["method"]

                    }

                )

            else:

                unmatched.append(

                    value

                )

        return {

            "matched": matched,

            "unmatched": unmatched,

            "matched_count": len(

                matched

            ),

            "unmatched_count": len(

                unmatched

            )

        }


    @classmethod
    def create_product_alias(

        cls,

        product,

        alias_name

    ):

        cls.load_cache()

        if product is None:

            return None

        normalized = cls.normalize(

            alias_name

        )

        if normalized in cls._product_alias_cache:

            return cls._product_alias_cache[

                normalized

            ]

        alias = ProductAlias(

            product_id=product.id,

            alias_name=alias_name.strip()

        )

        db.session.add(

            alias

        )

        db.session.commit()

        cls.refresh()

        return alias


    @classmethod
    def create_representative_alias(

        cls,

        representative,

        alias_name

    ):

        cls.load_cache()

        if representative is None:

            return None

        normalized = cls.normalize(

            alias_name

        )

        if normalized in cls._representative_alias_cache:

            return cls._representative_alias_cache[

                normalized

            ]

        alias = RepresentativeAlias(

            representative_id=representative.id,

            alias_name=alias_name.strip()

        )

        db.session.add(

            alias

        )

        db.session.commit()

        cls.refresh()

        return alias


    @classmethod
    def alias_conflicts(

        cls

    ):

        cls.load_cache()

        conflicts = []

        seen = {}

        for alias in ProductAlias.query.all():

            key = cls.normalize(

                alias.alias_name

            )

            if key not in seen:

                seen[key] = alias.product_id

                continue

            if seen[key] != alias.product_id:

                conflicts.append(

                    {

                        "alias": alias.alias_name,

                        "first_product": seen[key],

                        "second_product": alias.product_id

                    }

                )

        return conflicts


    @classmethod
    def representative_conflicts(

        cls

    ):

        cls.load_cache()

        conflicts = []

        seen = {}

        for alias in RepresentativeAlias.query.all():

            key = cls.normalize(

                alias.alias_name

            )

            if key not in seen:

                seen[key] = alias.representative_id

                continue

            if seen[key] != alias.representative_id:

                conflicts.append(

                    {

                        "alias": alias.alias_name,

                        "first_representative": seen[key],

                        "second_representative": alias.representative_id

                    }

                )

        return conflicts

    @classmethod
    def statistics(

        cls

    ):

        cls.load_cache()

        hit = cls._statistics.get(

            "cache_hits",

            0

        )

        miss = cls._statistics.get(

            "cache_miss",

            0

        )

        total = hit + miss

        ratio = 0

        if total > 0:

            ratio = round(

                (

                    hit /

                    total

                ) * 100,

                2

            )

        return {

            "cache_version":

                cls._cache_version,

            "initialized":

                cls._initialized,

            "products":

                cls._statistics["product"],

            "product_aliases":

                cls._statistics["product_alias"],

            "representatives":

                cls._statistics["representative"],

            "representative_aliases":

                cls._statistics["representative_alias"],

            "cache_hits":

                hit,

            "cache_miss":

                miss,

            "hit_ratio":

                ratio,

            "product_cache_size":

                len(

                    cls._product_cache

                ),

            "product_alias_cache_size":

                len(

                    cls._product_alias_cache

                ),

            "representative_cache_size":

                len(

                    cls._representative_cache

                ),

            "representative_alias_cache_size":

                len(

                    cls._representative_alias_cache

                )

        }


    @classmethod
    def reset_statistics(

        cls

    ):

        cls._statistics["cache_hits"] = 0

        cls._statistics["cache_miss"] = 0

        return cls.statistics()


    @classmethod
    def validate(

        cls

    ):

        cls.load_cache()

        errors = []

        if not cls._product_cache:

            errors.append(

                "Product cache boş."

            )

        if not cls._representative_cache:

            errors.append(

                "Representative cache boş."

            )

        if len(

            cls.alias_conflicts()

        ) > 0:

            errors.append(

                "Product alias çakışmaları bulundu."

            )

        if len(

            cls.representative_conflicts()

        ) > 0:

            errors.append(

                "Representative alias çakışmaları bulundu."

            )

        return {

            "success":

                len(

                    errors

                ) == 0,

            "errors":

                errors,

            "statistics":

                cls.statistics()

        }


    @classmethod
    def health_check(

        cls

    ):

        report = cls.validate()

        report["service"] = "AliasService"

        report["status"] = (

            "Healthy"

            if report["success"]

            else "Warning"

        )

        return report


    @classmethod
    def warmup(

        cls

    ):

        cls.load_cache()

        return cls.statistics()


    @classmethod
    def export_cache(

        cls

    ):

        cls.load_cache()

        return {

            "products":

                list(

                    cls._product_cache.keys()

                ),

            "product_aliases":

                list(

                    cls._product_alias_cache.keys()

                ),

            "representatives":

                list(

                    cls._representative_cache.keys()

                ),

            "representative_aliases":

                list(

                    cls._representative_alias_cache.keys()

                )

        }


    @classmethod
    def clear(

        cls

    ):

        cls.clear_cache()

        cls.reset_statistics()

        return True
