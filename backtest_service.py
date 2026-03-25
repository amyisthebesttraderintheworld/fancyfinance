from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Any, Optional

import pandas as pd

from backtester import Backtester
from common import get_logger, load_historical_data

logger = get_logger("BacktestService")
ALLOWED_REMOTE_CANDLE_COUNTS = {500, 1000}


class BacktestServiceError(Exception):
    pass


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise BacktestServiceError("Start and end dates are required.")

    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                return datetime.combine(parsed.date(), time(23, 59, 59))
            return parsed

        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise BacktestServiceError(
            f"Invalid date `{text}`. Use `YYYY-MM-DD` or ISO datetime format."
        ) from exc


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    raw = str(timeframe or "").strip().lower()
    if len(raw) < 2:
        raise BacktestServiceError(f"Unsupported timeframe `{timeframe}`.")

    unit = raw[-1]
    try:
        value = int(raw[:-1])
    except ValueError as exc:
        raise BacktestServiceError(f"Unsupported timeframe `{timeframe}`.") from exc

    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise BacktestServiceError(f"Unsupported timeframe `{timeframe}`.")


def _resolve_requested_range(
    config: dict,
    start_date: Optional[str],
    end_date: Optional[str],
    timeframe: Optional[str],
) -> tuple[str, str, str]:
    backtest_config = config.get("backtest", {})
    strategy_config = config.get("strategy", {})

    resolved_start = start_date or backtest_config.get("start_date")
    resolved_end = end_date or backtest_config.get("end_date")
    resolved_timeframe = timeframe or strategy_config.get("timeframe") or "1m"

    if not resolved_start or not resolved_end:
        raise BacktestServiceError("Backtest start and end dates are not configured.")

    start_dt = _parse_date(resolved_start)
    end_dt = _parse_date(resolved_end, end_of_day=True)
    if end_dt < start_dt:
        raise BacktestServiceError("End date must be on or after start date.")

    return resolved_start, resolved_end, resolved_timeframe


def _load_local_dataset(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    data_dir: str,
) -> pd.DataFrame:
    if not data_dir:
        return pd.DataFrame()
    return load_historical_data(symbol, timeframe, start_date, end_date, data_dir)


def _resolve_ccxt_symbol(client: Any, requested_symbol: str) -> str:
    if requested_symbol in client.markets:
        return requested_symbol

    normalized_requested = "".join(ch for ch in requested_symbol.upper() if ch.isalnum())
    for symbol, market in client.markets.items():
        market_id = str(market.get("id") or "").upper()
        normalized_symbol = "".join(ch for ch in symbol.upper() if ch.isalnum())
        if market_id == requested_symbol.upper() or normalized_symbol == normalized_requested:
            return symbol

    raise BacktestServiceError(
        f"Symbol `{requested_symbol}` is not available on the configured exchange."
    )


def _fetch_remote_dataset(
    config: dict,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    try:
        from exchange_manager import ExchangeManager
    except Exception as exc:
        raise BacktestServiceError(
            "Remote historical backtesting is unavailable because exchange support is not installed."
        ) from exc

    exchange_id = config.get("exchange", "phemex")
    exchange_config = config.get(exchange_id, {})
    market_type = exchange_config.get("market_type") or exchange_config.get("symbol_type") or "swap"
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date, end_of_day=True)
    timeframe_step = _timeframe_to_timedelta(timeframe)

    manager = ExchangeManager(
        exchange_id,
        api_key=exchange_config.get("api_key"),
        api_secret=exchange_config.get("api_secret"),
        options={"defaultType": market_type},
    )
    client = manager.client
    client.load_markets()
    exchange_symbol = _resolve_ccxt_symbol(client, symbol)

    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    step_ms = max(int(timeframe_step.total_seconds() * 1000), 60_000)
    rows: list[list[Any]] = []
    seen_timestamps: set[int] = set()
    limit = 1000

    while since_ms <= end_ms:
        batch = client.fetch_ohlcv(exchange_symbol, timeframe=timeframe, since=since_ms, limit=limit)
        if not batch:
            break

        added = 0
        for candle in batch:
            timestamp = int(candle[0])
            if timestamp in seen_timestamps:
                continue
            seen_timestamps.add(timestamp)
            rows.append(candle[:6])
            added += 1

        last_timestamp = int(batch[-1][0])
        next_since = max(last_timestamp + step_ms, since_ms + step_ms)
        if next_since <= since_ms or added == 0:
            break
        since_ms = next_since

        if len(batch) < limit:
            break

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="ms")
    frame.set_index("datetime", inplace=True)
    frame.sort_index(inplace=True)
    frame = frame[(frame.index >= pd.Timestamp(start_dt)) & (frame.index <= pd.Timestamp(end_dt))]
    return frame


