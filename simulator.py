from __future__ import annotations

import asyncio
import json
import queue
import time
from typing import Any, Dict, Optional

import requests
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
from fang_engine_runtime import build_entry_plan, resolve_scan_settings, run_market_scan
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
        self._subscribed_symbols: set[str] = set()
        self.active_api_user_id: Optional[int] = None
        self.use_market_scan_engine = True
        self.market_scan_settings = resolve_scan_settings(config)

        ws_urls = {
            "phemex": "wss://ws.phemex.com",
        }
        self.ws_url = ws_urls.get(self.exchange_id, "")

    def _runtime_api_ready(self) -> bool:
        api_key = self.config.get(self.exchange_id, {}).get("api_key") or self.config.get("api_key")
        api_secret = self.config.get(self.exchange_id, {}).get("api_secret") or self.config.get("api_secret")
        return bool(api_key and api_secret and api_key != "YOUR_API_KEY" and api_secret != "YOUR_API_SECRET")

    def _apply_runtime_api_keys(self, user_id: int, api_key: str, api_secret: str):
        self.config.setdefault(self.exchange_id, {})
        self.config[self.exchange_id]["api_key"] = api_key
        self.config[self.exchange_id]["api_secret"] = api_secret
        self.config["api_key"] = api_key
        self.config["api_secret"] = api_secret
        self.exchange = ExchangeManager(self.exchange_id, api_key, api_secret)
        self.active_api_user_id = user_id

    def _send_command_response(self, chat_id: Optional[int], text: str):
        telegram_config = self.config.get("telegram", {})
        token = telegram_config.get("bot_token")
        if token and chat_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=15,
                )
                return
            except Exception as exc:
                self.logger.warning(f"Failed to send direct command response to chat {chat_id}: {exc}")

        self.notifier.send_message(text)

    def _ensure_symbol_state(self, symbol: str):
        if symbol not in self.long_scanners:
            self.long_scanners[symbol] = LongScanner(self.config)
        if symbol not in self.short_scanners:
            self.short_scanners[symbol] = ShortScanner(self.config)

    def _subscribe_payload(self, symbol: str) -> dict[str, Any]:
        return {
            "id": len(self._subscribed_symbols) + 1,
            "method": "kline.subscribe",
            "params": [symbol, 60],
        }

    def _subscribe_symbol(self, symbol: str):
        if not symbol or symbol in self._subscribed_symbols:
            return

        self._ensure_symbol_state(symbol)
        self._subscribed_symbols.add(symbol)
        if self._websocket and self._loop and self._loop.is_running():
            async def _send():
                await self._websocket.send(json.dumps(self._subscribe_payload(symbol)))

            try:
                asyncio.run_coroutine_threadsafe(_send(), self._loop)
            except RuntimeError:
                pass

    def _scan_market_candidates(self) -> list[dict[str, Any]]:
        if not self.use_market_scan_engine or self.is_paused:
            return []

        max_positions = int(self.config["risk"].get("max_positions", 1))
        available_slots = max_positions - len(self.positions)
        if available_slots <= 0:
            return []
        if self.balance < self.market_scan_settings.margin_usdt:
            return []

        candidates = run_market_scan(
            self.market_scan_settings,
            in_position=set(self.positions.keys()),
            available_slots=available_slots,
        )
        plans: list[dict[str, Any]] = []
        for result, direction in candidates:
            plan = build_entry_plan(result, direction, self.market_scan_settings)
            if not plan or not plan.get("symbol"):
                continue
            plans.append(plan)
        return plans

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
                if len(payload) >= 8:
                    return Candle(
                        timestamp=int(payload[0]),
                        open=self._normalize_price(payload[3]),
                        high=self._normalize_price(payload[4]),
                        low=self._normalize_price(payload[5]),
                        close=self._normalize_price(payload[6]),
                        volume=float(payload[7]),
                        symbol=symbol,
                    )
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
        symbols = sorted(self.positions.keys()) if self.use_market_scan_engine else list(self.symbols)
        self._subscribed_symbols = set()

        for index, symbol in enumerate(symbols, start=1):
            subscribe_msg = {
                "id": index,
                "method": "kline.subscribe",
                "params": [symbol, 60],
            }
            await websocket.send(json.dumps(subscribe_msg))
            self._subscribed_symbols.add(symbol)
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

        elif not self.use_market_scan_engine and len(self.positions) < self.config["risk"].get("max_positions", 1):
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

    async def _market_scan_loop(self):
        if not self.use_market_scan_engine:
            return

        await asyncio.sleep(1.0)
        while self.is_running:
            try:
                plans = await asyncio.to_thread(self._scan_market_candidates)
                for plan in plans:
                    if not self.is_running or self.is_paused:
                        break
                    if plan["symbol"] in self.positions:
                        continue
                    if len(self.positions) >= self.config["risk"].get("max_positions", 1):
                        break
                    self._execute_trade(
                        plan["symbol"],
                        plan["direction"],
                        plan["price"],
                        plan["quantity"],
                        is_entry=True,
                        stop_loss=plan["stop_loss"],
                        take_profit=plan["take_profit"],
                    )
            except Exception as exc:
                self.logger.error(f"Market scan loop error: {exc}")

            sleep_seconds = max(5, int(self.market_scan_settings.interval_seconds))
            for _ in range(sleep_seconds):
                if not self.is_running:
                    return
                await asyncio.sleep(1)

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
            self._subscribe_symbol(symbol)

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

    def _positions_summary_text(self) -> str:
        if not self.positions:
            return "No open positions right now."

        lines = ["Open Positions:"]
        for symbol, position in self.positions.items():
            lines.append(
                f"{symbol}: {position.direction.upper()} | Entry {position.entry_price:.4f} | "
                f"Qty {position.quantity:.4f} | SL {position.stop_loss:.4f} | TP {position.take_profit:.4f}"
            )
        return "\n".join(lines)

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
                f"Paused: {self.is_paused}\n"
                f"API Vault Unlocked: {self._runtime_api_ready()}"
            )
        elif command == "/positions":
            response = self._positions_summary_text()
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
        elif command == "/unlock_api":
            if len(args) < 2:
                response = "Usage: /unlock_api <passphrase>"
            else:
                try:
                    user_id = int(args[0])
                except ValueError:
                    response = "Invalid user ID for vault unlock."
                else:
                    passphrase = " ".join(args[1:])
                    credentials = self.db.get_user_api_keys(
                        user_id,
                        passphrase=passphrase,
                        exchange=self.exchange_id,
                    )
                    if not credentials:
                        response = "Could not unlock the API vault. Check your passphrase and stored keys."
                    else:
                        self._apply_runtime_api_keys(
                            user_id,
                            credentials["api_key"],
                            credentials["api_secret"],
                        )
                        response = f"API vault unlocked for {self.exchange_id} in this session."
        else:
            response = "Unknown command."

        self._send_command_response(chat_id, response)

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        await asyncio.gather(
            self._ws_handler(),
            self._command_listener(),
            self._market_scan_loop(),
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
