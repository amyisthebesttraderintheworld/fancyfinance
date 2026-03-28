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
        self.clients: dict[int, PhemexClient] = {}
        self._balance_reference = 0.0
        self._last_balance_refresh_monotonic = 0.0
        self._last_balance_refresh_candle_ts: Optional[int] = None

        if self._runtime_api_ready():
            self._configure_live_client(notify=True)
        else:
            self.logger.warning("Live Engine started without unlocked API credentials. Use /unlock_api to continue.")
            self.notifier.send_message("🔐 Live Engine waiting for `/unlock_api <passphrase>` to load exchange credentials.")

        # Attempt to auto-initialize clients for users with already stored/decrypted keys if possible
        # (Usually requires /unlock_api for zero-knowledge, but legacy or config keys work immediately)
        self._initialize_stored_clients()

    def _initialize_stored_clients(self):
        # Find all users who might have keys
        summary = self.db.get_user_summary(limit=1000)
        for user in summary.get("recent", []):
            user_id = user.get("telegram_id")
            if not user_id: continue
            
            # Try to get keys (will only work if legacy or no passphrase needed)
            keys = self.db.get_user_api_keys(user_id)
            if keys:
                self.logger.info(f"Auto-initializing live client for user {user_id}")
                self._configure_live_client(user_id=user_id, notify=False)

    def _configure_live_client(self, user_id: Optional[int] = None, notify: bool = True):
        exchange_cfg = self.config.get(self.exchange_id, {})
        api_key = exchange_cfg.get("api_key") or self.config.get("api_key")
        api_secret = exchange_cfg.get("api_secret") or self.config.get("api_secret")

        # If user_id is provided, prefer session-stored keys
        session = None
        if user_id:
            session = self.get_user_session(user_id)
            if session and session.runtime_api_key and session.runtime_api_secret:
                api_key = session.runtime_api_key
                api_secret = session.runtime_api_secret

        if not api_key or not api_secret or api_key == "YOUR_API_KEY" or api_secret == "YOUR_API_SECRET":
            if user_id:
                self.clients.pop(user_id, None)
            else:
                self.client = None
            return False

        new_client = PhemexClient(
            api_key,
            api_secret,
            testnet=bool(exchange_cfg.get("testnet", False)),
            account_currency=str(exchange_cfg.get("account_currency") or "USDT"),
        )

        if user_id:
            self.clients[user_id] = new_client
            if session:
                self._refresh_balance(session=session, force=True)
                session.reference_balance = max(session.reference_balance, session.balance)
                self.logger.info(f"Live Engine session for user {user_id} initialized. Balance: {session.balance}")
                self._reconcile_positions_once(session=session, notify=False)
                if notify:
                    self.notifier.send_message(f"🚀 Live Engine Session Unlocked. Balance: {session.balance:.4f}", user_id=str(user_id))
        else:
            self.client = new_client
            self._refresh_balance(force=True)
            self._balance_reference = max(self._balance_reference, self.balance)
            self.logger.info(f"Live Engine global initialized. Balance: {self.balance}")
            self._reconcile_positions_once(notify=False)
            if notify:
                self.notifier.send_message(f"🚀 Live Engine Started. Balance: {self.balance:.4f}")
        return True

    def _apply_runtime_api_keys(self, user_id: int, api_key: str, api_secret: str):
        # Apply to global config so _configure_live_client can find them if needed, 
        # but primarily we want them in the user scoped session.
        super()._apply_runtime_api_keys(user_id, api_key, api_secret)
        self._configure_live_client(user_id=user_id, notify=True)

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
        leverage = self._extract_price_field(raw_position, "leverageRr", "leverageEr", "leverage")
        resolved_leverage = int(leverage) if leverage and leverage > 0 else None
        margin_used = abs(entry_price * qty) / leverage if leverage and leverage > 0 else None
        open_time = int(time.time() * 1000)

        return Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=open_time,
            leverage=resolved_leverage,
            margin_used=margin_used,
            high_water=entry_price if direction == "long" else None,
            low_water=entry_price if direction == "short" else None,
        )

    def _set_scanner_position_flags(self, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        for scanner in target.long_scanners.values():
            scanner.has_position = False
        for scanner in target.short_scanners.values():
            scanner.has_position = False

        for symbol, position in target.positions.items():
            self._ensure_symbol_state(symbol, session=target)
            target.long_scanners[symbol].has_position = position.direction == "long"
            target.short_scanners[symbol].has_position = position.direction == "short"

    def _scan_market_candidates(self, session: Optional[SimulationSession] = None) -> list[dict[str, Any]]:
        target = session or self._global_session
        client = self.clients.get(target.user_id) if target.user_id else self.client
        if client is None:
            return []
        return super()._scan_market_candidates(session=target)

    def _refresh_balance(self, *, session: Optional[SimulationSession] = None, force: bool = False, candle_timestamp: Optional[int] = None) -> float:
        target = session or self._global_session
        client = self.clients.get(target.user_id) if target.user_id else self.client
        if client is None:
            return target.balance

        now = time.monotonic()
        if not force:
            # We use a shared monotonic tracker for global but per session should probably have its own if they are staggered.
            # For simplicity we use the session's internal state if we can or just global.
            if candle_timestamp is not None and candle_timestamp == self._last_balance_refresh_candle_ts:
                return target.balance
            if candle_timestamp is None and (now - self._last_balance_refresh_monotonic) < BALANCE_REFRESH_MIN_SECONDS:
                return target.balance

        try:
            current_balance = float(client.get_account())
        except Exception as exc:
            self.logger.warning(f"Failed to refresh live balance for {target.user_id or 'global'}: {exc}")
            return target.balance

        target.balance = current_balance
        target.reference_balance = max(target.reference_balance, current_balance)
        if session is None:
            self._last_balance_refresh_monotonic = now
            if candle_timestamp is not None:
                self._last_balance_refresh_candle_ts = candle_timestamp
        return current_balance

    def _max_daily_loss_exceeded(self, current_balance: Optional[float] = None, session: Optional[SimulationSession] = None) -> bool:
        target = session or self._global_session
        current = current_balance if current_balance is not None else target.balance
        reference_balance = max(target.reference_balance, current)
        max_daily_loss = float(self.config["risk"]["max_daily_loss"])
        return reference_balance > 0 and current < reference_balance * (1 - max_daily_loss)

    def _reconcile_positions_once(self, session: Optional[SimulationSession] = None, notify: bool = False):
        target = session or self._global_session
        client = self.clients.get(target.user_id) if target.user_id else self.client
        if client is None:
            return

        try:
            exchange_positions = client.get_positions()
        except Exception as exc:
            self.logger.warning(f"Failed to reconcile positions from Phemex for {target.user_id or 'global'}: {exc}")
            return

        previous_positions = dict(target.positions)
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
            self.db.remove_position(symbol, user_id=target.user_id)
            if notify:
                self.notifier.send_message(
                    f"⚠️ LIVE SYNC: `{symbol}` is no longer open on Phemex. Local state was updated to match the exchange.",
                    user_id=str(target.user_id) if target.user_id else None
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
                        "margin_used": position.margin_used,
                        "leverage": position.leverage,
                    },
                    user_id=target.user_id
                )

        target.positions = reconciled_positions
        self._set_scanner_position_flags(session=target)
        for symbol in set(reconciled_positions) - set(previous_positions):
            self._subscribe_symbol(symbol)

    def _sync_symbol_after_order(
        self,
        symbol: str,
        *,
        session: Optional[SimulationSession] = None,
        expected_direction: Optional[str] = None,
        fallback_price: Optional[float] = None,
        fallback_qty: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Position]:
        target = session or self._global_session
        for attempt in range(ORDER_SYNC_RETRIES):
            self._reconcile_positions_once(session=target, notify=False)
            position = target.positions.get(symbol)
            if position:
                if stop_loss is not None and not position.stop_loss:
                    position.stop_loss = stop_loss
                if take_profit is not None and not position.take_profit:
                    position.take_profit = take_profit
                if not position.leverage:
                    # Accessing attribute directly from Simulator's market_scan_settings resolver
                    # or the session's specific settings if we ever add them.
                    target_settings = self._settings_for_session(target)
                    position.leverage = int(target_settings.leverage)
                if position.margin_used is None and position.leverage:
                    position.margin_used = abs(position.entry_price * position.quantity) / max(float(position.leverage), 1.0)
                return position

            if expected_direction is None:
                break

            if attempt < ORDER_SYNC_RETRIES - 1:
                time.sleep(ORDER_SYNC_DELAY_SECONDS)

        if expected_direction is None:
            return None

        self.logger.warning(
            f"Order sync for {symbol} (User {target.user_id or 'global'}) never produced an exchange-confirmed {expected_direction} position. "
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
                for session in self._runtime_sessions():
                    self._refresh_balance(session=session, force=True)
                    self._reconcile_positions_once(session=session, notify=True)
            except Exception as exc:
                self.logger.error(f"Live reconciliation loop error: {exc}")

    async def _process_candle(self, symbol, candle):
        for session in self._runtime_sessions():
            if session.is_paused:
                continue

            self._refresh_balance(session=session, candle_timestamp=candle.timestamp)
            self._ensure_symbol_state(symbol, session=session)
            candle.symbol = symbol

            long_scanner = session.long_scanners[symbol]
            short_scanner = session.short_scanners[symbol]

            long_signal = long_scanner.update(candle)
            short_signal = short_scanner.update(candle)

            if symbol in session.positions:
                pos = session.positions[symbol]
                exit_price = None
                reason = None

                if pos.direction == "long" and long_signal and long_signal.direction is None:
                    exit_price = candle.close
                    reason = long_signal.exit_reason
                elif pos.direction == "short" and short_signal and short_signal.direction is None:
                    exit_price = candle.close
                    reason = short_signal.exit_reason

                if exit_price is not None:
                    self._execute_trade(symbol, pos.direction, exit_price, pos.quantity, is_entry=False, reason=reason, session=session)

                continue

            if self.use_market_scan_engine:
                continue

            if len(session.positions) >= self.config["risk"].get("max_positions", 1):
                continue

            signal = None
            if long_signal and long_signal.direction == "long":
                signal = long_signal
            elif short_signal and short_signal.direction == "short":
                signal = short_signal

            if not signal:
                continue

            stop_distance = abs(signal.entry_price - signal.stop_loss)
            quantity = calculate_position_size(
                session.balance,
                self.risk_per_trade,
                stop_distance,
                signal.entry_price,
            )
            if quantity <= 0:
                continue

            self._execute_trade(
                symbol,
                signal.direction,
                signal.entry_price,
                quantity,
                is_entry=True,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                session=session
            )

    async def _handle_command(self, cmd):
        command, args, chat_id, user_id = self._unpack_command(cmd)
        response = ""

        if command == "/shutdown":
            self.stop()
            response = "Engine shutting down..."
        elif command == "/emergency_stop":
            # For emergency stop in multi-user mode, we probably want to pause the specific user or all?
            # If triggered via bot it has a user_id.
            target_sessions = [self.get_user_session(user_id)] if user_id else self._runtime_sessions()
            
            cancelled_total = 0
            for session in target_sessions:
                if not session: continue
                session.is_paused = True
                client = self.clients.get(session.user_id) if session.user_id else self.client
                if client is not None:
                    for symbol in self.symbols:
                        try:
                            for order in client.get_open_orders(symbol) or []:
                                order_id = order.get("orderID") or order.get("orderId")
                                if not order_id:
                                    continue
                                client.cancel_order(symbol, order_id)
                                cancelled_total += 1
                        except Exception as exc:
                            self.logger.warning(f"Emergency stop failed to cancel open orders for {symbol} (User {session.user_id or 'global'}): {exc}")

                self._reconcile_positions_once(session=session, notify=False)

            response = f"EMERGENCY STOP TRIGGERED. Trading paused, {cancelled_total} open orders cancelled across targeted sessions."
        else:
            await super()._handle_command(cmd)
            return

        self._send_command_response(chat_id, response)

    def _execute_trade(self, symbol, direction, price, qty, is_entry, stop_loss=None, take_profit=None, reason=None, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        client = self.clients.get(target.user_id) if target.user_id else self.client
        
        if client is None:
            self.logger.warning(f"Live trade requested for {target.user_id or 'global'} before API vault was unlocked.")
            self.notifier.send_message(
                "🔐 Unlock the API vault with `/unlock_api <passphrase>` before live trading.",
                user_id=str(target.user_id) if target.user_id else None
            )
            return

        current_balance = self._refresh_balance(session=target, force=True)
        if self._max_daily_loss_exceeded(current_balance, session=target):
            self.logger.critical(f"Max daily loss exceeded for {target.user_id or 'global'}. Pausing session.")
            target.is_paused = True
            self.notifier.send_message(
                "🚨 Max daily loss exceeded. Your live session has been paused for safety.",
                user_id=str(target.user_id) if target.user_id else None
            )
            return

        side = "Buy" if direction == "long" else "Sell"
        if not is_entry:
            side = "Sell" if direction == "long" else "Buy"

        try:
            if is_entry:
                order = client.place_order(
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
                    session=target,
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
                    },
                    user_id=target.user_id
                )
                self.db.log_trade(entry_payload, user_id=target.user_id)
                self.db.update_position(
                    symbol,
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "entry_price": position.entry_price,
                        "qty": position.quantity,
                        "stop_loss": position.stop_loss,
                        "take_profit": position.take_profit,
                        "margin_used": position.margin_used,
                        "leverage": position.leverage,
                    },
                    user_id=target.user_id
                )
                self.notifier.send_message(
                    f"🔵 LIVE ENTRY: {symbol} {side} Qty: {position.quantity:.4f} @ {position.entry_price:.2f} "
                    f"Margin: ${float(position.margin_used or 0.0):.2f} @ {int(position.leverage or 0)}x",
                    user_id=str(target.user_id) if target.user_id else None
                )
                self.logger.info(f"Live entry {symbol} {direction} @ {position.entry_price} Qty: {position.quantity} (User {target.user_id or 'global'})")
            else:
                existing_position = target.positions.get(symbol)
                order = client.place_order(
                    symbol,
                    side,
                    qty,
                    reduce_only=True,
                )
                self._sync_symbol_after_order(symbol, session=target, expected_direction=None)
                remaining_position = target.positions.get(symbol)
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
                        },
                        user_id=target.user_id
                    )
                    self.db.log_trade(exit_payload, user_id=target.user_id)
                    self.db.remove_position(symbol, user_id=target.user_id)
                    self.notifier.send_message(
                        f"🔴 LIVE EXIT: {symbol} {side} Qty: {float(qty):.4f} @ {fill_price:.2f} Reason: {reason}",
                        user_id=str(target.user_id) if target.user_id else None
                    )
                    self.logger.info(f"Live exit {symbol} {direction} @ {fill_price} Qty: {qty} (User {target.user_id or 'global'})")
                    self._check_safety_timeout(session=target)
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
                            "margin_used": remaining_position.margin_used,
                            "leverage": remaining_position.leverage,
                        },
                        user_id=target.user_id
                    )
                    self.notifier.send_message(
                        f"🟠 LIVE EXIT SENT: {symbol} reduce-only {side} Qty: {float(qty):.4f}. Remaining size: {remaining_position.quantity:.4f}",
                        user_id=str(target.user_id) if target.user_id else None
                    )
        except Exception as exc:
            self.logger.error(f"Order Execution Failed for {target.user_id or 'global'}: {exc}")
            self.notifier.send_message(
                f"⚠️ Order Execution Failed: {exc}",
                user_id=str(target.user_id) if target.user_id else None
            )
        finally:
            self._refresh_balance(session=target, force=True)

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        await asyncio.gather(
            self._ws_handler(),
            self._command_listener(),
            self._market_scan_loop(),
            self._reconciliation_loop(),
        )
