from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


RSI_OVERSOLD_ZONE = 35.0
RSI_OVERBOUGHT_ZONE = 65.0
DIVERGENCE_WINDOW = 60
DIV_PRICE_THRESHOLD_SHORT = 1.005
DIV_PRICE_THRESHOLD_LONG = 0.995
DIV_RSI_THRESHOLD = 3.0
THREE_BLACK_CROWS_RSI_GATE = 45.0
THREE_WHITE_SOLDIERS_RSI_GATE = 55.0


@dataclass
class SetupSnapshot:
    symbol: str
    price: float
    rsi: Optional[float]
    prev_rsi: Optional[float]
    bb_pct: Optional[float]
    ema21: Optional[float]
    ema_slope: Optional[float]
    slope_change: Optional[float]
    change_window_pct: Optional[float]
    dist_low_pct: Optional[float]
    dist_high_pct: Optional[float]
    vol_spike: float
    has_div: bool
    patterns: List[Tuple[str, int, float]]
    atr: Optional[float]
    fast_ma: Optional[float]
    slow_ma: Optional[float]
    prev_fast_ma: Optional[float]
    prev_slow_ma: Optional[float]


def pct_change(current: Optional[float], reference: Optional[float]) -> Optional[float]:
    if current is None or reference in (None, 0):
        return None
    return ((float(current) - float(reference)) / float(reference)) * 100.0


def find_peaks(values: List[float], min_separation: int = 3) -> List[int]:
    peaks: List[int] = []
    if len(values) < 3:
        return peaks
    for idx in range(1, len(values) - 1):
        if values[idx] > values[idx - 1] and values[idx] > values[idx + 1]:
            if not peaks or idx - peaks[-1] >= min_separation:
                peaks.append(idx)
    return peaks


def find_troughs(values: List[float], min_separation: int = 3) -> List[int]:
    troughs: List[int] = []
    if len(values) < 3:
        return troughs
    for idx in range(1, len(values) - 1):
        if values[idx] < values[idx - 1] and values[idx] < values[idx + 1]:
            if not troughs or idx - troughs[-1] >= min_separation:
                troughs.append(idx)
    return troughs


def detect_bearish_divergence(closes: List[float], rsi_values: List[Optional[float]]) -> bool:
    if len(closes) < DIVERGENCE_WINDOW or len(rsi_values) < DIVERGENCE_WINDOW:
        return False

    price_window = np.asarray(closes[-DIVERGENCE_WINDOW:], dtype=float)
    rsi_window_list = rsi_values[-DIVERGENCE_WINDOW:]
    if any(value is None for value in rsi_window_list):
        return False

    rsi_window = np.asarray([float(value) for value in rsi_window_list], dtype=float)
    price_peaks = find_peaks(price_window.tolist())
    rsi_peaks = find_peaks(rsi_window.tolist())

    if len(price_peaks) < 2 or len(rsi_peaks) < 2:
        return False
    if abs(price_peaks[-1] - rsi_peaks[-1]) > 5 or abs(price_peaks[-2] - rsi_peaks[-2]) > 5:
        return False

    p1 = price_window[price_peaks[-2]]
    p2 = price_window[price_peaks[-1]]
    r1 = rsi_window[rsi_peaks[-2]]
    r2 = rsi_window[rsi_peaks[-1]]
    return (p2 > p1 * DIV_PRICE_THRESHOLD_SHORT) and (r2 < r1 - DIV_RSI_THRESHOLD) and (r2 > RSI_OVERBOUGHT_ZONE - 10)


