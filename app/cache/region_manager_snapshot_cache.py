"""Upload-versioned snapshot cache for the manager region cockpit.

The manager cockpit only reads existing region services. A region snapshot is
expensive enough that rebuilding it on every click is wasteful, while the source
is stable until a new IMS/production upload arrives. Cache keys therefore include
the latest completed IMS upload and final production upload identity. A new source
naturally creates a new key without explicit invalidation.
"""
from __future__ import annotations

import copy
import time
from collections import OrderedDict
from threading import Event, RLock
from typing import Any, Callable

from flask import current_app, has_app_context


class RegionManagerSnapshotCache:
    _MAX_ENTRIES = 256
    _TTL_SECONDS = 8 * 24 * 60 * 60
    _WAIT_SECONDS = 30.0
    _store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
    _inflight: dict[str, Event] = {}
    _lock = RLock()

    @classmethod
    def enabled(cls) -> bool:
        return not (has_app_context() and current_app.testing)

    @classmethod
    def _copy(cls, value: Any) -> Any:
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._store.clear()
            for event in cls._inflight.values():
                event.set()
            cls._inflight.clear()

    @classmethod
    def get_or_compute(cls, key: str, loader: Callable[[], Any]) -> Any:
        if not key or not cls.enabled():
            return loader()

        now = time.monotonic()
        owner = False
        with cls._lock:
            entry = cls._store.get(key)
            if entry and entry[0] > now:
                cls._store.move_to_end(key)
                return cls._copy(entry[1])
            if entry:
                cls._store.pop(key, None)
            event = cls._inflight.get(key)
            if event is None:
                event = Event()
                cls._inflight[key] = event
                owner = True

        if not owner:
            event.wait(cls._WAIT_SECONDS)
            now = time.monotonic()
            with cls._lock:
                entry = cls._store.get(key)
                if entry and entry[0] > now:
                    cls._store.move_to_end(key)
                    return cls._copy(entry[1])
                if cls._inflight.get(key) is event:
                    cls._inflight.pop(key, None)
                event = Event()
                cls._inflight[key] = event

        try:
            value = loader()
        except Exception:
            with cls._lock:
                pending = cls._inflight.pop(key, None)
                if pending is not None:
                    pending.set()
            raise

        with cls._lock:
            cls._store[key] = (time.monotonic() + cls._TTL_SECONDS, cls._copy(value))
            cls._store.move_to_end(key)
            while len(cls._store) > cls._MAX_ENTRIES:
                cls._store.popitem(last=False)
            pending = cls._inflight.pop(key, None)
            if pending is not None:
                pending.set()
        return cls._copy(value)
