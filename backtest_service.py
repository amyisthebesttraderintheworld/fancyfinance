from __future__ import annotations

import csv
import io
import time as time_module
from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Any, Optional

import pandas as pd

from backtester import Backtester
from common import get_logger, load_historical_data
from strategy_profile import ALLOWED_BACKTEST_CANDLES, normalize_strategy_profile

logger = get_logger("BacktestService")
ALLOWED_REMOTE_CANDLE_COUNTS = set(ALLOWED_BACKTEST_CANDLES)
RECENT_FETCH_RETRY_DELAYS_SECONDS = (0.75, 1.5, 3.0)


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


def _configured_symbols(config: dict) -> list[str]:
    exchange_id = config.get("exchange", "phemex")
    exchange_symbols = ((config.get(exchange_id) or {}).get("symbols") or [])
    configured = config.get("symbols") or exchange_symbols
    seen: set[str] = set()
    symbols: list[str] = []

    for raw_symbol in configured:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)

    return symbols


def _scanner_picked_symbols(config: dict) -> list[str]:
    try:
        from fang_engine_runtime import resolve_scan_settings, run_market_scan
    except Exception as exc:
        logger.warning("Scanner runtime unavailable for universe backtesting: %s", exc)
        return _configured_symbols(config)

    settings = resolve_scan_settings(config)
    available_slots = max(len(_configured_symbols(config)), 50)

    try:
        candidates = run_market_scan(
            settings,
            in_position=set(),
            available_slots=available_slots,
        )
    except Exception as exc:
        logger.warning("Scanner-driven universe selection failed: %s", exc)
        return _configured_symbols(config)

    symbols: list[str] = []
    seen: set[str] = set()
    for result, _direction in candidates:
        symbol = str((result or {}).get("inst_id") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)

    return symbols


def _create_exchange_client(config: dict):
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
    return client


def _fetch_remote_dataset(
    config: dict,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date, end_of_day=True)
    timeframe_step = _timeframe_to_timedelta(timeframe)

    client = _create_exchange_client(config)
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


def _fetch_remote_recent_dataset_with_client(
    client: Any,
    symbol: str,
    timeframe: str,
    candles: int,
) -> pd.DataFrame:
    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        raise BacktestServiceError(
            f"Phemex backtests are limited to {sorted(ALLOWED_REMOTE_CANDLE_COUNTS)} candles per run."
        )
    exchange_symbol = _resolve_ccxt_symbol(client, symbol)

    last_error: Optional[Exception] = None
    rows: list[list[Any]] = []
    for attempt, delay_seconds in enumerate((0.0, *RECENT_FETCH_RETRY_DELAYS_SECONDS), start=1):
        if delay_seconds > 0:
            time_module.sleep(delay_seconds)
        try:
            rows = client.fetch_ohlcv(exchange_symbol, timeframe=timeframe, limit=candles)
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if "too many requests" not in str(exc).lower() and "39995" not in str(exc):
                raise
            logger.warning(
                "Rate-limited fetching recent candles for {} on {} (attempt {}/{}). Retrying...",
                symbol,
                timeframe,
                attempt,
                len(RECENT_FETCH_RETRY_DELAYS_SECONDS) + 1,
            )
    if last_error is not None:
        raise BacktestServiceError(
            f"Phemex rate-limited `{symbol}` on `{timeframe}` while fetching `{candles}` candles. Please try again in a moment."
        ) from last_error
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="ms")
    frame.set_index("datetime", inplace=True)
    frame.sort_index(inplace=True)
    return frame


def _fetch_remote_recent_dataset(
    config: dict,
    symbol: str,
    timeframe: str,
    candles: int,
) -> pd.DataFrame:
    client = _create_exchange_client(config)
    return _fetch_remote_recent_dataset_with_client(client, symbol, timeframe, candles)


def _run_backtester(config: dict, symbol: str, timeframe: str, frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        raise BacktestServiceError(f"No historical data is available for `{symbol}` on `{timeframe}`.")

    backtester = Backtester(config)
    backtester.run(symbol, frame)
    report = backtester.generate_report(plot_filename=None)
    trade_pnls = [float(trade.pnl) for trade in backtester.trades if getattr(trade, "pnl", None) is not None]
    wins = sum(1 for pnl in trade_pnls if pnl > 0)
    losses = sum(1 for pnl in trade_pnls if pnl <= 0)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": frame.index.min().strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": frame.index.max().strftime("%Y-%m-%d %H:%M:%S"),
        "candles": int(len(frame)),
        "report": report,
        "wins": wins,
        "losses": losses,
        "trade_pnls": trade_pnls,
        "trades": [dict(trade.__dict__) for trade in backtester.trades],
    }


