from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

from core import bot_core
from strategy_profile import normalize_strategy_profile


TIMEFRAME_TO_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1H": 3600,
    "2H": 7200,
    "4H": 14400,
    "6H": 21600,
    "12H": 43200,
    "1D": 86400,
}


@dataclass(frozen=True)
class FangScanSettings:
    direction: str
    timeframe: str
    interval_seconds: int
    candle_seconds: int
    min_score: int
    min_score_gap: int
    min_signals: int
    min_volume: int
    max_workers: int
    rate_limit_rps: float
    margin_usdt: float
    max_margin_usdt: float
    candles: int
    leverage: int
    stop_loss_pct: float
    take_profit_pct: float
    trail_pct: float
    max_hold_candles: int
    cooldown_candles: int
    csv: bool
    symbols: Optional[list[str]] = None


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_direction(value: Any) -> str:
    normalized = str(value or "BOTH").strip().upper()
    return normalized if normalized in {"LONG", "SHORT", "BOTH"} else "BOTH"


def _normalize_timeframe(value: Any) -> str:
    raw = str(value or "1m").strip()
    if raw.endswith(("h", "d")):
        return raw.upper()
    return raw


def _default_scan_interval_seconds(timeframe: str) -> int:
    candle_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)
    return max(60, min(candle_seconds, 300))


def build_trade_protection_from_settings(
    entry_price: float,
    total_qty: float,
    direction: str,
    settings: FangScanSettings,
    qty_rounder=None,
) -> dict[str, Any]:
    protection = bot_core.build_trade_protection(
        entry_price,
        total_qty,
        direction.upper(),
        qty_rounder=qty_rounder,
    )

    stop_loss_pct = settings.stop_loss_pct if settings.stop_loss_pct > 0 else settings.trail_pct
    if stop_loss_pct <= 0 and settings.trail_pct > 0:
        stop_loss_pct = settings.trail_pct

    if stop_loss_pct > 0:
        if direction.upper() == "LONG":
            stop_price = entry_price * (1.0 - stop_loss_pct)
        else:
            stop_price = entry_price * (1.0 + stop_loss_pct)
        protection["stop_price"] = float(stop_price)
        protection["original_stop"] = float(stop_price)

    if settings.take_profit_pct > 0:
        if direction.upper() == "LONG":
            tp1_px = entry_price * (1.0 + (settings.take_profit_pct * 0.5))
            tp2_px = entry_price * (1.0 + (settings.take_profit_pct * 0.75))
            tp3_px = entry_price * (1.0 + settings.take_profit_pct)
        else:
            tp1_px = entry_price * (1.0 - (settings.take_profit_pct * 0.5))
            tp2_px = entry_price * (1.0 - (settings.take_profit_pct * 0.75))
            tp3_px = entry_price * (1.0 - settings.take_profit_pct)
        protection["take_profit"] = float(tp3_px)
        stages = list(protection.get("tp_stages") or [])
        if len(stages) >= 3:
            stages[0]["price"] = float(tp1_px)
            stages[1]["price"] = float(tp2_px)
            stages[2]["price"] = float(tp3_px)
            protection["tp_stages"] = stages

    return protection


