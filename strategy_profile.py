from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional


SUPPORTED_DIRECTIONS = {"LONG", "SHORT", "BOTH"}
SUPPORTED_TIMEFRAMES = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1H",
    "2H",
    "4H",
    "6H",
    "12H",
    "1D",
}
ALLOWED_BACKTEST_CANDLES = (500, 1000)

PROFILE_FIELD_ALIASES = {
    "timeframe": "timeframe",
    "candles": "candles",
    "min-score": "min_score",
    "min_score": "min_score",
    "min-signals": "min_signals",
    "min_signals": "min_signals",
    "leverage": "leverage",
    "margin": "margin",
    "max-margin": "max_margin",
    "max_margin": "max_margin",
    "stop-loss-pct": "stop_loss_pct",
    "stop_loss_pct": "stop_loss_pct",
    "take-profit-pct": "take_profit_pct",
    "take_profit_pct": "take_profit_pct",
    "trail-pct": "trail_pct",
    "trail_pct": "trail_pct",
    "max-hold": "max_hold",
    "max_hold": "max_hold",
    "direction": "direction",
    "min-score-gap": "min_score_gap",
    "min_score_gap": "min_score_gap",
    "cooldown": "cooldown",
    "csv": "csv",
    "symbol": "symbol",
}

PROFILE_FIELDS = (
    "timeframe",
    "candles",
    "min_score",
    "min_signals",
    "leverage",
    "margin",
    "max_margin",
    "stop_loss_pct",
    "take_profit_pct",
    "trail_pct",
    "max_hold",
    "direction",
    "min_score_gap",
    "cooldown",
    "csv",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def normalize_timeframe(value: Any) -> str:
    raw = str(value or "1m").strip()
    if not raw:
        return "1m"
    if raw.endswith(("h", "d")):
        raw = raw.upper()
    if raw not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe `{value}`.")
    return raw


def normalize_direction(value: Any) -> str:
    normalized = str(value or "BOTH").strip().upper()
    if normalized not in SUPPORTED_DIRECTIONS:
        raise ValueError(f"Unsupported direction `{value}`.")
    return normalized


def normalize_backtest_candles(value: Any, *, strict: bool = False) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise ValueError(
                f"Backtest candles must be one of `{list(ALLOWED_BACKTEST_CANDLES)}`."
            ) from exc
        return ALLOWED_BACKTEST_CANDLES[0]

    if resolved in ALLOWED_BACKTEST_CANDLES:
        return resolved
    if strict:
        raise ValueError(f"Backtest candles must be one of `{list(ALLOWED_BACKTEST_CANDLES)}`.")
    return min(ALLOWED_BACKTEST_CANDLES, key=lambda candidate: (abs(candidate - resolved), candidate))


def _apply_profile_overrides(base: Dict[str, Any], incoming: Dict[str, Any], *, strict_candles: bool = False) -> Dict[str, Any]:
    normalized = dict(base)
    aliased: Dict[str, Any] = {}
    for raw_key, value in (incoming or {}).items():
        if value is None:
            continue
        canonical = PROFILE_FIELD_ALIASES.get(str(raw_key or "").strip(), str(raw_key or "").strip())
        if canonical in PROFILE_FIELDS or canonical == "symbol":
            aliased[canonical] = value

    if "timeframe" in aliased:
        normalized["timeframe"] = normalize_timeframe(aliased["timeframe"])
    if "candles" in aliased:
        normalized["candles"] = normalize_backtest_candles(aliased["candles"], strict=strict_candles)
    if "min_score" in aliased:
        normalized["min_score"] = max(0, int(aliased["min_score"]))
    if "min_signals" in aliased:
        normalized["min_signals"] = max(1, int(aliased["min_signals"]))
    if "leverage" in aliased:
        normalized["leverage"] = max(1, min(int(aliased["leverage"]), 100))
    if "margin" in aliased:
        normalized["margin"] = max(1.0, float(aliased["margin"]))
    if "max_margin" in aliased:
        normalized["max_margin"] = max(normalized["margin"], float(aliased["max_margin"]))
    else:
        normalized["max_margin"] = max(normalized["margin"], float(normalized["max_margin"]))
    if "stop_loss_pct" in aliased:
        normalized["stop_loss_pct"] = max(0.0, float(aliased["stop_loss_pct"]))
    if "take_profit_pct" in aliased:
        normalized["take_profit_pct"] = max(0.0, float(aliased["take_profit_pct"]))
    if "trail_pct" in aliased:
        normalized["trail_pct"] = max(0.0, float(aliased["trail_pct"]))
    if "max_hold" in aliased:
        normalized["max_hold"] = max(0, int(aliased["max_hold"]))
    if "direction" in aliased:
        normalized["direction"] = normalize_direction(aliased["direction"])
    if "min_score_gap" in aliased:
        normalized["min_score_gap"] = max(0, int(aliased["min_score_gap"]))
    if "cooldown" in aliased:
        normalized["cooldown"] = max(0, int(aliased["cooldown"]))
    if "csv" in aliased:
        normalized["csv"] = _to_bool(aliased["csv"])

    return normalized


def default_strategy_profile(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source = config or {}
    base_timeframe = normalize_timeframe(source.get("strategy", {}).get("timeframe", os.getenv("BOT_TIMEFRAME", "1m")))
    base_margin = max(1.0, _env_float("BOT_MARGIN_USDT", 10.0))
    max_positions = max(int(source.get("risk", {}).get("max_positions", 3) or 3), 1)
    trail_pct = max(0.0, _env_float("BOT_TRAIL_PCT", 0.006))
    stop_loss_pct = max(0.0, _env_float("BOT_STOP_LOSS_PCT", trail_pct))

    profile = {
        "timeframe": base_timeframe,
        "candles": normalize_backtest_candles(_env_int("BOT_CANDLES", ALLOWED_BACKTEST_CANDLES[0])),
        "min_score": max(0, _env_int("BOT_MIN_SCORE", 125)),
        "min_signals": max(1, int(source.get("scoring", {}).get("min_signals", 1) or 1)),
        "leverage": max(1, _env_int("BOT_LEVERAGE", 30)),
        "margin": base_margin,
        "max_margin": max(base_margin, _env_float("BOT_MAX_MARGIN_USDT", base_margin * max_positions)),
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": max(0.0, _env_float("BOT_TAKE_PROFIT_PCT", 0.04)),
        "trail_pct": trail_pct,
        "max_hold": max(0, _env_int("BOT_MAX_HOLD", 0)),
        "direction": normalize_direction(os.getenv("BOT_DIRECTION", "BOTH")),
        "min_score_gap": max(0, _env_int("BOT_MIN_SCORE_GAP", 30)),
        "cooldown": max(0, _env_int("BOT_COOLDOWN", 0)),
        "csv": False,
    }
    configured_profile = source.get("strategy_profile") or {}
    if isinstance(configured_profile, dict) and configured_profile:
        return _apply_profile_overrides(profile, configured_profile)
    return profile


def strategy_profile_from_record(config: Optional[Dict[str, Any]], record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return normalize_strategy_profile(config, record or {})


def normalize_strategy_profile(
    config: Optional[Dict[str, Any]],
    overrides: Optional[Dict[str, Any]] = None,
    current: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = default_strategy_profile(config)
    if current and isinstance(current, dict):
        normalized = _apply_profile_overrides(normalized, current)

    incoming = overrides or {}
    if not isinstance(incoming, dict):
        raise ValueError("Strategy overrides must be an object.")
    return _apply_profile_overrides(normalized, incoming, strict_candles=True)


def strategy_profile_summary(profile: Dict[str, Any]) -> str:
    safe = normalize_strategy_profile({}, {}, current=profile)
    return (
        "Strategy config saved:\n"
        f"Timeframe: {safe['timeframe']}\n"
        f"Candles: {safe['candles']}\n"
        f"Min score/signals: {safe['min_score']} / {safe['min_signals']}\n"
        f"Margin/leverage: ${safe['margin']:.2f} @ {safe['leverage']}x\n"
        f"Max margin: ${safe['max_margin']:.2f}\n"
        f"SL/TP/Trail: {safe['stop_loss_pct']:.4f} / {safe['take_profit_pct']:.4f} / {safe['trail_pct']:.4f}\n"
        f"Direction: {safe['direction']}\n"
        f"Score gap: {safe['min_score_gap']}\n"
        f"Cooldown: {safe['cooldown']} candle(s)\n"
        f"Max hold: {safe['max_hold']} candle(s)\n"
        f"CSV output: {'on' if safe['csv'] else 'off'}"
    )


def parse_flag_args(args: Iterable[str]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    items = list(args or [])
    index = 0
    while index < len(items):
        item = str(items[index] or "").strip()
        if not item:
            index += 1
            continue
        if not item.startswith("--"):
            if "symbol" in parsed:
                raise ValueError(f"Unexpected token `{item}`.")
            parsed["symbol"] = item.upper()
            index += 1
            continue

        key = PROFILE_FIELD_ALIASES.get(item[2:], item[2:])
        if key == "csv":
            parsed["csv"] = True
            index += 1
            continue

        if index + 1 >= len(items):
            raise ValueError(f"Missing value for `{item}`.")
        parsed[key] = items[index + 1]
        index += 2

    return parsed


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
