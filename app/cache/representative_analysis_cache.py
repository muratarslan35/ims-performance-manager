"""Bounded cache for representative-heavy derived read models.

The representative page is read-only but can fan out into expensive IMS/competition
queries. This cache stores derived read-model payloads only; it never writes or
changes IMS, target, production or representative business data.

Representative market/intelligence keys already contain the active IMS upload and
scope identity. Those immutable source-keyed entries therefore stay valid for the
whole upload generation, with no calendar-day expiry. A new IMS upload naturally
produces a new key, while a web-code deploy starts fresh workers and an empty
process cache. This preserves every existing calculation/read service and only
avoids repeating the same expensive reads.
"""
from __future__ import annotations

import copy
import math
import time
from collections import OrderedDict
from threading import Event, RLock
from typing import Any, Callable

from flask import current_app, has_app_context


class RepresentativeAnalysisCache:
    _MAX_ENTRIES = 512
    _DEFAULT_TTL_SECONDS = 45
    _MAX_TTL_SECONDS = 120
    _SOURCE_KEY_PREFIXES = ("rep-market:", "rep-intelligence:")
    _WAIT_SECONDS = 30.0
    _store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
    _inflight: dict[str, Event] = {}
    _lock = RLock()

    @classmethod
    def enabled(cls) -> bool:
        # Tests should exercise the real query path unless they explicitly test
        # this cache in isolation.
        return not (has_app_context() and current_app.testing)

    @classmethod
    def _copy(cls, value: Any) -> Any:
        try:
            return copy.deepcopy(value)
        except Exception:
            # SQLAlchemy rows/simple namespaces are already immutable enough for
            # these read-only consumers. Do not let copying make the page fail.
            return value

    @classmethod
    def _ttl_for_key(cls, key: str, requested_ttl: int | None) -> float:
        """Keep upload-scoped representative reads for the source generation.

        Source-keyed representative payloads are invalidated by source identity,
        not elapsed days. Generic cache keys retain the original short TTL guard.
        This changes retention only; loaders, precedence, formulas, rounding and
        data-source selection remain untouched.
        """
        if str(key).startswith(cls._SOURCE_KEY_PREFIXES):
            return math.inf
        ttl = requested_ttl or cls._DEFAULT_TTL_SECONDS
        return float(max(1, min(int(ttl), cls._MAX_TTL_SECONDS)))

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._store.clear()
            for event in cls._inflight.values():
                event.set()
            cls._inflight.clear()

    @classmethod
    def get_or_compute(
        cls,
        key: str,
        loader: Callable[[], Any],
        *,
        ttl_seconds: int | None = None,
        force_enable: bool = False,
    ) -> Any:
        if not key or (not force_enable and not cls.enabled()):
            return loader()

        ttl = cls._ttl_for_key(key, ttl_seconds)
        now = time.monotonic()
        wait_event: Event | None = None
        owner = False

        with cls._lock:
            entry = cls._store.get(key)
            if entry is not None:
                expires_at, payload = entry
                if expires_at > now:
                    cls._store.move_to_end(key)
                    return cls._copy(payload)
                cls._store.pop(key, None)

            wait_event = cls._inflight.get(key)
            if wait_event is None:
                wait_event = Event()
                cls._inflight[key] = wait_event
                owner = True

        if not owner:
            wait_event.wait(cls._WAIT_SECONDS)
            now = time.monotonic()
            with cls._lock:
                entry = cls._store.get(key)
                if entry is not None and entry[0] > now:
                    cls._store.move_to_end(key)
                    return cls._copy(entry[1])
                # If the owner failed or timed out, one waiter becomes the new
                # owner. This prevents all waiters from recomputing together.
                current = cls._inflight.get(key)
                if current is wait_event:
                    cls._inflight.pop(key, None)
                replacement = Event()
                cls._inflight[key] = replacement
                wait_event = replacement
                owner = True

        try:
            value = loader()
        except Exception:
            with cls._lock:
                event = cls._inflight.pop(key, None)
                if event is not None:
                    event.set()
            raise

        with cls._lock:
            expires_at = math.inf if math.isinf(ttl) else time.monotonic() + ttl
            cls._store[key] = (expires_at, cls._copy(value))
            cls._store.move_to_end(key)
            while len(cls._store) > cls._MAX_ENTRIES:
                cls._store.popitem(last=False)
            event = cls._inflight.pop(key, None)
            if event is not None:
                event.set()
        return cls._copy(value)
