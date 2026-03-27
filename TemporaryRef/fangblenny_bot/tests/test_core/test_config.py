"""Tests for config module."""

import os
from fangblenny_bot.core import config


class TestConfigConstants:
    def test_base_url(self):
        assert config.BASE_URL.startswith("https://")

    def test_timeframe_map(self):
        assert isinstance(config.TIMEFRAME_MAP, dict)
        assert "1m" in config.TIMEFRAME_MAP
        assert config.TIMEFRAME_MAP["1m"] == 60

    def test_defaults(self):
        assert isinstance(config.DEFAULTS, dict)
        assert "MIN_VOLUME" in config.DEFAULTS

    def test_api_keys(self):
        # These may be None if not set
        assert hasattr(config, "CRYPTOPANIC_API_KEY")
        assert hasattr(config, "DEEPSEEK_API_KEY")