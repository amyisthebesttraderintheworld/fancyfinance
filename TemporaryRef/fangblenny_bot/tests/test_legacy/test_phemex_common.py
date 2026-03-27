"""Tests for legacy phemex_common wrapper."""

from fangblenny_bot.legacy import phemex_common as pc


class TestLegacyWrapper:
    def test_has_core_attributes(self):
        # Test that legacy wrapper exposes core functionality
        assert hasattr(pc, 'BASE_URL')
        assert hasattr(pc, 'TIMEFRAME_MAP')
        assert hasattr(pc, 'DEFAULTS')
        assert hasattr(pc, 'calc_rsi')
        assert hasattr(pc, 'get_tickers')
        assert hasattr(pc, 'SimpleCache')
        assert hasattr(pc, 'CACHE')

    def test_numpy_available(self):
        # Test that numpy is available as pc.np
        assert hasattr(pc, 'np')
        assert pc.np is not None

    def test_os_available(self):
        # Test that os is available as pc.os
        assert hasattr(pc, 'os')
        assert pc.os is not None

    def test_logger_available(self):
        # Test that logger is available
        assert hasattr(pc, 'logger')
        assert pc.logger is not None