def detect_bullish_divergence(closes: List[float], rsi_values: List[Optional[float]]) -> bool:
    if len(closes) < DIVERGENCE_WINDOW or len(rsi_values) < DIVERGENCE_WINDOW:
        return False

    price_window = np.asarray(closes[-DIVERGENCE_WINDOW:], dtype=float)
    rsi_window_list = rsi_values[-DIVERGENCE_WINDOW:]
    if any(value is None for value in rsi_window_list):
        return False

    rsi_window = np.asarray([float(value) for value in rsi_window_list], dtype=float)
    price_troughs = find_troughs(price_window.tolist())
    rsi_troughs = find_troughs(rsi_window.tolist())

    if len(price_troughs) < 2 or len(rsi_troughs) < 2:
        return False
    if abs(price_troughs[-1] - rsi_troughs[-1]) > 5 or abs(price_troughs[-2] - rsi_troughs[-2]) > 5:
        return False

    p1 = price_window[price_troughs[-2]]
    p2 = price_window[price_troughs[-1]]
    r1 = rsi_window[rsi_troughs[-2]]
    r2 = rsi_window[rsi_troughs[-1]]
    return (p2 < p1 * DIV_PRICE_THRESHOLD_LONG) and (r2 > r1 + DIV_RSI_THRESHOLD) and (r2 < RSI_OVERSOLD_ZONE + 10)


def detect_bearish_patterns(ohlc: List[Tuple[float, float, float, float]]) -> List[Tuple[str, int, float]]:
    patterns: List[Tuple[str, int, float]] = []
    if len(ohlc) < 3:
        return patterns

    def body(candle): return abs(candle[3] - candle[0])
    def upper_wick(candle): return candle[1] - max(candle[0], candle[3])
    def lower_wick(candle): return min(candle[0], candle[3]) - candle[2]
    def is_bear(candle): return candle[3] < candle[0]
    def is_bull(candle): return candle[3] > candle[0]

    c0, c1, c2 = ohlc[-3], ohlc[-2], ohlc[-1]

    if upper_wick(c2) > 2 * body(c2) and lower_wick(c2) < body(c2) * 0.4 and body(c2) > 0:
        patterns.append(("Shooting Star", 15, 1.0))
    if upper_wick(c2) > 2.5 * body(c2) and body(c2) < (c2[1] - c2[2]) * 0.2 and c2[1] > c1[1]:
        patterns.append(("Gravestone Doji", 14, 1.0))
    if is_bull(c1) and is_bear(c2) and c2[3] <= c1[0] and c2[0] >= c1[3] and body(c2) > body(c1):
        patterns.append(("Bearish Engulfing", 18, 1.0))
    if is_bull(c0) and body(c1) < body(c0) * 0.5 and is_bear(c2) and c2[3] < (c0[0] + c0[3]) / 2:
        patterns.append(("Evening Star", 20, 1.0))
    if is_bull(c1) and is_bear(c2) and c2[0] > c1[1] and c2[3] < (c1[0] + c1[3]) / 2 and c2[3] > c1[0]:
        patterns.append(("Dark Cloud Cover", 16, 1.0))
    if is_bull(c1) and is_bear(c2) and c2[0] < c1[3] and c2[3] > c1[0] and body(c2) < body(c1):
        patterns.append(("Bearish Harami", 12, 1.0))
    if body(c2) < (c2[1] - c2[2]) * 0.15 and c2[1] > c1[1]:
        patterns.append(("Doji at High", 10, 1.0))
    if is_bear(c0) and is_bear(c1) and is_bear(c2) and c1[3] < c0[3] and c2[3] < c1[3] and body(c0) > 0 and body(c1) > 0 and body(c2) > 0:
        patterns.append(("Three Black Crows", 18, 1.0))
    if is_bear(c2) and upper_wick(c2) < body(c2) * 0.1 and lower_wick(c2) < body(c2) * 0.1 and body(c2) > (c2[1] - c2[2]) * 0.85:
        patterns.append(("Bearish Marubozu", 14, 1.0))

    return patterns


