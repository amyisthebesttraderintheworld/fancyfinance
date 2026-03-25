from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from common import Candle, Signal, get_logger
from setup_scanner_core import (
    SetupSnapshot,
    build_snapshot,
    enrich_indicator_frame,
    score_long,
)


class LongScanner:
    def __init__(self, config):
        self.config = config
        self.logger = get_logger("LongScanner")
        self.strat_params = config["strategy"]
        self.risk_params = config["risk"]

        self.candles: List[Dict[str, Any]] = []
        self.has_position = False
        self.last_score: Dict[str, Any] | None = None

        self.fast_period = self.strat_params["fast_ma"]
        self.slow_period = self.strat_params["slow_ma"]
        self.rsi_period = self.strat_params["rsi_period"]
        self.atr_period = self.strat_params["atr_period"]
        self.bb_period = self.strat_params.get("bb_period", 20)
        self.bb_std_dev = self.strat_params.get("bb_std_dev", 2.0)
        self.min_setup_score = float(config.get("scoring", {}).get("min_score", 45))
        self.max_history = max(self.bb_period, self.slow_period, self.rsi_period, self.atr_period, 96) * 3

    def _frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.candles)
        return enrich_indicator_frame(
            df,
            fast_period=self.fast_period,
            slow_period=self.slow_period,
            rsi_period=self.rsi_period,
            atr_period=self.atr_period,
            bb_period=self.bb_period,
            bb_std_dev=self.bb_std_dev,
        )

    def _entry_trigger(self, snapshot: SetupSnapshot) -> bool:
        rsi_recovery = (
            snapshot.rsi is not None
            and snapshot.prev_rsi is not None
            and 25.0 <= snapshot.rsi <= 45.0
            and snapshot.rsi > snapshot.prev_rsi
        )
        lower_band_touch = snapshot.bb_pct is not None and snapshot.bb_pct <= 25.0
        ma_cross_up = (
            snapshot.prev_fast_ma is not None
            and snapshot.prev_slow_ma is not None
            and snapshot.fast_ma is not None
            and snapshot.slow_ma is not None
            and snapshot.prev_fast_ma <= snapshot.prev_slow_ma
            and snapshot.fast_ma > snapshot.slow_ma
        )
        ema_turning_up = (
            snapshot.ema_slope is not None and snapshot.ema_slope > 0
        ) or (
            snapshot.slope_change is not None and snapshot.slope_change > 0.01
        )
        return bool(snapshot.has_div or snapshot.patterns or rsi_recovery or lower_band_touch or ma_cross_up or ema_turning_up)

    def _exit_reason(self, snapshot: SetupSnapshot) -> str | None:
        ma_cross_down = (
            snapshot.prev_fast_ma is not None
            and snapshot.prev_slow_ma is not None
            and snapshot.fast_ma is not None
            and snapshot.slow_ma is not None
            and snapshot.prev_fast_ma >= snapshot.prev_slow_ma
            and snapshot.fast_ma < snapshot.slow_ma
        )
        if ma_cross_down:
            return "MA Cross Down"

        mean_reversion_complete = (
            snapshot.bb_pct is not None
            and snapshot.bb_pct >= 55.0
            and snapshot.rsi is not None
            and snapshot.rsi >= 55.0
        )
        if mean_reversion_complete:
            return "Mean Reversion Complete"

        return None

    def update(self, candle: Candle) -> Signal | None:
        self.candles.append(
            {
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "symbol": candle.symbol,
            }
        )

        if len(self.candles) > self.max_history:
            self.candles = self.candles[-self.max_history :]

        if len(self.candles) < max(self.slow_period, self.rsi_period, self.bb_period, 20):
            return None

        df = self._frame()
        current = df.iloc[-1]
        if any(pd.isna(current.get(field)) for field in ("rsi", "atr", "bb_upper", "bb_lower", "ema21")):
            return None

        symbol = candle.symbol or current.get("symbol") or "UNKNOWN"
        snapshot = build_snapshot(df, direction="long", symbol=symbol)
        score, signals = score_long(snapshot)
        self.last_score = {"total": score, "signals": signals, "direction": "long", "symbol": symbol}

        if not self.has_position:
            if score < self.min_setup_score:
                return None
            if not self._entry_trigger(snapshot):
                return None
            if snapshot.rsi is not None and snapshot.rsi > 65.0:
                return None

            self.has_position = True
            stop_loss_dist = float(current["atr"]) * self.risk_params["stop_loss_atr_mult"]
            take_profit_dist = float(current["atr"]) * self.risk_params["take_profit_atr_mult"]
            return Signal(
                timestamp=candle.timestamp,
                symbol=symbol,
                direction="long",
                entry_price=float(current["close"]),
                quantity=0,
                stop_loss=float(current["close"]) - stop_loss_dist,
                take_profit=float(current["close"]) + take_profit_dist,
                score=self.last_score,
            )

        exit_reason = self._exit_reason(snapshot)
        if exit_reason:
            self.has_position = False
            return Signal(
                timestamp=candle.timestamp,
                symbol=symbol,
                direction=None,
                entry_price=float(current["close"]),
                quantity=0,
                stop_loss=0,
                take_profit=0,
                exit_reason=exit_reason,
            )

        return None

    def reset(self):
        self.candles = []
        self.has_position = False
        self.last_score = None
