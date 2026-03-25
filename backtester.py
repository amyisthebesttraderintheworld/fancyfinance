import numpy as np
import pandas as pd

from common import Candle, Position, Trade, apply_slippage, calculate_fee, get_logger
from fang_engine_runtime import build_trade_protection_from_settings, resolve_scan_settings
from scanner_long import LongScanner
from scanner_short import ShortScanner

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - plotting is optional in tests/headless runs
    plt = None

class Backtester:
    def __init__(self, config):
        self.config = config
        self.logger = get_logger("Backtester")
        self.initial_balance = config['backtest']['initial_balance']
        self.balance = self.initial_balance
        self.fee_rate = config['backtest']['fee_rate']
        self.slippage = config['backtest']['slippage']
        self.risk_per_trade = config['risk']['risk_per_trade']
        
        self.long_scanner = LongScanner(config)
        self.short_scanner = ShortScanner(config)
        
        self.positions: dict[str, Position] = {} # symbol -> Position
        self.trades: list[Trade] = []
        self.equity_curve = []
        self.last_report = None
        self.scan_settings = resolve_scan_settings(config)
        self._cooldown_until_candle: dict[str, int] = {}

    def _periods_per_year(self) -> int:
        timeframe = self.config.get('strategy', {}).get('timeframe', '1m')
        unit = timeframe[-1]
        value = int(timeframe[:-1] or 1)
        minutes_map = {'m': value, 'h': value * 60, 'd': value * 1440}
        minutes = minutes_map.get(unit, 1)
        return max(int((365 * 24 * 60) / minutes), 1)

    def run(self, symbol: str, df: pd.DataFrame):
        self.logger.info(f"Starting backtest for {symbol} with {len(df)} candles.")
        self.long_scanner.reset()
        self.short_scanner.reset()
        self.positions = {}
        self.trades = []
        self.balance = self.initial_balance
        self.equity_curve = []
        
        self.scan_settings = resolve_scan_settings(self.config)
        self._cooldown_until_candle = {}

        for candle_index, (index, row) in enumerate(df.iterrows()):
            timestamp = int(index.timestamp() * 1000)
            candle = Candle(
                timestamp=timestamp,
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row['volume']
            )
            
            # Update Scanners
            long_signal = self.long_scanner.update(candle)
            short_signal = self.short_scanner.update(candle)
            
            # Check Stop Loss / Take Profit for existing position
            if symbol in self.positions:
                pos = self.positions[symbol]
                exit_price = None
                reason = None

                if pos.direction == 'long':
                    pos.high_water = max(float(pos.high_water or pos.entry_price), float(candle.high))
                    if float(pos.trail_pct or 0.0) > 0 and pos.high_water > 0:
                        pos.stop_loss = max(float(pos.stop_loss), pos.high_water * (1.0 - float(pos.trail_pct)))
                elif pos.direction == 'short':
                    pos.low_water = min(float(pos.low_water or pos.entry_price), float(candle.low))
                    if float(pos.trail_pct or 0.0) > 0 and pos.low_water > 0:
                        pos.stop_loss = min(float(pos.stop_loss), pos.low_water * (1.0 + float(pos.trail_pct)))

                if (
                    int(pos.max_hold_candles or 0) > 0
                    and timestamp - pos.open_time >= int(pos.max_hold_candles) * int(self.scan_settings.candle_seconds) * 1000
                ):
                    exit_price = candle.close
                    reason = "Max Hold"
                
                # Check SL/TP
                if exit_price is None and pos.direction == 'long':
                    if candle.low <= pos.stop_loss:
                        exit_price = pos.stop_loss # Assume execution at SL (gap risk ignored for simplicity)
                        reason = "Stop Loss"
                    elif candle.high >= pos.take_profit:
                        exit_price = pos.take_profit
                        reason = "Take Profit"
                elif exit_price is None and pos.direction == 'short':
                    if candle.high >= pos.stop_loss:
                        exit_price = pos.stop_loss
                        reason = "Stop Loss"
                    elif candle.low <= pos.take_profit:
                        exit_price = pos.take_profit
                        reason = "Take Profit"
                
                # Check Signal Exit
                if not exit_price:
                    if pos.direction == 'long' and long_signal and long_signal.direction is None:
                        exit_price = candle.close
                        reason = long_signal.exit_reason
                    elif pos.direction == 'short' and short_signal and short_signal.direction is None:
                        exit_price = candle.close
                        reason = short_signal.exit_reason
                
                if exit_price:
                    # Execute Exit
                    adjusted_exit_price = apply_slippage(exit_price, self.slippage, 'short' if pos.direction == 'long' else 'long')
                    fee = calculate_fee(pos.quantity, adjusted_exit_price, self.fee_rate)
                    
                    pnl = 0
                    if pos.direction == 'long':
                        pnl = (adjusted_exit_price - pos.entry_price) * pos.quantity
                    else:
                        pnl = (pos.entry_price - adjusted_exit_price) * pos.quantity
                        
                    pnl -= fee
                    self.balance += pnl
                    
                    self.trades.append(Trade(
                        entry_time=pos.open_time,
                        exit_time=timestamp,
                        symbol=symbol,
                        direction=pos.direction,
                        entry_price=pos.entry_price,
                        exit_price=adjusted_exit_price,
                        quantity=pos.quantity,
                        pnl=pnl,
                        pnl_percent=(pnl / (pos.entry_price * pos.quantity)) * 100,
                        fee=fee
                    ))
                    
                    del self.positions[symbol]
                    if self.scan_settings.cooldown_candles > 0:
                        self._cooldown_until_candle[symbol] = candle_index + int(self.scan_settings.cooldown_candles)
                    # Notify scanners of flat position if needed (simple scanners here handle logic internally based on update return)
            
            # Entry Logic (only if no position)
            if symbol not in self.positions and len(self.positions) < self.config['risk'].get('max_positions', 1):
                if self._cooldown_until_candle.get(symbol, -1) > candle_index:
                    self.equity_curve.append({'timestamp': timestamp, 'balance': self.balance})
                    continue

                signal = None
                if long_signal and long_signal.direction == 'long':
                    signal = long_signal
                elif short_signal and short_signal.direction == 'short':
                    signal = short_signal
                
                if signal:
                    if self.scan_settings.direction != "BOTH" and signal.direction.upper() != self.scan_settings.direction:
                        signal = None
                    score_payload = getattr(signal, "score", None) or {}
                    score_total = int((score_payload or {}).get("total") or 0)
                    signals_count = len((score_payload or {}).get("signals") or [])

                if signal:
                    if score_total < int(self.scan_settings.min_score):
                        signal = None
                    elif signals_count < int(self.scan_settings.min_signals):
                        signal = None

                if signal:
                    qty = (float(self.scan_settings.margin_usdt) * float(self.scan_settings.leverage)) / max(float(signal.entry_price), 1e-8)
                    
                    if qty > 0:
                        adjusted_entry_price = apply_slippage(signal.entry_price, self.slippage, signal.direction)
                        fee = calculate_fee(qty, adjusted_entry_price, self.fee_rate)
                        protection = build_trade_protection_from_settings(
                            adjusted_entry_price,
                            qty,
                            signal.direction.upper(),
                            self.scan_settings,
                        )
                        
                        # Simplified: fee deducted from balance, not reducing qty
                        self.balance -= fee 
                        
                        self.positions[symbol] = Position(
                            symbol=symbol,
                            direction=signal.direction,
                            entry_price=adjusted_entry_price,
                            quantity=qty,
                            stop_loss=protection["stop_price"],
                            take_profit=protection["take_profit"],
                            open_time=timestamp,
                            leverage=int(self.scan_settings.leverage),
                            margin_used=float(self.scan_settings.margin_usdt),
                            score=score_total,
                            signals_count=signals_count,
                            trail_pct=float(self.scan_settings.trail_pct),
                            high_water=adjusted_entry_price if signal.direction == "long" else None,
                            low_water=adjusted_entry_price if signal.direction == "short" else None,
                            max_hold_candles=int(self.scan_settings.max_hold_candles),
                        )
            
            self.equity_curve.append({'timestamp': timestamp, 'balance': self.balance})

            daily_loss_limit = self.config['risk'].get('max_daily_loss')
            if daily_loss_limit and self.balance <= self.initial_balance * (1 - daily_loss_limit):
                self.logger.warning("Daily loss limit reached during backtest. Stopping run early.")
                break

    def generate_report(self, plot_filename: str | None = "backtest_equity.png"):
        if not self.trades:
            print("No trades executed.")
            self.last_report = {
                "final_balance": self.balance,
                "total_return": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "profit_factor": 0.0,
            }
            return self.last_report

        df_trades = pd.DataFrame([t.__dict__ for t in self.trades])
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = len(df_trades[df_trades['pnl'] > 0]) / len(df_trades) * 100
        
        # Max Drawdown
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['balance'].cummax()
        equity_df['drawdown'] = (equity_df['balance'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min() * 100

        returns = equity_df['balance'].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        sharpe_ratio = 0.0
        if not returns.empty and returns.std(ddof=0) > 0:
            sharpe_ratio = (returns.mean() / returns.std(ddof=0)) * np.sqrt(self._periods_per_year())

        gross_profit = df_trades.loc[df_trades['pnl'] > 0, 'pnl'].sum()
        gross_loss = df_trades.loc[df_trades['pnl'] < 0, 'pnl'].sum()
        if gross_loss == 0:
            profit_factor = float('inf') if gross_profit > 0 else 0.0
        else:
            profit_factor = gross_profit / abs(gross_loss)

        report = {
            "final_balance": round(self.balance, 2),
            "total_return": round(total_return, 2),
            "total_trades": int(len(self.trades)),
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else float('inf'),
        }
        self.last_report = report
        
        print(f"--- Backtest Report ---")
        print(f"Final Balance: {report['final_balance']:.2f}")
        print(f"Total Return: {report['total_return']:.2f}%")
        print(f"Total Trades: {report['total_trades']}")
        print(f"Win Rate: {report['win_rate']:.2f}%")
        print(f"Max Drawdown: {report['max_drawdown']:.2f}%")
        print(f"Sharpe Ratio: {report['sharpe_ratio']:.2f}")
        if np.isfinite(profit_factor):
            print(f"Profit Factor: {report['profit_factor']:.2f}")
        else:
            print("Profit Factor: inf")
        
        # Optional Plotting
        if plt is not None and plot_filename:
            try:
                plt.figure(figsize=(10, 6))
                plt.plot(pd.to_datetime(equity_df['timestamp'], unit='ms'), equity_df['balance'])
                plt.title("Equity Curve")
                plt.xlabel("Date")
                plt.ylabel("Balance")
                plt.savefig(plot_filename)
                print(f"Equity curve saved to {plot_filename}")
            except Exception as e:
                self.logger.error(f"Failed to plot: {e}")

        return report

if __name__ == "__main__":
    # Example usage (user would run main.py usually)
    pass
