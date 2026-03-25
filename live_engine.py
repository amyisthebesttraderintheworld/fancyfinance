from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from common import PhemexClient, Position, calculate_position_size, get_logger
from simulator import Simulator


POSITION_RECONCILIATION_INTERVAL_SECONDS = 30
BALANCE_REFRESH_MIN_SECONDS = 5
ORDER_SYNC_RETRIES = 4
ORDER_SYNC_DELAY_SECONDS = 0.75


class LiveEngine(Simulator):
    def __init__(self, config, notifier, command_queue):
        super().__init__(config, notifier, command_queue)
        self.logger = get_logger("LiveEngine")
        self.client: Optional[PhemexClient] = None
        self._balance_reference = 0.0
        self._last_balance_refresh_monotonic = 0.0
        self._last_balance_refresh_candle_ts: Optional[int] = None

        if self._runtime_api_ready():
            self._configure_live_client(notify=True)
        else:
            self.logger.warning("Live Engine started without unlocked API credentials. Use /unlock_api to continue.")
            self.notifier.send_message("🔐 Live Engine waiting for `/unlock_api <passphrase>` to load exchange credentials.")

    def _configure_live_client(self, notify: bool = True):
        exchange_cfg = self.config.get(self.exchange_id, {})
        api_key = exchange_cfg.get("api_key") or self.config.get("api_key")
        api_secret = exchange_cfg.get("api_secret") or self.config.get("api_secret")
        if not api_key or not api_secret or api_key == "YOUR_API_KEY" or api_secret == "YOUR_API_SECRET":
            self.client = None
            return False

        self.client = PhemexClient(
            api_key,
            api_secret,
            testnet=bool(exchange_cfg.get("testnet", False)),
            account_currency=str(exchange_cfg.get("account_currency") or "USDT"),
        )
        self._refresh_balance(force=True)
        self._balance_reference = max(self._balance_reference, self.balance)
        self.logger.info(f"Live Engine initialized. Balance: {self.balance}")
        self._reconcile_positions_once(notify=False)
        if notify:
            self.notifier.send_message(f"🚀 Live Engine Started. Balance: {self.balance:.4f}")
        return True

    def _apply_runtime_api_keys(self, user_id: int, api_key: str, api_secret: str):
        super()._apply_runtime_api_keys(user_id, api_key, api_secret)
        self._configure_live_client(notify=True)

    @staticmethod
    def _coerce_price(value: Any, key: str = "") -> Optional[float]:
        if value in (None, "", 0, "0"):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if key.endswith("Ep"):
            return number / 10000.0
        return number

    @staticmethod
    def _coerce_quantity(value: Any) -> float:
        try:
            return abs(float(value))
        except (TypeError, ValueError):
            return 0.0

    def _extract_price_field(self, payload: dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            if key in payload:
                price = self._coerce_price(payload.get(key), key)
                if price and price > 0:
                    return price
        return None

    def _extract_qty_field(self, payload: dict[str, Any], *keys: str) -> float:
        for key in keys:
            if key in payload:
                qty = self._coerce_quantity(payload.get(key))
                if qty > 0:
                    return qty
        return 0.0

    def _extract_direction(self, payload: dict[str, Any], qty_hint: float = 0.0) -> Optional[str]:
        side_value = str(payload.get("side") or payload.get("posSide") or payload.get("direction") or "").strip().lower()
        if side_value in {"buy", "long"}:
            return "long"
        if side_value in {"sell", "short"}:
            return "short"

        signed_size = payload.get("size") or payload.get("currentQty") or payload.get("pos")
        try:
            signed_number = float(signed_size)
        except (TypeError, ValueError):
            signed_number = 0.0
        if signed_number < 0:
            return "short"
        if signed_number > 0 or qty_hint > 0:
            return "long"
        return None

    def _build_position_from_exchange(self, raw_position: dict[str, Any]) -> Optional[Position]:
        symbol = str(raw_position.get("symbol") or "").strip()
        if not symbol:
            return None

        qty = self._extract_qty_field(
            raw_position,
            "size",
            "currentQty",
            "orderQty",
            "qty",
            "posSize",
        )
        if qty <= 0:
            return None

        direction = self._extract_direction(raw_position, qty_hint=qty)
        if direction not in {"long", "short"}:
            return None

        entry_price = self._extract_price_field(
            raw_position,
            "avgEntryPriceRp",
            "avgEntryPriceEp",
            "avgEntryPrice",
            "entryPriceRp",
            "entryPriceEp",
            "entryPrice",
        )
        if not entry_price:
            return None

        stop_loss = self._extract_price_field(raw_position, "stopLossRp", "stopLossEp", "stopLoss") or 0.0
        take_profit = self._extract_price_field(raw_position, "takeProfitRp", "takeProfitEp", "takeProfit") or 0.0
        open_time = int(time.time() * 1000)

        return Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=open_time,
        )

    def _set_scanner_position_flags(self):
        for scanner in self.long_scanners.values():
            scanner.has_position = False
        for scanner in self.short_scanners.values():
            scanner.has_position = False

        for symbol, position in self.positions.items():
            self._ensure_symbol_state(symbol)
            self.long_scanners[symbol].has_position = position.direction == "long"
            self.short_scanners[symbol].has_position = position.direction == "short"

    def _scan_market_candidates(self) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        return super()._scan_market_candidates()

    def _refresh_balance(self, *, force: bool = False, candle_timestamp: Optional[int] = None) -> float:
        if self.client is None:
            return self.balance

        now = time.monotonic()
        if not force:
            if candle_timestamp is not None and candle_timestamp == self._last_balance_refresh_candle_ts:
                return self.balance
            if candle_timestamp is None and (now - self._last_balance_refresh_monotonic) < BALANCE_REFRESH_MIN_SECONDS:
                return self.balance

        try:
            current_balance = float(self.client.get_account())
        except Exception as exc:
            self.logger.warning(f"Failed to refresh live balance: {exc}")
            return self.balance

        self.balance = current_balance
        self._balance_reference = max(self._balance_reference, current_balance)
        self._last_balance_refresh_monotonic = now
        if candle_timestamp is not None:
            self._last_balance_refresh_candle_ts = candle_timestamp
        return current_balance

    def _max_daily_loss_exceeded(self, current_balance: Optional[float] = None) -> bool:
        current = current_balance if current_balance is not None else self.balance
        reference_balance = max(self._balance_reference, current)
        max_daily_loss = float(self.config["risk"]["max_daily_loss"])
        return reference_balance > 0 and current < reference_balance * (1 - max_daily_loss)

    def _reconcile_positions_once(self, *, notify: bool = False):
        if self.client is None:
            return

        try:
            exchange_positions = self.client.get_positions()
        except Exception as exc:
            self.logger.warning(f"Failed to reconcile positions from Phemex: {exc}")
            return

        previous_positions = dict(self.positions)
        reconciled_positions: dict[str, Position] = {}
        for raw_position in exchange_positions or []:
            if not isinstance(raw_position, dict):
                continue
            position = self._build_position_from_exchange(raw_position)
            if not position:
                continue
            reconciled_positions[position.symbol] = position

        removed_symbols = set(previous_positions) - set(reconciled_positions)
        for symbol in removed_symbols:
            self.db.remove_position(symbol)
            if notify:
                self.notifier.send_message(
                    f"⚠️ LIVE SYNC: `{symbol}` is no longer open on Phemex. Local state was updated to match the exchange."
                )

        for symbol, position in reconciled_positions.items():
            self.db.update_position(
                symbol,
                {
                    "symbol": symbol,
                    "direction": position.direction,
                    "entry_price": position.entry_price,
                    "qty": position.quantity,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                },
            )

        self.positions = reconciled_positions
        self._set_scanner_position_flags()
        for symbol in set(reconciled_positions) - set(previous_positions):
            self._subscribe_symbol(symbol)

    def _sync_symbol_after_order(
        self,
        symbol: str,
        *,
        expected_direction: Optional[str] = None,
        fallback_price: Optional[float] = None,
        fallback_qty: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Position]:
        for attempt in range(ORDER_SYNC_RETRIES):
            self._reconcile_positions_once(notify=False)
            position = self.positions.get(symbol)
            if position:
                if stop_loss is not None and not position.stop_loss:
                    position.stop_loss = stop_loss
                if take_profit is not None and not position.take_profit:
                    position.take_profit = take_profit
                return position

            if expected_direction is None:
                break

            if attempt < ORDER_SYNC_RETRIES - 1:
                time.sleep(ORDER_SYNC_DELAY_SECONDS)

        if expected_direction is None:
            return None

        self.logger.warning(
            f"Order sync for {symbol} never produced an exchange-confirmed {expected_direction} position. "
            "Keeping local state empty until Phemex reports the fill."
        )
        return None

    def _extract_order_fill_price(self, order_response: Any, fallback_price: float) -> float:
        if isinstance(order_response, dict):
            price = self._extract_price_field(
                order_response,
                "avgFillPriceRp",
                "avgFillPriceEp",
                "avgFillPrice",
                "execPriceRp",
                "execPriceEp",
                "execPrice",
                "priceRp",
                "priceEp",
                "price",
            )
            if price:
                return price
        return float(fallback_price)

    def _extract_order_fill_qty(self, order_response: Any, fallback_qty: float) -> float:
        if isinstance(order_response, dict):
            qty = self._extract_qty_field(order_response, "cumQty", "execQty", "orderQty", "qty")
            if qty > 0:
                return qty
        return float(fallback_qty)

    async def _reconciliation_loop(self):
        while self.is_running:
            try:
                await asyncio.sleep(POSITION_RECONCILIATION_INTERVAL_SECONDS)
                self._refresh_balance(force=True)
                self._reconcile_positions_once(notify=True)
            except Exception as exc:
                self.logger.error(f"Live reconciliation loop error: {exc}")

    async def _process_candle(self, symbol, candle):
        if self.is_paused:
            return

        self._refresh_balance(candle_timestamp=candle.timestamp)
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

            if pos.direction == "long" and long_signal and long_signal.direction is None:
                exit_price = candle.close
                reason = long_signal.exit_reason
            elif pos.direction == "short" and short_signal and short_signal.direction is None:
                exit_price = candle.close
                reason = short_signal.exit_reason

            if exit_price is not None:
                self._execute_trade(symbol, pos.direction, exit_price, pos.quantity, is_entry=False, reason=reason)

            return

        if self.use_market_scan_engine:
            return

        if len(self.positions) >= self.config["risk"].get("max_positions", 1):
            return

        signal = None
        if long_signal and long_signal.direction == "long":
            signal = long_signal
        elif short_signal and short_signal.direction == "short":
            signal = short_signal

        if not signal:
            return

        stop_distance = abs(signal.entry_price - signal.stop_loss)
        quantity = calculate_position_size(
            self.balance,
            self.risk_per_trade,
            stop_distance,
            signal.entry_price,
        )
        if quantity <= 0:
            return

        self._execute_trade(
            symbol,
            signal.direction,
            signal.entry_price,
            quantity,
            is_entry=True,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

    async def _handle_command(self, cmd):
        command, args, chat_id = cmd
        response = ""

        if command == "/shutdown":
            self.stop()
            response = "Engine shutting down..."
        elif command == "/emergency_stop":
            self.is_paused = True
            cancelled_orders = 0

            if self.client is not None:
                for symbol in self.symbols:
                    try:
                        for order in self.client.get_open_orders(symbol) or []:
                            order_id = order.get("orderID") or order.get("orderId")
                            if not order_id:
                                continue
                            self.client.cancel_order(symbol, order_id)
                            cancelled_orders += 1
                    except Exception as exc:
                        self.logger.warning(f"Emergency stop failed to cancel open orders for {symbol}: {exc}")

                self._reconcile_positions_once(notify=False)

            response = f"EMERGENCY STOP TRIGGERED. Trading paused, {cancelled_orders} open orders cancelled."
        else:
            await super()._handle_command(cmd)
            return

        self._send_command_response(chat_id, response)

    def _execute_trade(self, symbol, direction, price, qty, is_entry, stop_loss=None, take_profit=None, reason=None):
        if self.client is None:
            self.logger.warning("Live trade requested before API vault was unlocked.")
            self.notifier.send_message("🔐 Unlock the API vault with `/unlock_api <passphrase>` before live trading.")
            return

        current_balance = self._refresh_balance(force=True)
        if self._max_daily_loss_exceeded(current_balance):
            self.logger.critical("Max daily loss exceeded. Stopping.")
            self.stop()
            self.notifier.send_message("🚨 Max daily loss exceeded. Engine stopped.")
            return

        side = "Buy" if direction == "long" else "Sell"
        if not is_entry:
            side = "Sell" if direction == "long" else "Buy"

        try:
            if is_entry:
                order = self.client.place_order(
                    symbol,
                    side,
                    qty,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                fill_price = self._extract_order_fill_price(order, fallback_price=price)
                fill_qty = self._extract_order_fill_qty(order, fallback_qty=qty)
                position = self._sync_symbol_after_order(
                    symbol,
                    expected_direction=direction,
                    fallback_price=fill_price,
                    fallback_qty=fill_qty,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                if position is None:
                    raise RuntimeError(f"Entry order for {symbol} did not produce a reconciled position.")

                entry_payload = self._record_trade_event(
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "price": position.entry_price,
                        "qty": position.quantity,
                        "type": "entry",
                    }
                )
                self.db.log_trade(entry_payload)
                self.db.update_position(
                    symbol,
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "entry_price": position.entry_price,
                        "qty": position.quantity,
                        "stop_loss": position.stop_loss,
                        "take_profit": position.take_profit,
                    },
                )
                self.notifier.send_message(
                    f"🔵 LIVE ENTRY: {symbol} {side} Qty: {position.quantity:.4f} @ {position.entry_price:.2f}"
                )
                self.logger.info(f"Live entry {symbol} {direction} @ {position.entry_price} Qty: {position.quantity}")
            else:
                existing_position = self.positions.get(symbol)
                order = self.client.place_order(
                    symbol,
                    side,
                    qty,
                    reduce_only=True,
                )
                self._sync_symbol_after_order(symbol, expected_direction=None)
                remaining_position = self.positions.get(symbol)
                fill_price = self._extract_order_fill_price(order, fallback_price=price)

                if not remaining_position:
                    pnl = None
                    if existing_position:
                        if direction == "long":
                            pnl = (fill_price - existing_position.entry_price) * existing_position.quantity
                        else:
                            pnl = (existing_position.entry_price - fill_price) * existing_position.quantity

                    exit_payload = self._record_trade_event(
                        {
                            "symbol": symbol,
                            "direction": direction,
                            "price": fill_price,
                            "qty": float(qty),
                            "type": "exit",
                            "pnl": pnl,
                            "reason": reason,
                        }
                    )
                    self.db.log_trade(exit_payload)
                    self.db.remove_position(symbol)
                    self.notifier.send_message(
                        f"🔴 LIVE EXIT: {symbol} {side} Qty: {float(qty):.4f} @ {fill_price:.2f} Reason: {reason}"
                    )
                    self.logger.info(f"Live exit {symbol} {direction} @ {fill_price} Qty: {qty}")
                    self._check_safety_timeout()
                else:
                    self.db.update_position(
                        symbol,
                        {
                            "symbol": symbol,
                            "direction": remaining_position.direction,
                            "entry_price": remaining_position.entry_price,
                            "qty": remaining_position.quantity,
                            "stop_loss": remaining_position.stop_loss,
                            "take_profit": remaining_position.take_profit,
                        },
                    )
                    self.notifier.send_message(
                        f"🟠 LIVE EXIT SENT: {symbol} reduce-only {side} Qty: {float(qty):.4f}. Remaining size: {remaining_position.quantity:.4f}"
                    )
        except Exception as exc:
            self.logger.error(f"Order Execution Failed: {exc}")
            self.notifier.send_message(f"⚠️ Order Execution Failed: {exc}")
        finally:
            self._refresh_balance(force=True)

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        await asyncio.gather(
            self._ws_handler(),
            self._command_listener(),
            self._market_scan_loop(),
            self._reconciliation_loop(),
        )
