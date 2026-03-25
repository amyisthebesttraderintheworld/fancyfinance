"""Tests for cache module."""

import time
from fangblenny_bot.core.cache import SimpleCache, CACHE


class TestSimpleCache:
    def test_get_nonexistent(self):
        cache = SimpleCache()
        assert cache.get("missing") is None

    def test_set_and_get(self):
        cache = SimpleCache()
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_ttl_expiry(self):
        cache = SimpleCache(ttl=0.1)  # short TTL
        cache.set("key", "value")
        assert cache.get("key") == "value"
        time.sleep(0.2)
        assert cache.get("key") is None

    def test_no_ttl_expiry(self):
        cache = SimpleCache(ttl=10)
        cache.set("key", "value")
        time.sleep(0.1)  # much less than TTL
        assert cache.get("key") == "value"


class TestGlobalCache:
    def test_global_cache_instance(self):
        # Test that CACHE is an instance of SimpleCache
        assert isinstance(CACHE, SimpleCache)
        CACHE.set("test", "data")
        assert CACHE.get("test") == "data"