def _apply_strategy_profile(config: dict, strategy_profile: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    normalized = normalize_strategy_profile(config, strategy_profile or {}, current=config.get("strategy_profile") or {})
    config["strategy_profile"] = normalized
    config.setdefault("strategy", {})
    config["strategy"]["timeframe"] = normalized["timeframe"]
    return normalized


def _trades_to_csv(trades: list[dict[str, Any]]) -> str:
    if not trades:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(trades[0].keys()))
    writer.writeheader()
    writer.writerows(trades)
    return output.getvalue()


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
    strategy_profile: Optional[dict[str, Any]] = None,
    csv_output: bool = False,
) -> dict[str, Any]:
    config = deepcopy(base_config or {})
    normalized_profile = _apply_strategy_profile(config, strategy_profile)
    resolved_start, resolved_end, resolved_timeframe = _resolve_requested_range(
        config,
        start_date,
        end_date,
        timeframe,
    )
    config["strategy"]["timeframe"] = resolved_timeframe

    frame = load_backtest_dataframe(config, symbol, resolved_start, resolved_end, resolved_timeframe)
    if frame.empty:
        raise BacktestServiceError(
            f"No historical data is available for `{symbol}` on `{resolved_timeframe}` between `{resolved_start}` and `{resolved_end}`."
        )

    result = _run_backtester(config, symbol, resolved_timeframe, frame)

    payload = {
        "symbol": symbol,
        "timeframe": resolved_timeframe,
        "start_date": resolved_start,
        "end_date": resolved_end,
        "candles": int(len(frame)),
        "report": result["report"],
        "strategy_profile": normalized_profile,
    }
    if csv_output:
        payload["csv"] = _trades_to_csv(result.get("trades") or [])
    return payload


def run_backtest_recent(
    base_config: dict,
    symbol: str,
    timeframe: Optional[str] = None,
    candles: int = 500,
    strategy_profile: Optional[dict[str, Any]] = None,
    csv_output: bool = False,
) -> dict[str, Any]:
    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        raise BacktestServiceError(
            f"Phemex backtests are limited to {sorted(ALLOWED_REMOTE_CANDLE_COUNTS)} candles per run."
        )

    config = deepcopy(base_config or {})
    normalized_profile = _apply_strategy_profile(config, strategy_profile)
    resolved_timeframe = timeframe or config.get("strategy", {}).get("timeframe") or "1m"
    config["strategy"]["timeframe"] = resolved_timeframe

    frame = _fetch_remote_recent_dataset(config, symbol, resolved_timeframe, candles)
    if frame.empty:
        raise BacktestServiceError(
            f"No historical data is available for `{symbol}` on `{resolved_timeframe}` using the latest `{candles}` candles."
        )

    result = _run_backtester(config, symbol, resolved_timeframe, frame)

    payload = {
        "symbol": symbol,
        "timeframe": resolved_timeframe,
        "start_date": result["start_date"],
        "end_date": result["end_date"],
        "candles": result["candles"],
        "report": result["report"],
        "window": f"latest_{candles}_candles",
        "strategy_profile": normalized_profile,
    }
    if csv_output:
        payload["csv"] = _trades_to_csv(result.get("trades") or [])
    return payload


