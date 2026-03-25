import pandas as pd
import pytest

import backtest_service


def test_run_backtest_returns_report(sample_config, monkeypatch):
    dates = pd.date_range("2024-01-01", periods=60, freq="1min")
    prices = [1000 - i * 3 for i in range(30)] + [910 + i * 4 for i in range(30)]
    frame = pd.DataFrame(
        {
            "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
            "open": prices,
            "high": [price + 5 for price in prices],
            "low": [price - 5 for price in prices],
            "close": prices,
            "volume": [1000] * len(prices),
        },
        index=dates,
    )

    monkeypatch.setattr(backtest_service, "load_backtest_dataframe", lambda *args, **kwargs: frame)

    result = backtest_service.run_backtest(
        sample_config,
        symbol="BTCUSD",
        start_date="2024-01-01",
        end_date="2024-01-02",
        timeframe="1m",
    )

    assert result["symbol"] == "BTCUSD"
    assert result["timeframe"] == "1m"
    assert result["candles"] == 60
    assert "final_balance" in result["report"]


def test_run_backtest_recent_returns_report(sample_config, monkeypatch):
    dates = pd.date_range("2026-03-24", periods=500, freq="1min")
    prices = [1000 + i for i in range(500)]
    frame = pd.DataFrame(
        {
            "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
            "open": prices,
            "high": [price + 5 for price in prices],
            "low": [price - 5 for price in prices],
            "close": prices,
            "volume": [1000] * len(prices),
        },
        index=dates,
    )

    monkeypatch.setattr(backtest_service, "_fetch_remote_recent_dataset", lambda *args, **kwargs: frame)

    result = backtest_service.run_backtest_recent(
        sample_config,
        symbol="BTCUSD",
        timeframe="1m",
        candles=500,
    )

    assert result["symbol"] == "BTCUSD"
    assert result["timeframe"] == "1m"
    assert result["candles"] == 500
    assert result["window"] == "latest_500_candles"
    assert "final_balance" in result["report"]


def test_run_backtest_recent_universe_returns_aggregate_report(sample_config, monkeypatch):
    dates = pd.date_range("2026-03-24", periods=500, freq="1min")
    frame = pd.DataFrame(
        {
            "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
            "open": [1000 + i for i in range(500)],
            "high": [1005 + i for i in range(500)],
            "low": [995 + i for i in range(500)],
            "close": [1000 + i for i in range(500)],
            "volume": [1000] * 500,
        },
        index=dates,
    )

    sample_config["symbols"] = ["BTCUSD", "ETHUSD"]
    monkeypatch.setattr(backtest_service, "_scanner_picked_symbols", lambda config: ["BTCUSD", "ETHUSD"])
    monkeypatch.setattr(backtest_service, "_create_exchange_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backtest_service, "_fetch_remote_recent_dataset_with_client", lambda *args, **kwargs: frame)

    result = backtest_service.run_backtest_recent_universe(
        sample_config,
        timeframe="1m",
        candles=500,
    )

    assert result["scope"] == "universe"
    assert result["successful_symbols"] == 2
    assert result["candles"] == 500
    assert result["symbol_source"] == "scanner_picks"
    assert result["report"]["total_trades"] >= 0
    assert len(result["top_symbols"]) <= 2


def test_run_backtest_recent_universe_uses_scanner_picks(sample_config, monkeypatch):
    dates = pd.date_range("2026-03-24", periods=500, freq="1min")
    frame = pd.DataFrame(
        {
            "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
            "open": [1000 + i for i in range(500)],
            "high": [1005 + i for i in range(500)],
            "low": [995 + i for i in range(500)],
            "close": [1000 + i for i in range(500)],
            "volume": [1000] * 500,
        },
        index=dates,
    )

    monkeypatch.setattr(backtest_service, "_scanner_picked_symbols", lambda config: ["SOLUSDT"])
    monkeypatch.setattr(backtest_service, "_create_exchange_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backtest_service, "_fetch_remote_recent_dataset_with_client", lambda *args, **kwargs: frame)

    result = backtest_service.run_backtest_recent_universe(
        sample_config,
        timeframe="1m",
        candles=500,
    )

    assert result["symbols"] == ["SOLUSDT"]
    assert result["successful_symbols"] == 1


def test_run_backtest_recent_rejects_invalid_candle_count(sample_config):
    with pytest.raises(backtest_service.BacktestServiceError):
        backtest_service.run_backtest_recent(
            sample_config,
            symbol="BTCUSD",
            timeframe="1m",
            candles=750,
        )


def test_format_backtest_summary_contains_key_metrics():
    summary = backtest_service.format_backtest_summary(
        {
            "symbol": "BTCUSD",
            "timeframe": "1m",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "candles": 500,
            "report": {
                "final_balance": 10500.0,
                "total_return": 5.0,
                "total_trades": 12,
                "win_rate": 58.33,
                "max_drawdown": -3.2,
                "sharpe_ratio": 1.42,
                "profit_factor": 1.8,
            },
        }
    )

    assert "Backtest Complete" in summary
    assert "BTCUSD" in summary
    assert "10,500.00" in summary


def test_format_backtest_summary_handles_scanner_universe():
    summary = backtest_service.format_backtest_summary(
        {
            "symbol": "SCANNER_UNIVERSE",
            "scope": "universe",
            "scope_label": "scanner universe",
            "timeframe": "1m",
            "start_date": "2026-03-24 00:00:00",
            "end_date": "2026-03-24 08:19:00",
            "candles": 500,
            "window": "latest_500_candles",
            "symbols": ["BTCUSD", "ETHUSD"],
            "successful_symbols": 2,
            "failed_symbols": [],
            "top_symbols": [
                {"symbol": "BTCUSD", "total_return": 5.0},
                {"symbol": "ETHUSD", "total_return": 2.5},
            ],
            "capital_model": "Each asset ran independently with the same starting balance.",
            "report": {
                "final_balance": 20500.0,
                "total_return": 2.5,
                "total_trades": 24,
                "win_rate": 54.17,
                "max_drawdown": -4.8,
                "sharpe_ratio": 1.11,
                "profit_factor": 1.5,
            },
        }
    )

    assert "scanner universe" in summary
    assert "Assets Tested" in summary
    assert "BTCUSD" in summary