def _fetch_remote_recent_dataset(
    config: dict,
    symbol: str,
    timeframe: str,
    candles: int,
) -> pd.DataFrame:
    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        raise BacktestServiceError(
            f"Phemex backtests are limited to {sorted(ALLOWED_REMOTE_CANDLE_COUNTS)} candles per run."
        )

    try:
        from exchange_manager import ExchangeManager
    except Exception as exc:
        raise BacktestServiceError(
            "Remote historical backtesting is unavailable because exchange support is not installed."
        ) from exc

    exchange_id = config.get("exchange", "phemex")
    exchange_config = config.get(exchange_id, {})
    market_type = exchange_config.get("market_type") or exchange_config.get("symbol_type") or "swap"

    manager = ExchangeManager(
        exchange_id,
        api_key=exchange_config.get("api_key"),
        api_secret=exchange_config.get("api_secret"),
        options={"defaultType": market_type},
    )
    client = manager.client
    client.load_markets()
    exchange_symbol = _resolve_ccxt_symbol(client, symbol)

    rows = client.fetch_ohlcv(exchange_symbol, timeframe=timeframe, limit=candles)
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="ms")
    frame.set_index("datetime", inplace=True)
    frame.sort_index(inplace=True)
    return frame


def load_backtest_dataframe(
    config: dict,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str,
) -> pd.DataFrame:
    data_dir = config.get("backtest", {}).get("data_dir", "")
    local_frame = _load_local_dataset(symbol, timeframe, start_date, end_date, data_dir)
    if not local_frame.empty:
        return local_frame

    logger.info(
        "Local backtest dataset unavailable for %s on %s between %s and %s. Falling back to remote fetch.",
        symbol,
        timeframe,
        start_date,
        end_date,
    )
    return _fetch_remote_dataset(config, symbol, timeframe, start_date, end_date)


def run_backtest(
    base_config: dict,
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> dict[str, Any]:
    config = deepcopy(base_config or {})
    resolved_start, resolved_end, resolved_timeframe = _resolve_requested_range(
        config,
        start_date,
        end_date,
        timeframe,
    )
    config.setdefault("strategy", {})
    config["strategy"]["timeframe"] = resolved_timeframe

    frame = load_backtest_dataframe(config, symbol, resolved_start, resolved_end, resolved_timeframe)
    if frame.empty:
        raise BacktestServiceError(
            f"No historical data is available for `{symbol}` on `{resolved_timeframe}` between `{resolved_start}` and `{resolved_end}`."
        )

    backtester = Backtester(config)
    backtester.run(symbol, frame)
    report = backtester.generate_report(plot_filename=None)

    return {
        "symbol": symbol,
        "timeframe": resolved_timeframe,
        "start_date": resolved_start,
        "end_date": resolved_end,
        "candles": int(len(frame)),
        "report": report,
    }


def run_backtest_recent(
    base_config: dict,
    symbol: str,
    timeframe: Optional[str] = None,
    candles: int = 500,
) -> dict[str, Any]:
    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        raise BacktestServiceError(
            f"Phemex backtests are limited to {sorted(ALLOWED_REMOTE_CANDLE_COUNTS)} candles per run."
        )

    config = deepcopy(base_config or {})
    resolved_timeframe = timeframe or config.get("strategy", {}).get("timeframe") or "1m"
    config.setdefault("strategy", {})
    config["strategy"]["timeframe"] = resolved_timeframe

    frame = _fetch_remote_recent_dataset(config, symbol, resolved_timeframe, candles)
    if frame.empty:
        raise BacktestServiceError(
            f"No historical data is available for `{symbol}` on `{resolved_timeframe}` using the latest `{candles}` candles."
        )

    backtester = Backtester(config)
    backtester.run(symbol, frame)
    report = backtester.generate_report(plot_filename=None)

    return {
        "symbol": symbol,
        "timeframe": resolved_timeframe,
        "start_date": frame.index.min().strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": frame.index.max().strftime("%Y-%m-%d %H:%M:%S"),
        "candles": int(len(frame)),
        "report": report,
        "window": f"latest_{candles}_candles",
    }


def format_backtest_summary(result: dict[str, Any]) -> str:
    report = result.get("report") or {}
    window = str(result.get("window") or "").strip()
    window_line = ""
    if window:
        window_line = f"*Window:* `{window.replace('_', ' ')}`\n"
    return (
        f"📈 *Backtest Complete*\n\n"
        f"*Symbol:* `{result.get('symbol')}`\n"
        f"*Timeframe:* `{result.get('timeframe')}`\n"
        f"{window_line}"
        f"*Range:* `{result.get('start_date')}` → `{result.get('end_date')}`\n"
        f"*Candles:* `{result.get('candles')}`\n\n"
        f"*Final Balance:* `${report.get('final_balance', 0):,.2f}`\n"
        f"*Total Return:* `{report.get('total_return', 0):.2f}%`\n"
        f"*Trades:* `{report.get('total_trades', 0)}`\n"
        f"*Win Rate:* `{report.get('win_rate', 0):.2f}%`\n"
        f"*Max Drawdown:* `{report.get('max_drawdown', 0):.2f}%`\n"
        f"*Sharpe Ratio:* `{report.get('sharpe_ratio', 0):.2f}`\n"
        f"*Profit Factor:* `{report.get('profit_factor', 0)}`"
    )
