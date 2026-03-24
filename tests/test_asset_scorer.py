"""Tests for asset_scorer.AssetScorer."""
import sys
import os
import types

# --- Stub out loguru so common.py imports cleanly without the package ---
loguru_stub = types.ModuleType("loguru")
class _Logger:
    def bind(self, **kw): return self
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def remove(self): pass
    def add(self, *a, **kw): pass
loguru_stub.logger = _Logger()
sys.modules["loguru"] = loguru_stub
# -------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import pytest
from asset_scorer import AssetScorer, ScoreResult


def make_config(overrides=None):
    cfg = {
        "strategy": {
            "fast_ma": 9, "slow_ma": 21, "rsi_period": 14,
            "rsi_oversold": 30, "rsi_overbought": 70,
            "atr_period": 14, "volume_multiplier": 1.5,
        },
        "risk": {},
        "scoring": {
            "trend_weight": 30, "rsi_weight": 25,
            "volume_weight": 25, "momentum_weight": 20,
            "min_score": 45,
        },
    }
    if overrides:
        cfg["scoring"].update(overrides)
    return cfg


def make_df(
    fast_ma=100.5, slow_ma=100.0, rsi=25.0,
    volume=2000, avg_volume=1000,
    close_series=None, atr=1.0,
    rows=10
):
    """Build a minimal indicator DataFrame mimicking scanner output."""
    closes = close_series if close_series is not None else [100.0] * rows
    df = pd.DataFrame({
        "close":    closes,
        "fast_ma":  [fast_ma] * rows,
        "slow_ma":  [slow_ma] * rows,
        "rsi":      [rsi] * rows,
        "volume":   [volume] * rows,
        "avg_volume": [avg_volume] * rows,
        "atr":      [atr] * rows,
    })
    return df


# ── Initialisation ───────────────────────────────────────────────────────────

def test_weights_normalised_if_not_100():
    cfg = make_config({"trend_weight": 10, "rsi_weight": 10,
                       "volume_weight": 10, "momentum_weight": 10})
    scorer = AssetScorer(cfg)
    total = scorer.w_trend + scorer.w_rsi + scorer.w_volume + scorer.w_momentum
    assert abs(total - 100.0) < 0.01


# ── Score bounds ─────────────────────────────────────────────────────────────

def test_score_total_bounded_0_100_long():
    scorer = AssetScorer(make_config())
    df = make_df(fast_ma=105, slow_ma=100, rsi=20, volume=5000, avg_volume=1000)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    assert 0 <= result.total <= 100


def test_score_total_bounded_0_100_short():
    scorer = AssetScorer(make_config())
    df = make_df(fast_ma=95, slow_ma=100, rsi=80, volume=5000, avg_volume=1000)
    result = scorer.score(df, direction="short", rsi_overbought=70)
    assert 0 <= result.total <= 100


def test_empty_df_returns_zero():
    scorer = AssetScorer(make_config())
    result = scorer.score(pd.DataFrame(), direction="long")
    assert result.total == 0.0


# ── Direction logic ───────────────────────────────────────────────────────────

def test_wrong_direction_trend_is_zero():
    """fast_ma < slow_ma should give 0 trend score for a long setup."""
    scorer = AssetScorer(make_config())
    df = make_df(fast_ma=99, slow_ma=100)
    result = scorer.score(df, direction="long")
    assert result.breakdown["trend"] == 0.0


def test_correct_direction_trend_is_positive():
    scorer = AssetScorer(make_config())
    df = make_df(fast_ma=102, slow_ma=100)
    result = scorer.score(df, direction="long")
    assert result.breakdown["trend"] > 0


def test_rsi_oversold_gives_full_rsi_score_long():
    scorer = AssetScorer(make_config())
    # RSI exactly at oversold (30) should give maximum rsi sub-score
    df = make_df(rsi=30)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    # rsi sub-score should be 25 pts (full weight)
    assert result.breakdown["rsi"] == pytest.approx(scorer.w_rsi, rel=0.01)


def test_rsi_overbought_gives_full_rsi_score_short():
    scorer = AssetScorer(make_config())
    df = make_df(rsi=70)
    result = scorer.score(df, direction="short", rsi_overbought=70)
    assert result.breakdown["rsi"] == pytest.approx(scorer.w_rsi, rel=0.01)


def test_rsi_neutral_gives_zero_rsi_long():
    scorer = AssetScorer(make_config())
    df = make_df(rsi=55)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    assert result.breakdown["rsi"] == 0.0


# ── Volume sub-score ──────────────────────────────────────────────────────────

def test_volume_below_average_gives_zero():
    scorer = AssetScorer(make_config())
    df = make_df(volume=800, avg_volume=1000)
    result = scorer.score(df, direction="long")
    assert result.breakdown["volume"] == 0.0


def test_volume_surge_gives_positive_score():
    scorer = AssetScorer(make_config())
    df = make_df(volume=3000, avg_volume=1000)   # 3x avg
    result = scorer.score(df, direction="long")
    assert result.breakdown["volume"] > 0


# ── Momentum sub-score ────────────────────────────────────────────────────────

def test_momentum_rising_close_scores_long():
    scorer = AssetScorer(make_config())
    closes = [100.0, 100.5, 101.0, 101.5, 102.5, 103.0]
    df = make_df(close_series=closes, atr=1.0, rows=len(closes))
    result = scorer.score(df, direction="long")
    assert result.breakdown["momentum"] > 0


def test_momentum_falling_close_scores_zero_for_long():
    scorer = AssetScorer(make_config())
    closes = [103.0, 102.5, 101.5, 101.0, 100.5, 100.0]
    df = make_df(close_series=closes, atr=1.0, rows=len(closes))
    result = scorer.score(df, direction="long")
    assert result.breakdown["momentum"] == 0.0


# ── min_score gate ────────────────────────────────────────────────────────────

def test_passes_min_score_high_score():
    scorer = AssetScorer(make_config({"min_score": 20}))
    df = make_df(fast_ma=105, slow_ma=100, rsi=20, volume=3000, avg_volume=1000)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    assert scorer.passes_min_score(result)


def test_fails_min_score_weak_setup():
    scorer = AssetScorer(make_config({"min_score": 90}))
    df = make_df(fast_ma=100.01, slow_ma=100, rsi=48, volume=1050, avg_volume=1000)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    assert not scorer.passes_min_score(result)


# ── ScoreResult helpers ───────────────────────────────────────────────────────

def test_score_result_str_contains_total():
    scorer = AssetScorer(make_config())
    df = make_df()
    result = scorer.score(df, direction="long", symbol="BTCUSD")
    assert "BTCUSD" in str(result)
    assert "total=" in str(result)


def test_breakdown_keys_present():
    scorer = AssetScorer(make_config())
    df = make_df()
    result = scorer.score(df, direction="long")
    assert set(result.breakdown.keys()) == {"trend", "rsi", "volume", "momentum"}


def test_breakdown_sums_to_total():
    scorer = AssetScorer(make_config())
    df = make_df(fast_ma=103, slow_ma=100, rsi=25, volume=2500, avg_volume=1000)
    result = scorer.score(df, direction="long", rsi_oversold=30)
    assert abs(sum(result.breakdown.values()) - result.total) < 0.01
