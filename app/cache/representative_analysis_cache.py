"""Short-lived, bounded cache for representative-heavy read models.

The representative page is read-only but can fan out into expensive IMS/competition
queries.  This cache deliberately stores only derived read-model payloads and is
keyed with the relevant upload identity, so a new IMS upload naturally produces a
new key.  It also coalesces concurrent misses inside each worker to avoid a cache
stampede.
"""
from __future__ import annotations

import copy
import time
from collections import OrderedDict
from threading import Event, RLock
from typing import Any, Callable

from flask import current_app, has_app_context


class RepresentativeAnalysisCache:
    _MAX_ENTRIES = 512
    _DEFAULT_TTL_SECONDS = 45
    _MAX_TTL_SECONDS = 120
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
            # these read-only consumers.  Do not let copying make the page fail.
            return value

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

        ttl = ttl_seconds or cls._DEFAULT_TTL_SECONDS
        ttl = max(1, min(int(ttl), cls._MAX_TTL_SECONDS))
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
                # owner.  This prevents all waiters from recomputing together.
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
            cls._store[key] = (time.monotonic() + ttl, cls._copy(value))
            cls._store.move_to_end(key)
            while len(cls._store) > cls._MAX_ENTRIES:
                cls._store.popitem(last=False)
            event = cls._inflight.pop(key, None)
            if event is not None:
                event.set()
        return cls._copy(value)
