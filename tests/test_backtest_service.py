import pandas as pd

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