def resolve_scan_settings(config: dict[str, Any], overrides: Optional[dict[str, Any]] = None) -> FangScanSettings:
    exchange_id = str(config.get("exchange", "phemex")).lower()
    exchange_cfg = config.get(exchange_id, {})
    configured_symbols = config.get("symbols") or exchange_cfg.get("symbols") or []
    scan_all_symbols = bool(exchange_cfg.get("scan_all_symbols", False))
    profile = normalize_strategy_profile(config, overrides)

    timeframe = _normalize_timeframe(profile["timeframe"])
    candle_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)
    interval_seconds = _int_env("BOT_SCAN_INTERVAL", _default_scan_interval_seconds(timeframe))

    return FangScanSettings(
        direction=_normalize_direction(profile["direction"]),
        timeframe=timeframe,
        interval_seconds=max(15, interval_seconds),
        candle_seconds=candle_seconds,
        min_score=max(0, int(profile["min_score"])),
        min_score_gap=max(0, int(profile["min_score_gap"])),
        min_signals=max(1, int(profile["min_signals"])),
        min_volume=max(0, _int_env("BOT_MIN_VOLUME", 1_000_000)),
        max_workers=max(1, _int_env("BOT_MAX_WORKERS", 25)),
        rate_limit_rps=max(0.1, _float_env("BOT_RATE_LIMIT_RPS", 8.0)),
        margin_usdt=max(1.0, float(profile["margin"])),
        max_margin_usdt=max(float(profile["margin"]), float(profile["max_margin"])),
        candles=max(50, int(profile["candles"])),
        leverage=max(1, int(profile["leverage"])),
        stop_loss_pct=max(0.0, float(profile["stop_loss_pct"])),
        take_profit_pct=max(0.0, float(profile["take_profit_pct"])),
        trail_pct=max(0.0, float(profile["trail_pct"])),
        max_hold_candles=max(0, int(profile["max_hold"])),
        cooldown_candles=max(0, int(profile["cooldown"])),
        csv=bool(profile["csv"]),
        symbols=list(configured_symbols) if configured_symbols and not scan_all_symbols else None,
    )


def run_market_scan(
    settings: FangScanSettings,
    *,
    in_position: set[str],
    available_slots: int,
) -> list[tuple[dict[str, Any], str]]:
    if available_slots <= 0:
        return []

    cfg = {
        "MIN_VOLUME": settings.min_volume,
        "TIMEFRAME": settings.timeframe,
        "TOP_N": 50,
        "MIN_SCORE": 0,
        "MAX_WORKERS": settings.max_workers,
        "RATE_LIMIT_RPS": settings.rate_limit_rps,
        "CANDLES": settings.candles,
    }
    if settings.symbols:
        cfg["SYMBOLS"] = list(settings.symbols)

    args = SimpleNamespace(direction=settings.direction, no_ai=True, no_entity=True)
    long_results, short_results = bot_core.run_scanner_both(cfg, args, show_progress=False)
    candidates = bot_core.pick_candidates(
        long_results,
        short_results,
        min_score=settings.min_score,
        min_score_gap=settings.min_score_gap,
        direction_filter=settings.direction,
        in_position=in_position,
        available_slots=available_slots,
    )
    return [(result, direction) for result, direction in candidates if result.get("inst_id") not in in_position]


def build_entry_plan(
    result: dict[str, Any],
    direction: str,
    settings: FangScanSettings,
) -> Optional[dict[str, Any]]:
    try:
        price = float(result.get("price") or 0.0)
        score = int(result.get("score") or 0)
    except (TypeError, ValueError):
        return None

    if price <= 0.0:
        return None

    signals = list(result.get("signals") or [])
    signals_count = len(signals)
    if signals_count < settings.min_signals:
        return None

    leverage = max(1, int(settings.leverage or bot_core.get_score_leverage(score)))
    notional = settings.margin_usdt * leverage
    quantity = notional / price if price > 0 else 0.0
    if quantity <= 0.0:
        return None

    protection = build_trade_protection_from_settings(
        price,
        max(quantity, 1e-8),
        direction.upper(),
        settings,
    )
    return {
        "symbol": str(result.get("inst_id") or "").strip(),
        "direction": direction.lower(),
        "price": price,
        "quantity": quantity,
        "stop_loss": float(protection["stop_price"]),
        "take_profit": float(protection["take_profit"]),
        "score": score,
        "signals": signals,
        "signals_count": signals_count,
        "leverage": leverage,
        "margin_used": settings.margin_usdt,
        "trail_pct": settings.trail_pct,
        "max_hold_candles": settings.max_hold_candles,
    }
