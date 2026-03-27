from __future__ import annotations

import threading
import time
from typing import Any, Dict, Tuple


class SimpleCache:
    def __init__(self, ttl: float = 30.0):
        self._data: Dict[str, Tuple[float, Any]] = {}
        self._ttl = float(ttl)
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            ts, val = entry
            if time.time() - ts > self._ttl:
                del self._data[key]
                return None
            return val

    def set(self, key: str, val: Any):
        with self._lock:
            self._data[key] = (time.time(), val)


# global shared cache instance with default 30s TTL
CACHE = SimpleCache(ttl=30.0)
