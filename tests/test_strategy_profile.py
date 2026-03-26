import pytest

from strategy_profile import normalize_strategy_profile


def test_normalize_strategy_profile_rejects_invalid_explicit_candles(sample_config):
    with pytest.raises(ValueError, match="Backtest candles must be one of"):
        normalize_strategy_profile(sample_config, {"candles": 750})


def test_normalize_strategy_profile_coerces_legacy_current_candles(sample_config):
    profile = normalize_strategy_profile(sample_config, {}, current={"candles": 100})

    assert profile["candles"] == 500