def run_backtest_recent_universe(
    base_config: dict,
    timeframe: Optional[str] = None,
    candles: int = 500,
    strategy_profile: Optional[dict[str, Any]] = None,
    csv_output: bool = False,
) -> dict[str, Any]:
    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        raise BacktestServiceError(
            f"Phemex backtests are limited to {sorted(ALLOWED_REMOTE_CANDLE_COUNTS)} candles per run."
        )

    config = deepcopy(base_config or {})
    normalized_profile = _apply_strategy_profile(config, strategy_profile)
    symbols = _scanner_picked_symbols(config)
    symbol_source = "scanner_picks"
    scope_label = "scanner universe"
    if not symbols:
        symbols = _configured_symbols(config)
        if not symbols:
            raise BacktestServiceError("The scanner did not pick any assets for a universe backtest right now.")
        symbol_source = "configured_fallback"
        scope_label = "configured fallback universe"
        logger.info(
            "Scanner returned no assets for a universe backtest. Falling back to configured symbols: {}",
            symbols,
        )

    resolved_timeframe = timeframe or config.get("strategy", {}).get("timeframe") or "1m"
    config["strategy"]["timeframe"] = resolved_timeframe

    client = _create_exchange_client(config)
    per_symbol: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for symbol in symbols:
        try:
            frame = _fetch_remote_recent_dataset_with_client(client, symbol, resolved_timeframe, candles)
            if frame.empty:
                raise BacktestServiceError(
                    f"No historical data is available for `{symbol}` on `{resolved_timeframe}` using the latest `{candles}` candles."
                )
            per_symbol.append(_run_backtester(config, symbol, resolved_timeframe, frame))
        except Exception as exc:
            logger.warning("Skipping recent universe backtest for {}: {}", symbol, exc)
            failures.append({"symbol": symbol, "reason": str(exc)})

    if not per_symbol:
        raise BacktestServiceError("No scanner symbols returned enough Phemex data for a backtest run.")

    initial_balance = float(config.get("backtest", {}).get("initial_balance") or 0.0)
    aggregate_initial_balance = initial_balance * len(per_symbol)
    aggregate_final_balance = sum(float(item["report"].get("final_balance", initial_balance)) for item in per_symbol)
    aggregate_total_return = (
        ((aggregate_final_balance - aggregate_initial_balance) / aggregate_initial_balance) * 100.0
        if aggregate_initial_balance
        else 0.0
    )

    total_trade_count = sum(int(item["report"].get("total_trades", 0) or 0) for item in per_symbol)
    total_wins = sum(int(item.get("wins", 0) or 0) for item in per_symbol)
    total_losses = sum(int(item.get("losses", 0) or 0) for item in per_symbol)
    trade_pnls = [pnl for item in per_symbol for pnl in item.get("trade_pnls", [])]
    gross_profit = sum(pnl for pnl in trade_pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in trade_pnls if pnl < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    max_drawdown = min(float(item["report"].get("max_drawdown", 0) or 0) for item in per_symbol)
    average_sharpe = sum(float(item["report"].get("sharpe_ratio", 0) or 0) for item in per_symbol) / len(per_symbol)
    start_date = min(item["start_date"] for item in per_symbol)
    end_date = max(item["end_date"] for item in per_symbol)

    top_symbols = sorted(
        [
            {
                "symbol": item["symbol"],
                "final_balance": float(item["report"].get("final_balance", initial_balance)),
                "total_return": float(item["report"].get("total_return", 0) or 0),
                "total_trades": int(item["report"].get("total_trades", 0) or 0),
                "win_rate": float(item["report"].get("win_rate", 0) or 0),
            }
            for item in per_symbol
        ],
        key=lambda entry: entry["total_return"],
        reverse=True,
    )

    payload = {
        "symbol": "SCANNER_UNIVERSE",
        "scope": "universe",
        "scope_label": scope_label,
        "symbol_source": symbol_source,
        "timeframe": resolved_timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "candles": candles,
        "window": f"latest_{candles}_candles",
        "report": {
            "final_balance": round(aggregate_final_balance, 2),
            "total_return": round(aggregate_total_return, 2),
            "total_trades": int(total_trade_count),
            "win_rate": round((total_wins / total_trade_count) * 100, 2) if total_trade_count else 0.0,
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(average_sharpe, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
        },
        "symbols": symbols,
        "successful_symbols": len(per_symbol),
        "failed_symbols": failures,
        "top_symbols": top_symbols[:5],
        "capital_model": "Each asset ran independently with the same starting balance.",
        "wins": total_wins,
        "losses": total_losses,
        "strategy_profile": normalized_profile,
    }
    if csv_output:
        flattened = []
        for item in per_symbol:
            for trade in item.get("trades", []) or []:
                flattened.append({"symbol": item["symbol"], **trade})
        payload["csv"] = _trades_to_csv(flattened)
    return payload


def format_backtest_summary(result: dict[str, Any]) -> str:
    report = result.get("report") or {}
    window = str(result.get("window") or "").strip()
    window_line = ""
    if window:
        window_line = f"*Window:* `{window.replace('_', ' ')}`\n"
    if result.get("scope") == "universe":
        top_symbols = result.get("top_symbols") or []
        top_line = ""
        if top_symbols:
            top_line = "*Top Symbols:* " + ", ".join(
                f"`{item['symbol']}` ({item['total_return']:.2f}%)" for item in top_symbols[:3]
            ) + "\n"
        failed_symbols = result.get("failed_symbols") or []
        failed_line = ""
        if failed_symbols:
            failed_line = f"*Skipped:* `{len(failed_symbols)}` symbol(s)\n"
        return (
            f"📈 *Backtest Complete*\n\n"
            f"*Scope:* `{result.get('scope_label', 'scanner universe')}`\n"
            f"*Assets Tested:* `{result.get('successful_symbols', 0)}` / `{len(result.get('symbols') or [])}`\n"
            f"*Timeframe:* `{result.get('timeframe')}`\n"
            f"{window_line}"
            f"*Range:* `{result.get('start_date')}` → `{result.get('end_date')}`\n"
            f"*Candles per Asset:* `{result.get('candles')}`\n"
            f"*Capital Model:* {result.get('capital_model')}\n\n"
            f"*Aggregate Final Balance:* `${report.get('final_balance', 0):,.2f}`\n"
            f"*Aggregate Return:* `{report.get('total_return', 0):.2f}%`\n"
            f"*Trades:* `{report.get('total_trades', 0)}`\n"
            f"*Win Rate:* `{report.get('win_rate', 0):.2f}%`\n"
            f"*Worst Max Drawdown:* `{report.get('max_drawdown', 0):.2f}%`\n"
            f"*Average Sharpe Ratio:* `{report.get('sharpe_ratio', 0):.2f}`\n"
            f"*Profit Factor:* `{report.get('profit_factor', 0)}`\n"
            f"{top_line}"
            f"{failed_line}"
        )
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