def detect_bullish_patterns(ohlc: List[Tuple[float, float, float, float]]) -> List[Tuple[str, int, float]]:
    patterns: List[Tuple[str, int, float]] = []
    if len(ohlc) < 3:
        return patterns

    def body(candle): return abs(candle[3] - candle[0])
    def upper_wick(candle): return candle[1] - max(candle[0], candle[3])
    def lower_wick(candle): return min(candle[0], candle[3]) - candle[2]
    def is_bear(candle): return candle[3] < candle[0]
    def is_bull(candle): return candle[3] > candle[0]

    c0, c1, c2 = ohlc[-3], ohlc[-2], ohlc[-1]

    if lower_wick(c2) > 2 * body(c2) and upper_wick(c2) < body(c2) * 0.4 and body(c2) > 0:
        patterns.append(("Hammer", 15, 1.0))
    if lower_wick(c2) > 2.5 * body(c2) and body(c2) < (c2[1] - c2[2]) * 0.2 and c2[2] < c1[2]:
        patterns.append(("Dragonfly Doji", 14, 1.0))
    if is_bear(c1) and is_bull(c2) and c2[0] <= c1[3] and c2[3] >= c1[0] and body(c2) > body(c1):
        patterns.append(("Bullish Engulfing", 18, 1.0))
    if is_bear(c0) and body(c1) < body(c0) * 0.5 and is_bull(c2) and c2[3] > (c0[0] + c0[3]) / 2:
        patterns.append(("Morning Star", 20, 1.0))
    if is_bear(c1) and is_bull(c2) and c2[0] < c1[2] and c2[3] > (c1[0] + c1[3]) / 2 and c2[3] < c1[0]:
        patterns.append(("Piercing Line", 16, 1.0))
    if is_bear(c1) and is_bull(c2) and c2[0] > c1[3] and c2[3] < c1[0] and body(c2) < body(c1):
        patterns.append(("Bullish Harami", 12, 1.0))
    if body(c2) < (c2[1] - c2[2]) * 0.15 and c2[2] < c1[2]:
        patterns.append(("Doji at Low", 10, 1.0))
    if is_bull(c0) and is_bull(c1) and is_bull(c2) and c1[3] > c0[3] and c2[3] > c1[3] and body(c0) > 0 and body(c1) > 0 and body(c2) > 0:
        patterns.append(("Three White Soldiers", 18, 1.0))
    if is_bull(c2) and upper_wick(c2) < body(c2) * 0.1 and lower_wick(c2) < body(c2) * 0.1 and body(c2) > (c2[1] - c2[2]) * 0.85:
        patterns.append(("Bullish Marubozu", 14, 1.0))

    return patterns


