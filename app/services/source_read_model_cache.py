"""Small source-versioned cache for expensive presentation-only read models."""
from collections import OrderedDict
from threading import RLock


class SourceReadModelCache:
    """Bound memory while reusing immutable output until its source ids change."""

    _entries = OrderedDict()
    _lock = RLock()
    MAX_ENTRIES = 16

    @classmethod
    def get_or_build(cls, key, builder):
        normalized = tuple(key)
        with cls._lock:
            ready = cls._entries.get(normalized)
            if ready is not None:
                cls._entries.move_to_end(normalized)
                return ready

        built = builder()
        with cls._lock:
            ready = cls._entries.get(normalized)
            if ready is not None:
                cls._entries.move_to_end(normalized)
                return ready
            cls._entries[normalized] = built
            cls._entries.move_to_end(normalized)
            while len(cls._entries) > cls.MAX_ENTRIES:
                cls._entries.popitem(last=False)
            return built

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._entries.clear()
