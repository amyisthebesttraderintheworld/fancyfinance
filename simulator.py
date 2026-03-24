from __future__ import annotations

import asyncio
import json
import queue
import time
from typing import Any, Dict, Optional

import websockets

from common import (
    Candle,
    Position,
    TelegramNotifier,
    apply_slippage,
    calculate_fee,
    calculate_position_size,
    get_logger,
)
from exchange_manager import ExchangeManager
from scanner_long import LongScanner
from scanner_short import ShortScanner
from supabase_client import SupabaseManager

WS_PING_INTERVAL_SECONDS = 20
WS_PING_TIMEOUT_SECONDS = 60
SUBSCRIPTION_PAUSE_EVERY = 50
SUBSCRIPTION_PAUSE_SECONDS = 0.01


class Simulator:
    def __init__(self, config, notifier: TelegramNotifier, command_queue: queue.Queue):
        self.config = config
        self.notifier = notifier
        self.command_queue = command_queue
        self.logger = get_logger("Simulator")
        self.db = SupabaseManager()

        self.exchange_id = config.get("exchange", "phemex").lower()
        self.exchange = ExchangeManager(
            self.exchange_id,
            config.get("api_key"),
            config.get("api_secret"),
        )

        exchange_config = config.get(self.exchange_id, {})
        self.balance = config["backtest"]["initial_balance"]
        self.risk_per_trade = config["risk"]["risk_per_trade"]
        self.fee_rate = config["backtest"]["fee_rate"]
        self.slippage = config["backtest"]["slippage"]
        self.symbols = config.get("symbols") or exchange_config.get("symbols", [])

        self.long_scanners = {symbol: LongScanner(config) for symbol in self.symbols}
        self.short_scanners = {symbol: ShortScanner(config) for symbol in self.symbols}

        self.positions: dict[str, Position] = {}
        self.trade_history: list[dict[str, Any]] = []
        self.safety_paused_until = 0.0
        self.is_running = True
        self.is_paused = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._websocket = None

        ws_urls = {
            "phemex": "wss://ws.phemex.com",
        }
        self.ws_url = ws_urls.get(self.exchange_id, "")

    def _ensure_symbol_state(self, symbol: str):
        if symbol not in self.long_scanners:
            self.long_scanners[symbol] = LongScanner(self.config)
        if symbol not in self.short_scanners:
            self.short_scanners[symbol] = ShortScanner(self.config)

    def _normalize_price(self, value: Any) -> float:
        price = float(value)
        return price / 10000 if abs(price) > 1_000_000 else price

    def _parse_candle(self, symbol: str, payload: Any) -> Optional[Candle]:
        try:
            if isinstance(payload, dict):
                return Candle(
                    timestamp=int(payload.get("timestamp") or payload.get("t") or payload.get("openTime")),
                    open=self._normalize_price(payload.get("open") or payload.get("o")),
                    high=self._normalize_price(payload.get("high") or payload.get("h")),
                    low=self._normalize_price(payload.get("low") or payload.get("l")),
                    close=self._normalize_price(payload.get("close") or payload.get("c")),
                    volume=float(payload.get("volume") or payload.get("v") or 0.0),
                    symbol=symbol,
                )

            if isinstance(payload, (list, tuple)) and len(payload) >= 6:
                return Candle(
                    timestamp=int(payload[0]),
                    open=self._normalize_price(payload[1]),
                    high=self._normalize_price(payload[2]),
                    low=self._normalize_price(payload[3]),
                    close=self._normalize_price(payload[4]),
                    volume=float(payload[5]),
                    symbol=symbol,
                )
        except (TypeError, ValueError) as exc:
            self.logger.debug(f"Skipped malformed candle payload for {symbol}: {exc}")

        return None

    async def _subscribe(self, websocket):
        for index, symbol in enumerate(self.symbols, start=1):
            subscribe_msg = {
                "id": index,
                "method": "kline.subscribe",
                "params": [symbol, 60],
            }
            await websocket.send(json.dumps(subscribe_msg))
            if index % SUBSCRIPTION_PAUSE_EVERY == 0:
                await asyncio.sleep(SUBSCRIPTION_PAUSE_SECONDS)
            self.logger.debug(f"Subscribed to {symbol}")

    async def _handle_ws_message(self, data: Dict[str, Any]):
        symbol = data.get("symbol") or data.get("s")
        kline_payload = data.get("kline") or data.get("data")
        if not symbol or not kline_payload:
            return

        if isinstance(kline_payload, dict):
            kline_payload = [kline_payload]

        for raw_candle in kline_payload:
            candle = self._parse_candle(symbol, raw_candle)
            if candle:
                await self._process_candle(symbol, candle)

    async def _ws_handler(self):
        if not self.ws_url:
            self.logger.warning(f"No WebSocket URL configured for exchange '{self.exchange_id}'.")
            while self.is_running:
                await asyncio.sleep(1)
            return

        while self.is_running:
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=WS_PING_INTERVAL_SECONDS,
                    ping_timeout=WS_PING_TIMEOUT_SECONDS,
                ) as websocket:
                    self._websocket = websocket
                    self.logger.info("Connected to WebSocket")
                    await self._subscribe(websocket)

                    while self.is_running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue

                        data = json.loads(message)
                        await self._handle_ws_message(data)
            except Exception as exc:
                self.logger.error(f"WS Error: {exc}")
                if self.is_running:
                    await asyncio.sleep(5)
            finally:
                self._websocket = None

    async def _process_candle(self, symbol: str, candle: Candle):
        if self.is_paused:
            return

        self._ensure_symbol_state(symbol)
        candle.symbol = symbol

        long_scanner = self.long_scanners[symbol]
        short_scanner = self.short_scanners[symbol]

        long_signal = long_scanner.update(candle)
        short_signal = short_scanner.update(candle)

        if symbol in self.positions:
            pos = self.positions[symbol]
            exit_price = None
            reason = None

            if pos.direction == "long":
                if candle.low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "Stop Loss"
                elif candle.high >= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "Take Profit"
            elif pos.direction == "short":
                if candle.high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "Stop Loss"
                elif candle.low <= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "Take Profit"

            if exit_price is None:
                if pos.direction == "long" and long_signal and long_signal.direction is None:
                    exit_price = candle.close
                    reason = long_signal.exit_reason
                elif pos.direction == "short" and short_signal and short_signal.direction is None:
                    exit_price = candle.close
                    reason = short_signal.exit_reason

            if exit_price is not None:
                self._execute_trade(symbol, pos.direction, exit_price, pos.quantity, is_entry=False, reason=reason)
                if pos.direction == "long":
                    long_scanner.has_position = False
                if pos.direction == "short":
                    short_scanner.has_position = False

        elif len(self.positions) < self.config["risk"].get("max_positions", 1):
            signal = None
            if long_signal and long_signal.direction == "long":
                signal = long_signal
            elif short_signal and short_signal.direction == "short":
                signal = short_signal

            if signal:
                stop_distance = abs(signal.entry_price - signal.stop_loss)
                quantity = calculate_position_size(
                    self.balance,
                    self.risk_per_trade,
                    stop_distance,
                    signal.entry_price,
                )
                if quantity > 0:
                    self._execute_trade(
                        symbol,
                        signal.direction,
                        signal.entry_price,
                        quantity,
                        is_entry=True,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                    )

    def _check_safety_timeout(self):
        if self.is_paused:
            return

        consecutive_losses = 0
        for trade in reversed(self.trade_history):
            if trade["pnl"] < 0:
                consecutive_losses += 1
            else:
                break

        max_losses = self.config["safety"]["max_consecutive_losses"]
        if consecutive_losses >= max_losses:
            self.is_paused = True
            self.safety_paused_until = time.time() + (self.config["safety"]["timeout_duration_minutes"] * 60)
            msg = (
                "🛡️ *SAFETY TIMEOUT TRIGGERED*\n\n"
                f"Reason: {consecutive_losses} consecutive losses.\n"
                f"Trading paused for {self.config['safety']['timeout_duration_minutes']} minutes."
            )
            self.notifier.send_message(msg)
            self.logger.warning(f"Safety timeout triggered: {consecutive_losses} losses.")

    def _execute_trade(self, symbol, direction, price, qty, is_entry, stop_loss=None, take_profit=None, reason=None):
        adjusted_direction = direction if is_entry else ("short" if direction == "long" else "long")
        adjusted_price = apply_slippage(price, self.slippage, adjusted_direction)
        fee = calculate_fee(qty, adjusted_price, self.fee_rate)

        if is_entry:
            self.balance -= fee
            position = Position(symbol, direction, adjusted_price, qty, stop_loss, take_profit, int(time.time() * 1000))
            self.positions[symbol] = position

            self.db.log_trade(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "price": adjusted_price,
                    "qty": qty,
                    "type": "entry",
                }
            )
            self.db.update_position(
                symbol,
                {
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": adjusted_price,
                    "qty": qty,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
            )

            self.notifier.send_message(f"🔵 SIM ENTRY: {direction.upper()} {symbol} @ {adjusted_price:.2f} Qty: {qty:.4f}")
            self.logger.info(f"Entry {symbol} {direction} @ {adjusted_price}")
            return

        position = self.positions[symbol]
        if direction == "long":
            pnl = (adjusted_price - position.entry_price) * qty
        else:
            pnl = (position.entry_price - adjusted_price) * qty

        pnl -= fee
        self.balance += pnl
        self.trade_history.append({"symbol": symbol, "pnl": pnl, "timestamp": time.time()})

        self.db.log_trade(
            {
                "symbol": symbol,
                "direction": direction,
                "price": adjusted_price,
                "qty": qty,
                "type": "exit",
                "pnl": pnl,
                "reason": reason,
            }
        )
        self.db.remove_position(symbol)

        del self.positions[symbol]
        self.notifier.send_message(
            f"🔴 SIM EXIT: {direction.upper()} {symbol} @ {adjusted_price:.2f} PnL: {pnl:.2f} Reason: {reason}"
        )
        self.logger.info(f"Exit {symbol} {direction} @ {adjusted_price} PnL: {pnl}")
        self._check_safety_timeout()

    async def _command_listener(self):
        while self.is_running:
            try:
                if not self.command_queue.empty():
                    command = self.command_queue.get()
                    await self._handle_command(command)
                await asyncio.sleep(0.1)
            except Exception as exc:
                self.logger.error(f"Command listener error: {exc}")

    async def _handle_command(self, cmd):
        command, args, chat_id = cmd
        response = ""

        if command == "/status":
            response = (
                f"Balance: {self.balance:.2f}\n"
                f"Open Positions: {len(self.positions)}\n"
                f"Paused: {self.is_paused}"
            )
        elif command == "/pause":
            self.is_paused = True
            response = "Simulation paused."
        elif command == "/resume":
            now = time.time()
            if now < self.safety_paused_until:
                remaining = int((self.safety_paused_until - now) / 60)
                response = f"⚠️ Still in Safety Timeout. {remaining} minutes remaining."
            else:
                self.is_paused = False
                self.safety_paused_until = 0
                response = "Simulation resumed."
        elif command == "/reset":
            self.balance = self.config["backtest"]["initial_balance"]
            self.positions = {}
            self.trade_history = []
            for scanner in self.long_scanners.values():
                scanner.reset()
            for scanner in self.short_scanners.values():
                scanner.reset()
            response = "Simulation reset."
        elif command == "/set_balance":
            if args:
                try:
                    self.balance = float(args[0])
                    response = f"Balance set to {self.balance}"
                except ValueError:
                    response = "Invalid amount."
            else:
                response = "Usage: /set_balance <amount>"
        elif command == "/shutdown":
            self.stop()
            response = "Simulation shutting down..."
        else:
            response = "Unknown command."

        self.notifier.send_message(response)

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        await asyncio.gather(
            self._ws_handler(),
            self._command_listener(),
        )

    def start(self):
        self.logger.info("Starting Simulator...")
        self.is_running = True
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.is_running = False
        self.logger.info("Simulator stopped.")
        if self._websocket and self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)
            except RuntimeError:
                pass
