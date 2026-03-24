"""
asset_scorer.py
---------------
Scores each asset on a 0–100 scale so the scanners can rank and
prioritise which symbols to trade when multiple setups fire at once.

Score breakdown (configurable weights via config.yaml → scoring):
  • Trend   (default 30 pts): MA spread strength in the signal direction
  • RSI     (default 25 pts): RSI proximity to oversold/overbought threshold
  • Volume  (default 25 pts): Current volume vs rolling average
  • Momentum(default 20 pts): Recent price impulse relative to ATR

Usage:
    scorer = AssetScorer(config)
    result = scorer.score(df, direction="long")   # df from scanner._calculate_indicators()
    print(result.total)           # 0–100
    print(result.breakdown)       # {'trend': 22.1, 'rsi': 18.3, ...}
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Literal

import pandas as pd

from common import get_logger

Direction = Literal["long", "short"]


@dataclass
class ScoreResult:
    symbol: str
    direction: Direction
    total: float                          # 0–100
    breakdown: Dict[str, float] = field(default_factory=dict)
    raw: Dict[str, float] = field(default_factory=dict)   # un-normalised values

    def __str__(self) -> str:
        parts = ", ".join(f"{k}={v:.1f}" for k, v in self.breakdown.items())
        return f"[{self.symbol}|{self.direction}] total={self.total:.1f}  ({parts})"


class AssetScorer:
    """
    Stateless scorer — call score() after indicators have been calculated.

    Config block expected in config.yaml:
        scoring:
          trend_weight:    30
          rsi_weight:      25
          volume_weight:   25
          momentum_weight: 20
          min_score:       45     # signals below this are suppressed
    """

    DEFAULTS = {
        "trend_weight":    30,
        "rsi_weight":      25,
        "volume_weight":   25,
        "momentum_weight": 20,
        "min_score":       45,
    }

    def __init__(self, config: dict):
        self.logger = get_logger("AssetScorer")
        cfg = config.get("scoring", {})
        self.w_trend    = float(cfg.get("trend_weight",    self.DEFAULTS["trend_weight"]))
        self.w_rsi      = float(cfg.get("rsi_weight",      self.DEFAULTS["rsi_weight"]))
        self.w_volume   = float(cfg.get("volume_weight",   self.DEFAULTS["volume_weight"]))
        self.w_momentum = float(cfg.get("momentum_weight", self.DEFAULTS["momentum_weight"]))
        self.min_score  = float(cfg.get("min_score",       self.DEFAULTS["min_score"]))

        total_weight = self.w_trend + self.w_rsi + self.w_volume + self.w_momentum
        if abs(total_weight - 100) > 0.01:
            self.logger.warning(
                f"Scoring weights sum to {total_weight}, not 100. "
                "Normalising automatically."
            )
            self.w_trend    = self.w_trend    / total_weight * 100
            self.w_rsi      = self.w_rsi      / total_weight * 100
            self.w_volume   = self.w_volume   / total_weight * 100
            self.w_momentum = self.w_momentum / total_weight * 100

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        df: pd.DataFrame,
        direction: Direction,
        symbol: str = "UNKNOWN",
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
    ) -> ScoreResult:
        """
        Score the *current* bar (df.iloc[-1]) for the given direction.

        Required columns in df (produced by scanner._calculate_indicators):
            fast_ma, slow_ma, rsi, atr, volume, avg_volume, close
        """
        if len(df) < 2:
            return ScoreResult(symbol=symbol, direction=direction, total=0.0)

        row = df.iloc[-1]

        trend_score    = self._score_trend(row, direction)
        rsi_score      = self._score_rsi(row, direction, rsi_oversold, rsi_overbought)
        volume_score   = self._score_volume(row)
        momentum_score = self._score_momentum(df, direction)

        total = (
            trend_score    * self.w_trend    / 100
            + rsi_score    * self.w_rsi      / 100
            + volume_score * self.w_volume   / 100
            + momentum_score * self.w_momentum / 100
        )
        total = round(min(max(total, 0.0), 100.0), 2)

        result = ScoreResult(
            symbol=symbol,
            direction=direction,
            total=total,
            breakdown={
                "trend":    round(trend_score    * self.w_trend    / 100, 2),
                "rsi":      round(rsi_score      * self.w_rsi      / 100, 2),
                "volume":   round(volume_score   * self.w_volume   / 100, 2),
                "momentum": round(momentum_score * self.w_momentum / 100, 2),
            },
            raw={
                "fast_ma":   float(row.get("fast_ma", 0)),
                "slow_ma":   float(row.get("slow_ma", 0)),
                "rsi":       float(row.get("rsi", 50)),
                "vol_ratio": float(row.get("volume", 0) / row.get("avg_volume", 1) if row.get("avg_volume", 0) > 0 else 1),
            },
        )
        self.logger.debug(str(result))
        return result

    def passes_min_score(self, result: ScoreResult) -> bool:
        return result.total >= self.min_score

    # ------------------------------------------------------------------
    # Sub-scores  (each returns 0–100 before weighting)
    # ------------------------------------------------------------------

    def _score_trend(self, row: pd.Series, direction: Direction) -> float:
        """
        Measures how strongly the MAs are aligned in the signal direction.

        MA spread %  → sigmoid-shaped mapping to 0–100.
        Spread of 0.5 % → ~50 pts, 2 % → ~90 pts.
        Wrong-direction spread → 0 pts.
        """
        slow = float(row.get("slow_ma", 0))
        fast = float(row.get("fast_ma", 0))
        if slow == 0:
            return 0.0

        spread_pct = (fast - slow) / slow * 100  # positive = fast above slow

        if direction == "long":
            if spread_pct <= 0:
                return 0.0
        else:  # short
            if spread_pct >= 0:
                return 0.0
            spread_pct = abs(spread_pct)

        # Sigmoid: score = 100 / (1 + e^(-k*(x - x0)))  centred at 0.5 %
        score = 100 / (1 + math.exp(-4 * (spread_pct - 0.5)))
        return min(score, 100.0)

    def _score_rsi(
        self,
        row: pd.Series,
        direction: Direction,
        rsi_oversold: float,
        rsi_overbought: float,
    ) -> float:
        """
        For longs:  RSI ≤ oversold → 100 pts; RSI at 50 → 0 pts.
        For shorts: RSI ≥ overbought → 100 pts; RSI at 50 → 0 pts.
        Linear interpolation between extremes.
        """
        rsi = float(row.get("rsi", 50))

        if direction == "long":
            if rsi >= 50:
                return 0.0
            # 0 at rsi=50, 100 at rsi=oversold (or below)
            score = (50 - rsi) / (50 - rsi_oversold) * 100
        else:
            if rsi <= 50:
                return 0.0
            score = (rsi - 50) / (rsi_overbought - 50) * 100

        return min(max(score, 0.0), 100.0)

    def _score_volume(self, row: pd.Series) -> float:
        """
        Volume relative to its 20-bar average.
        1x avg → 0 pts, 2x avg → ~67 pts, 3x avg → 100 pts (capped).
        """
        vol     = float(row.get("volume", 0))
        avg_vol = float(row.get("avg_volume", 0))
        if avg_vol <= 0:
            return 0.0

        ratio = vol / avg_vol
        if ratio <= 1.0:
            return 0.0

        # Linear: 0 at 1x, 100 at 3x
        score = (ratio - 1.0) / 2.0 * 100
        return min(score, 100.0)

    def _score_momentum(self, df: pd.DataFrame, direction: Direction) -> float:
        """
        Impulse = (close_now - close_3bars_ago) / ATR_now
        Measures how many ATR units price moved recently.
        1 ATR of movement in signal direction → ~63 pts.
        Negative momentum → 0 pts.
        """
        if len(df) < 4:
            return 0.0

        row     = df.iloc[-1]
        row_old = df.iloc[-4]   # 3 bars ago

        atr   = float(row.get("atr", 0))
        close_now  = float(row.get("close", 0))
        close_old  = float(row_old.get("close", 0))

        if atr <= 0 or close_old <= 0:
            return 0.0

        impulse = (close_now - close_old) / atr  # ATR multiples

        if direction == "short":
            impulse = -impulse   # invert for shorts

        if impulse <= 0:
            return 0.0

        # Exponential: score = 100 * (1 - e^(-k * impulse)), k=1
        score = 100 * (1 - math.exp(-impulse))
        return min(score, 100.0)
