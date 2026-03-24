import pandas as pd
import numpy as np

from asset_scorer import AssetScorer, ScoreResult
from common import Candle, Signal, get_logger

class LongScanner:
    def __init__(self, config):
        self.config = config
        self.logger = get_logger("LongScanner")
        self.strat_params = config['strategy']
        self.risk_params = config['risk']
        
        # History for indicator calculation
        self.candles = []
        self.has_position = False
        
        # Parameters
        self.fast_period = self.strat_params['fast_ma']
        self.slow_period = self.strat_params['slow_ma']
        self.rsi_period = self.strat_params['rsi_period']
        self.rsi_oversold = self.strat_params['rsi_oversold']
        self.atr_period = self.strat_params['atr_period']
        self.volume_mult = self.strat_params['volume_multiplier']
        self.macd_fast = self.strat_params.get('macd_fast', 12)
        self.macd_slow = self.strat_params.get('macd_slow', 26)
        self.macd_signal = self.strat_params.get('macd_signal', 9)
        self.bb_period = self.strat_params.get('bb_period', 20)
        self.bb_std_dev = self.strat_params.get('bb_std_dev', 2.0)
        self.squeeze_threshold = self.strat_params.get('squeeze_threshold', 0.05)
        self.use_macd_confirmation = self.strat_params.get('use_macd_confirmation', False)
        self.use_bollinger_squeeze = self.strat_params.get('use_bollinger_squeeze', False)

        self.scorer = AssetScorer(config)
        self.last_score: ScoreResult | None = None

    def _calculate_indicators(self, df: pd.DataFrame):
        df['fast_ma'] = df['close'].rolling(window=self.fast_period).mean()
        df['slow_ma'] = df['close'].rolling(window=self.slow_period).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['atr'] = true_range.rolling(window=self.atr_period).mean()
        
        # Avg Volume
        df['avg_volume'] = df['volume'].rolling(window=20).mean() # Hardcoded 20 for simplicity

        # MACD
        ema_fast = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd_line'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal, adjust=False).mean()
        df['macd_hist'] = df['macd_line'] - df['macd_signal']

        # Bollinger Band squeeze
        df['bb_middle'] = df['close'].rolling(window=self.bb_period).mean()
        df['bb_std'] = df['close'].rolling(window=self.bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * self.bb_std_dev)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * self.bb_std_dev)
        df['bb_bandwidth'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle'].replace(0, np.nan)
        df['bb_squeeze'] = df['bb_bandwidth'] <= self.squeeze_threshold
        
        return df

    def update(self, candle: Candle) -> Signal:
        # Convert candle to dict/dataframe format for pandas
        self.candles.append({
            'timestamp': candle.timestamp,
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume,
            'symbol': candle.symbol
        })
        
        # Maintain buffer size (keep enough for indicators)
        max_period = max(
            self.slow_period,
            self.rsi_period,
            self.atr_period,
            self.bb_period,
            self.macd_slow + self.macd_signal,
        ) * 3
        if len(self.candles) > max_period:
            self.candles = self.candles[-max_period:]
            
        if len(self.candles) < max(self.slow_period, self.rsi_period, self.bb_period):
            return None
            
        df = pd.DataFrame(self.candles)
        df = self._calculate_indicators(df)
        
        current = df.iloc[-1]
        previous = df.iloc[-2]
        symbol = candle.symbol or current.get('symbol') or "UNKNOWN"
        
        # Entry Logic
        if not self.has_position:
            # Fast MA crosses above Slow MA
            ma_cross = (previous['fast_ma'] <= previous['slow_ma']) and (current['fast_ma'] > current['slow_ma'])
            
            # RSI Condition
            rsi_condition = current['rsi'] < self.rsi_oversold
            
            # Volume Condition
            vol_condition = current['volume'] > (current['avg_volume'] * self.volume_mult)
            if not np.isfinite(vol_condition):
                vol_condition = True

            macd_condition = True
            if self.use_macd_confirmation:
                macd_condition = (
                    current['macd_line'] >= current['macd_signal']
                    and current['macd_hist'] >= previous['macd_hist']
                )

            squeeze_condition = True
            if self.use_bollinger_squeeze:
                squeeze_condition = (
                    bool(current['bb_squeeze']) or bool(previous['bb_squeeze'])
                ) and current['close'] >= current['bb_middle']
            
            if ma_cross and rsi_condition and macd_condition and squeeze_condition:
                # Score the setup before committing
                score = self.scorer.score(
                    df, direction="long",
                    symbol=symbol,
                    rsi_oversold=self.rsi_oversold,
                )
                self.last_score = score

                if not self.scorer.passes_min_score(score):
                    self.logger.info(
                        f"Long setup skipped — score too low: {score}"
                    )
                    return None

                self.has_position = True
                
                stop_loss_dist = current['atr'] * self.risk_params['stop_loss_atr_mult']
                take_profit_dist = current['atr'] * self.risk_params['take_profit_atr_mult']
                
                return Signal(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    direction='long',
                    entry_price=current['close'],
                    quantity=0, # Calculated by engine
                    stop_loss=current['close'] - stop_loss_dist,
                    take_profit=current['close'] + take_profit_dist,
                    score=score,
                )
        
        # Exit Logic
        else:
             # Fast MA crosses below Slow MA
            ma_cross_down = (previous['fast_ma'] >= previous['slow_ma']) and (current['fast_ma'] < current['slow_ma'])
            
            if ma_cross_down:
                self.has_position = False
                return Signal(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    direction=None, # Exit
                    entry_price=current['close'],
                    quantity=0,
                    stop_loss=0,
                    take_profit=0,
                    exit_reason="MA Cross Down"
                )
                
        return None

    def reset(self):
        self.candles = []
        self.has_position = False
