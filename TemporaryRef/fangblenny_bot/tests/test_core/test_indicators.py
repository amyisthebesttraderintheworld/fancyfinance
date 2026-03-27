"""Tests for indicators module."""

import numpy as np
from fangblenny_bot.core.indicators import (
    calc_rsi,
    calc_bb,
    calc_ema_series,
    calc_ema_slope,
    calc_atr,
    calc_volume_profile,
    calc_volume_spike,
)


class TestCalcRsi:
    def test_insufficient_data(self):
        closes = [100, 101, 102]
        current, prev, history = calc_rsi(closes, period=14)
        assert current is None
        assert prev is None
        assert len(history) == 3

    def test_basic_rsi(self):
        # Simple uptrend
        closes = [100 + i for i in range(20)]
        current, prev, history = calc_rsi(closes, period=14)
        assert current is not None
        assert 50 < current <= 100  # RSI in uptrend

    def test_rsi_overbought(self):
        # Strong uptrend
        closes = [100 + i*2 for i in range(20)]
        current, prev, history = calc_rsi(closes, period=14)
        assert current > 70


class TestCalcBb:
    def test_insufficient_data(self):
        closes = [100, 101, 102]
        result = calc_bb(closes, period=21)
        assert result is None

    def test_basic_bb(self):
        closes = [100 + np.sin(i/10) for i in range(30)]
        result = calc_bb(closes, period=21)
        assert result is not None
        assert "upper" in result
        assert "mid" in result
        assert "lower" in result
        assert result["upper"] > result["mid"] > result["lower"]


class TestCalcEmaSeries:
    def test_insufficient_data(self):
        closes = [100, 101]
        series = calc_ema_series(closes, period=10)
        assert series == []

    def test_basic_ema(self):
        closes = [100 + i for i in range(20)]
        series = calc_ema_series(closes, period=10)
        # For closes of len 20 and period 10:
        # first EMA is average of first 10.
        # Then we have 10 more closes [10...19] which each add one EMA point.
        # Total EMA series len = (20 - 10) + 1 = 11
        assert len(series) == 11
        assert series[0] > 100  # EMA starts after period


class TestCalcEmaSlope:
    def test_insufficient_data(self):
        series = [100, 101]
        slope, delta = calc_ema_slope(series, lookback=3)
        assert slope is None
        assert delta is None

    def test_basic_slope(self):
        series = [100 + i for i in range(10)]
        slope, delta = calc_ema_slope(series, lookback=3)
        assert slope is not None
        assert slope > 0  # Increasing series


class TestCalcAtr:
    def test_insufficient_data(self):
        highs = [101, 102]
        lows = [99, 100]
        closes = [100, 101]
        atr = calc_atr(highs, lows, closes, period=14)
        assert atr is None

    def test_basic_atr(self):
        highs = [102, 103, 104]
        lows = [98, 99, 100]
        closes = [100, 101, 102]
        atr = calc_atr(highs, lows, closes, period=2)
        assert atr is not None
        assert atr > 0


class TestCalcVolumeProfile:
    def test_empty_data(self):
        poc, nodes = calc_volume_profile([], [])
        assert poc is None
        assert nodes == []

    def test_basic_profile(self):
        ohlc = [(100, 105, 95, 102), (102, 107, 97, 104)]
        volumes = [1000, 1500]
        poc, nodes = calc_volume_profile(ohlc, volumes)
        assert poc is not None
        assert isinstance(nodes, list)


class TestCalcVolumeSpike:
    def test_insufficient_data(self):
        volumes = [1000, 1100]
        spike = calc_volume_spike(volumes, period=20)
        assert spike == 1.0

    def test_basic_spike(self):
        volumes = [1000] * 25  # 25 periods
        volumes[-1] = 2000  # Last volume doubled
        spike = calc_volume_spike(volumes, period=20)
        assert spike == 2.0