def enrich_indicator_frame(
    df: pd.DataFrame,
    *,
    fast_period: int,
    slow_period: int,
    rsi_period: int,
    atr_period: int,
    bb_period: int,
    bb_std_dev: float,
    ema_period: int = 21,
) -> pd.DataFrame:
    frame = df.copy()
    frame["fast_ma"] = frame["close"].rolling(window=fast_period).mean()
    frame["slow_ma"] = frame["close"].rolling(window=slow_period).mean()

    delta = frame["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_period, adjust=False, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_period, adjust=False, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    frame["rsi"] = 100 - (100 / (1 + rs))

    frame["ema21"] = frame["close"].ewm(span=ema_period, adjust=False).mean()
    frame["ema_slope"] = frame["ema21"].diff()
    frame["slope_change"] = frame["ema_slope"].diff()

    frame["bb_middle"] = frame["close"].rolling(window=bb_period).mean()
    frame["bb_std"] = frame["close"].rolling(window=bb_period).std()
    frame["bb_upper"] = frame["bb_middle"] + (frame["bb_std"] * bb_std_dev)
    frame["bb_lower"] = frame["bb_middle"] - (frame["bb_std"] * bb_std_dev)

    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    frame["atr"] = true_range.rolling(window=atr_period).mean()

    frame["avg_volume"] = frame["volume"].rolling(window=20).mean()
    return frame


def build_snapshot(
    df: pd.DataFrame,
    *,
    direction: str,
    symbol: str,
    extreme_window: int = 96,
) -> SetupSnapshot:
    current = df.iloc[-1]
    previous = df.iloc[-2]
    closes = df["close"].tolist()
    rsi_values = df["rsi"].tolist()
    ohlc = list(zip(df["open"], df["high"], df["low"], df["close"]))

    bb_pct: Optional[float] = None
    if pd.notna(current.get("bb_upper")) and pd.notna(current.get("bb_lower")):
        bb_range = float(current["bb_upper"] - current["bb_lower"])
        if bb_range > 0:
            bb_pct = ((float(current["close"]) - float(current["bb_lower"])) / bb_range) * 100.0

    window = min(len(df), extreme_window)
    rolling_high = float(df["high"].tail(window).max()) if window else float(current["high"])
    rolling_low = float(df["low"].tail(window).min()) if window else float(current["low"])
    reference_close = float(df["close"].iloc[-window]) if window else float(current["close"])

    if direction == "long":
        raw_patterns = detect_bullish_patterns(ohlc)
        has_div = detect_bullish_divergence(closes, rsi_values)
        patterns = [
            (name, bonus, quality)
            for name, bonus, quality in raw_patterns
            if not (name == "Three White Soldiers" and pd.notna(current.get("rsi")) and float(current["rsi"]) > THREE_WHITE_SOLDIERS_RSI_GATE)
        ]
    else:
        raw_patterns = detect_bearish_patterns(ohlc)
        has_div = detect_bearish_divergence(closes, rsi_values)
        patterns = [
            (name, bonus, quality)
            for name, bonus, quality in raw_patterns
            if not (name == "Three Black Crows" and pd.notna(current.get("rsi")) and float(current["rsi"]) < THREE_BLACK_CROWS_RSI_GATE)
        ]

    volume_spike = 1.0
    avg_volume = current.get("avg_volume")
    if pd.notna(avg_volume) and float(avg_volume) > 0:
        volume_spike = float(current["volume"]) / float(avg_volume)

    return SetupSnapshot(
        symbol=symbol,
        price=float(current["close"]),
        rsi=float(current["rsi"]) if pd.notna(current.get("rsi")) else None,
        prev_rsi=float(previous["rsi"]) if pd.notna(previous.get("rsi")) else None,
        bb_pct=bb_pct,
        ema21=float(current["ema21"]) if pd.notna(current.get("ema21")) else None,
        ema_slope=float(current["ema_slope"]) if pd.notna(current.get("ema_slope")) else None,
        slope_change=float(current["slope_change"]) if pd.notna(current.get("slope_change")) else None,
        change_window_pct=pct_change(float(current["close"]), reference_close),
        dist_low_pct=abs(pct_change(float(current["close"]), rolling_low)) if rolling_low > 0 else None,
        dist_high_pct=abs(pct_change(float(current["close"]), rolling_high)) if rolling_high > 0 else None,
        vol_spike=volume_spike,
        has_div=has_div,
        patterns=patterns,
        atr=float(current["atr"]) if pd.notna(current.get("atr")) else None,
        fast_ma=float(current["fast_ma"]) if pd.notna(current.get("fast_ma")) else None,
        slow_ma=float(current["slow_ma"]) if pd.notna(current.get("slow_ma")) else None,
        prev_fast_ma=float(previous["fast_ma"]) if pd.notna(previous.get("fast_ma")) else None,
        prev_slow_ma=float(previous["slow_ma"]) if pd.notna(previous.get("slow_ma")) else None,
    )


def score_long(snapshot: SetupSnapshot) -> Tuple[int, List[str]]:
    score = 0
    signals: List[str] = []

    if snapshot.ema_slope is not None:
        if snapshot.ema_slope > 0:
            score += 12
            signals.append(f"Positive EMA slope ({snapshot.ema_slope:.3f})")
        elif snapshot.slope_change is not None and snapshot.slope_change > 0.01:
            score += 8
            signals.append(f"EMA curling up ({snapshot.slope_change:.3f})")
        elif snapshot.ema_slope < 0 and snapshot.slope_change is not None and snapshot.slope_change > 0.02:
            score += 5
            signals.append(f"EMA flattening up ({snapshot.slope_change:.3f})")

    if snapshot.has_div:
        score += 20
        signals.append("Bullish divergence")

    if snapshot.rsi is not None:
        recovering = snapshot.prev_rsi is not None and snapshot.rsi > snapshot.prev_rsi
        if snapshot.rsi < 25:
            score += 22
            signals.append(f"RSI {snapshot.rsi:.1f} deeply oversold")
        elif 25 <= snapshot.rsi <= 45:
            points = 25 + (8 if recovering else 0)
            score += points
            signals.append(f"RSI {snapshot.rsi:.1f} recovery zone")
        elif snapshot.rsi > 65:
            score -= 5
            signals.append(f"RSI {snapshot.rsi:.1f} overbought")

    if snapshot.bb_pct is not None:
        if snapshot.bb_pct <= 10:
            score += 30
            signals.append(f"At BB lower band ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct <= 25:
            score += 22
            signals.append(f"Near BB lower band ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct <= 45:
            score += 5
            signals.append(f"Below BB mid ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct > 55:
            score -= 5
            signals.append(f"Above BB mid ({snapshot.bb_pct:.0f}%)")

    if snapshot.ema21 is not None:
        pct_from_ema = pct_change(snapshot.price, snapshot.ema21)
        if pct_from_ema is not None:
            if pct_from_ema < -3:
                score += 15
                signals.append(f"{abs(pct_from_ema):.1f}% below EMA21")
                if snapshot.rsi is not None and snapshot.rsi < 35:
                    score += 5
                    signals.append("Stretch bonus")
            elif pct_from_ema < -1:
                score += 5
                signals.append(f"{abs(pct_from_ema):.1f}% below EMA21")
            elif pct_from_ema > 1:
                score -= 10
                signals.append(f"{pct_from_ema:.1f}% above EMA21")

    if snapshot.change_window_pct is not None:
        if snapshot.change_window_pct < -12:
            score += 20
            signals.append(f"{snapshot.change_window_pct:.1f}% capitulation")
        elif -12 <= snapshot.change_window_pct <= -5:
            score += 12
            signals.append(f"{snapshot.change_window_pct:.1f}% dip")
        elif -5 < snapshot.change_window_pct < -2:
            score += 5
            signals.append(f"{snapshot.change_window_pct:.1f}% pullback")
        elif 3 <= snapshot.change_window_pct <= 10:
            score += 12
            signals.append(f"+{snapshot.change_window_pct:.1f}% bullish momentum")

    if snapshot.dist_low_pct is not None:
        if snapshot.dist_low_pct < 1:
            score += 12
            signals.append(f"Near rolling low ({snapshot.dist_low_pct:.1f}%)")
        elif snapshot.dist_low_pct < 2:
            score += 6
            signals.append(f"Close to rolling low ({snapshot.dist_low_pct:.1f}%)")

    if snapshot.vol_spike > 2:
        score += 15
        signals.append(f"Volume spike ({snapshot.vol_spike:.1f}x)")
    elif snapshot.vol_spike > 1.4:
        score += 7
        signals.append(f"Elevated volume ({snapshot.vol_spike:.1f}x)")

    for name, bonus, quality in snapshot.patterns:
        weighted_bonus = int(bonus * quality)
        score += weighted_bonus
        signals.append(f"Pattern: {name} (+{weighted_bonus})")

    return int(round(score)), signals


def score_short(snapshot: SetupSnapshot) -> Tuple[int, List[str]]:
    score = 0
    signals: List[str] = []

    if snapshot.ema_slope is not None:
        if snapshot.ema_slope < 0:
            score += 12
            signals.append(f"Negative EMA slope ({snapshot.ema_slope:.3f})")
        elif snapshot.slope_change is not None and snapshot.slope_change < -0.01:
            score += 8
            signals.append(f"EMA curling down ({snapshot.slope_change:.3f})")
        elif snapshot.ema_slope > 0 and snapshot.slope_change is not None and snapshot.slope_change < -0.02:
            score += 5
            signals.append(f"EMA flattening down ({snapshot.slope_change:.3f})")

    if snapshot.has_div:
        score += 20
        signals.append("Bearish divergence")

    if snapshot.rsi is not None:
        rolling_over = snapshot.prev_rsi is not None and snapshot.rsi < snapshot.prev_rsi
        if snapshot.rsi > 75:
            score += 22
            signals.append(f"RSI {snapshot.rsi:.1f} deeply overbought")
        elif 55 <= snapshot.rsi <= 75:
            points = 25 + (8 if rolling_over else 0)
            score += points
            signals.append(f"RSI {snapshot.rsi:.1f} rollover zone")
        elif snapshot.rsi < 35:
            score -= 5
            signals.append(f"RSI {snapshot.rsi:.1f} oversold")

    if snapshot.bb_pct is not None:
        if snapshot.bb_pct >= 90:
            score += 30
            signals.append(f"At BB upper band ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct >= 75:
            score += 22
            signals.append(f"Near BB upper band ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct >= 55:
            score += 5
            signals.append(f"Above BB mid ({snapshot.bb_pct:.0f}%)")
        elif snapshot.bb_pct < 45:
            score -= 5
            signals.append(f"Below BB mid ({snapshot.bb_pct:.0f}%)")

    if snapshot.ema21 is not None:
        pct_from_ema = pct_change(snapshot.price, snapshot.ema21)
        if pct_from_ema is not None:
            if pct_from_ema > 3:
                score += 15
                signals.append(f"{pct_from_ema:.1f}% above EMA21")
                if snapshot.rsi is not None and snapshot.rsi > 65:
                    score += 5
                    signals.append("Stretch bonus")
            elif pct_from_ema > 1:
                score += 5
                signals.append(f"{pct_from_ema:.1f}% above EMA21")
            elif pct_from_ema < -1:
                score -= 10
                signals.append(f"{abs(pct_from_ema):.1f}% below EMA21")

    if snapshot.change_window_pct is not None:
        if snapshot.change_window_pct > 12:
            score += 20
            signals.append(f"+{snapshot.change_window_pct:.1f}% pump")
        elif 5 <= snapshot.change_window_pct <= 12:
            score += 12
            signals.append(f"+{snapshot.change_window_pct:.1f}% rally")
        elif 2 < snapshot.change_window_pct < 5:
            score += 5
            signals.append(f"+{snapshot.change_window_pct:.1f}% small rally")
        elif -10 <= snapshot.change_window_pct <= -3:
            score += 12
            signals.append(f"{snapshot.change_window_pct:.1f}% bearish momentum")

    if snapshot.dist_high_pct is not None:
        if snapshot.dist_high_pct < 1:
            score += 12
            signals.append(f"Near rolling high ({snapshot.dist_high_pct:.1f}%)")
        elif snapshot.dist_high_pct < 2:
            score += 6
            signals.append(f"Close to rolling high ({snapshot.dist_high_pct:.1f}%)")

    if snapshot.vol_spike > 2:
        score += 15
        signals.append(f"Volume spike ({snapshot.vol_spike:.1f}x)")
    elif snapshot.vol_spike > 1.4:
        score += 7
        signals.append(f"Elevated volume ({snapshot.vol_spike:.1f}x)")

    for name, bonus, quality in snapshot.patterns:
        weighted_bonus = int(bonus * quality)
        score += weighted_bonus
        signals.append(f"Pattern: {name} (+{weighted_bonus})")

    return int(round(score)), signals
