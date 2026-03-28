from __future__ import annotations

import asyncio
import json
import queue
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from advanced_scanner.main import run_scan as advanced_run_scan
from strategy_profile import normalize_strategy_profile
from supabase_client import SupabaseManager

WS_PING_INTERVAL_SECONDS = 20
WS_PING_TIMEOUT_SECONDS = 60
SUBSCRIPTION_PAUSE_EVERY = 50
SUBSCRIPTION_PAUSE_SECONDS = 0.01


class BaseEngine(ABC):
    @abstractmethod
    def start(self):
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        raise NotImplementedError

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False
        if hasattr(self, "safety_paused_until"):
            self.safety_paused_until = 0

    @property
    @abstractmethod
    def positions(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def balance(self):
        raise NotImplementedError


@dataclass
class SimulationSession:
    user_id: Optional[int]
    balance: float
    reference_balance: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    trade_history: list[dict[str, Any]] = field(default_factory=list)
    safety_paused_until: float = 0.0
    is_paused: bool = False
    session_started_at: Optional[str] = None
    session_started_epoch: float = 0.0
    long_scanners: dict[str, Any] = field(default_factory=dict)
    short_scanners: dict[str, Any] = field(default_factory=dict)
    active_api_user_id: Optional[int] = None
    runtime_api_ready: bool = False
    runtime_api_key: Optional[str] = None
    runtime_api_secret: Optional[str] = None
    strategy_profile: dict[str, Any] = field(default_factory=dict)
    market_scan_settings: Any = None
    symbol_cooldowns: dict[str, int] = field(default_factory=dict)


class Simulator(BaseEngine):
    def __init__(self, config, notifier: TelegramNotifier, command_queue: queue.Queue):
        self.config = config
        self.notifier = notifier
        self.command_queue = command_queue
        self.logger = get_logger("Simulator")
        self.db = SupabaseManager(mode=str(config.get("mode", "production")))

        self.exchange_id = config.get("exchange", "phemex").lower()
        self.exchange = ExchangeManager(
            self.exchange_id,
            config.get("api_key"),
            config.get("api_secret"),
        )

        exchange_config = config.get(self.exchange_id, {})
        self.initial_balance = float(config["backtest"]["initial_balance"])
        self.risk_per_trade = config["risk"]["risk_per_trade"]
        self.fee_rate = config["backtest"]["fee_rate"]
        self.slippage = config["backtest"]["slippage"]
        self.symbols = config.get("symbols") or exchange_config.get("symbols", [])
        self.default_strategy_profile = normalize_strategy_profile(config)
        self.market_scan_settings = resolve_scan_settings(config, self.default_strategy_profile)

        self._user_scoped_simulation = str(config.get("mode") or "").strip().lower() in {"simulation", "live"}
        self._user_sessions: dict[int, SimulationSession] = {}
        self._global_session = self._build_session(user_id=None)
        self._latest_market_prices: dict[str, tuple[int, float]] = {}
        self._next_ws_request_id = 1

        self.is_running = True
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._websocket = None
        self._subscribed_symbols: set[str] = set()
        self.use_market_scan_engine = True

        ws_urls = {
            "phemex": "wss://ws.phemex.com",
        }
        self.ws_url = ws_urls.get(self.exchange_id, "")
        self._restore_persisted_sessions()

    @property
    def balance(self) -> float:
        return self._global_session.balance

    @balance.setter
    def balance(self, value: float):
        self._global_session.balance = float(value)

    @property
    def positions(self) -> dict[str, Position]:
        return self._global_session.positions

    @positions.setter
    def positions(self, value: dict[str, Position]):
        self._global_session.positions = dict(value)

    @property
    def trade_history(self) -> list[dict[str, Any]]:
        return self._global_session.trade_history

    @trade_history.setter
    def trade_history(self, value: list[dict[str, Any]]):
        self._global_session.trade_history = list(value)

    @property
    def safety_paused_until(self) -> float:
        return self._global_session.safety_paused_until

    @safety_paused_until.setter
    def safety_paused_until(self, value: float):
        self._global_session.safety_paused_until = float(value)

    @property
    def is_paused(self) -> bool:
        return self._global_session.is_paused

    @is_paused.setter
    def is_paused(self, value: bool):
        self._global_session.is_paused = bool(value)

    @property
    def session_started_at(self) -> Optional[str]:
        return self._global_session.session_started_at

    @session_started_at.setter
    def session_started_at(self, value: Optional[str]):
        self._global_session.session_started_at = value

    @property
    def session_started_epoch(self) -> float:
        return self._global_session.session_started_epoch

    @session_started_epoch.setter
    def session_started_epoch(self, value: float):
        self._global_session.session_started_epoch = float(value)

    @property
    def long_scanners(self) -> dict[str, LongScanner]:
        return self._global_session.long_scanners

    @long_scanners.setter
    def long_scanners(self, value: dict[str, LongScanner]):
        self._global_session.long_scanners = dict(value)

    @property
    def short_scanners(self) -> dict[str, ShortScanner]:
        return self._global_session.short_scanners

    @short_scanners.setter
    def short_scanners(self, value: dict[str, ShortScanner]):
        self._global_session.short_scanners = dict(value)


    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _build_session(self, user_id: Optional[int], *, start_new: bool = True) -> SimulationSession:
        session = SimulationSession(user_id=user_id, balance=self.initial_balance)
        stored_profile = self.db.get_user_strategy_config(user_id) if user_id is not None else None
        session.strategy_profile = normalize_strategy_profile(
            self.config,
            stored_profile or self.default_strategy_profile,
            current=self.default_strategy_profile,
        )
        session.market_scan_settings = resolve_scan_settings(self.config, session.strategy_profile)
        if start_new:
            self._start_new_session(session)
        return session

    def _timestamp_ms(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            numeric = int(value)
            return numeric * 1000 if numeric and abs(numeric) < 1_000_000_000_000 else numeric
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return 0

    def _timestamp_seconds(self, value: Any) -> float:
        milliseconds = self._timestamp_ms(value)
        return milliseconds / 1000 if milliseconds else 0.0

    def _optional_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _optional_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _session_state_payload(self, session: SimulationSession) -> Dict[str, Any]:
        return {
            "balance": float(session.balance),
            "reference_balance": float(session.reference_balance),
            "is_paused": bool(session.is_paused),
            "safety_paused_until": float(session.safety_paused_until or 0.0),
            "session_started_at": session.session_started_at,
            "session_started_epoch": float(session.session_started_epoch or 0.0),
            "symbol_cooldowns": {str(symbol): int(expires_at) for symbol, expires_at in session.symbol_cooldowns.items()},
        }

    def _persist_session_state(self, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        if target.user_id is None:
            return
        store_state = getattr(self.db, "store_user_simulation_state", None)
        if callable(store_state):
            store_state(int(target.user_id), self._session_state_payload(target))

    def _derive_balance_from_trades(self, trades: list[dict[str, Any]]) -> float:
        balance = float(self.initial_balance)
        for trade in trades:
            trade_type = str(trade.get("type") or "").strip().lower()
            if trade_type == "entry":
                try:
                    balance -= calculate_fee(float(trade.get("qty") or 0.0), float(trade.get("price") or 0.0), self.fee_rate)
                except (TypeError, ValueError):
                    continue
            elif trade_type == "exit":
                try:
                    balance += float(trade.get("pnl") or 0.0)
                except (TypeError, ValueError):
                    continue
        return balance

    def _restore_trade_history(self, user_id: int, session_started_at: Optional[str]) -> list[dict[str, Any]]:
        trades = self.db.get_recent_trades(limit=500, since=session_started_at, user_id=user_id)
        history = [dict(trade) for trade in trades if str(trade.get("type") or "").strip().lower() in {"entry", "exit"}]
        history.sort(key=lambda trade: self._timestamp_ms(trade.get("timestamp") or trade.get("created_at")))
        return history[-500:]

    def _restore_position(self, record: Dict[str, Any], trade_history: list[dict[str, Any]]) -> Optional[Position]:
        symbol = str(record.get("symbol") or "").strip()
        if not symbol:
            return None

        try:
            entry_price = float(record.get("entry_price") or 0.0)
            quantity = float(record.get("qty") if record.get("qty") is not None else record.get("quantity") or 0.0)
            stop_loss = float(record.get("stop_loss") or 0.0)
            take_profit = float(record.get("take_profit") or 0.0)
        except (TypeError, ValueError):
            return None

        matching_entries = [
            trade for trade in trade_history
            if trade.get("symbol") == symbol and str(trade.get("type") or "").strip().lower() == "entry"
        ]
        open_time = self._timestamp_ms(record.get("open_time") or record.get("entry_time"))
        if not open_time and matching_entries:
            open_time = self._timestamp_ms(matching_entries[-1].get("timestamp") or matching_entries[-1].get("created_at"))
        if not open_time:
            open_time = int(time.time() * 1000)

        position = Position(
            symbol=symbol,
            direction=str(record.get("direction") or "long"),
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=open_time,
            leverage=self._optional_int(record.get("leverage")),
            margin_used=self._optional_float(record.get("margin_used")),
            score=self._optional_int(record.get("score")),
            signals_count=self._optional_int(record.get("signals_count")),
            trail_pct=self._optional_float(record.get("trail_pct")),
            high_water=self._optional_float(record.get("high_water")),
            low_water=self._optional_float(record.get("low_water")),
            max_hold_candles=self._optional_int(record.get("max_hold_candles")),
        )
        if self._optional_float(record.get("mark_price")) is not None:
            position.mark_price = float(record.get("mark_price"))
        else:
            latest_price = self.get_latest_market_price(symbol)
            if latest_price is not None:
                position.mark_price = latest_price
        if self._optional_float(record.get("current_pnl")) is not None:
            position.current_pnl = float(record.get("current_pnl"))
        elif position.mark_price is not None:
            if position.direction == "short":
                position.current_pnl = (position.entry_price - position.mark_price) * position.quantity
            else:
                position.current_pnl = (position.mark_price - position.entry_price) * position.quantity
        if position.direction == "long" and position.high_water is None:
            position.high_water = position.entry_price
        if position.direction == "short" and position.low_water is None:
            position.low_water = position.entry_price
        return position

    def _restore_session(self, user_id: int) -> Optional[SimulationSession]:
        get_state = getattr(self.db, "get_user_simulation_state", None)
        state = get_state(user_id) if callable(get_state) else None
        session_started_at = str(state.get("session_started_at") or "").strip() if isinstance(state, dict) else ""
        trade_history = self._restore_trade_history(user_id, session_started_at or None)
        position_records = self.db.list_open_positions(user_id=user_id)
        if not state and not trade_history and not position_records:
            return None

        session = self._build_session(user_id, start_new=False)
        if isinstance(state, dict):
            try:
                session.balance = float(state.get("balance", self.initial_balance))
            except (TypeError, ValueError):
                session.balance = self._derive_balance_from_trades(trade_history)
            try:
                session.reference_balance = float(state.get("reference_balance", session.balance))
            except (TypeError, ValueError):
                session.reference_balance = float(session.balance)
            session.is_paused = bool(state.get("is_paused", False))
            try:
                session.safety_paused_until = float(state.get("safety_paused_until", 0.0) or 0.0)
            except (TypeError, ValueError):
                session.safety_paused_until = 0.0
            session.session_started_at = session_started_at or (trade_history[0].get("created_at") if trade_history else self._now_iso())
            try:
                session.session_started_epoch = float(
                    state.get("session_started_epoch") or self._timestamp_seconds(session.session_started_at)
                )
            except (TypeError, ValueError):
                session.session_started_epoch = self._timestamp_seconds(session.session_started_at) or time.time()
            raw_cooldowns = state.get("symbol_cooldowns") if isinstance(state.get("symbol_cooldowns"), dict) else {}
            session.symbol_cooldowns = {
                str(symbol): int(expires_at)
                for symbol, expires_at in raw_cooldowns.items()
                if expires_at is not None
            }
        else:
            session.balance = self._derive_balance_from_trades(trade_history)
            session.reference_balance = float(self.initial_balance)
            session.is_paused = False
            session.safety_paused_until = 0.0
            session.session_started_at = trade_history[0].get("created_at") if trade_history else self._now_iso()
            session.session_started_epoch = self._timestamp_seconds(session.session_started_at) or time.time()
            session.symbol_cooldowns = {}

        session.trade_history = trade_history
        session.positions = {}
        for record in position_records:
            position = self._restore_position(record, trade_history)
            if position is None:
                continue
            session.positions[position.symbol] = position

        self._persist_session_state(session)
        return session

    def _restore_persisted_sessions(self):
        if not self._user_scoped_simulation:
            return

        candidate_user_ids = set()
        list_state_users = getattr(self.db, "list_user_ids_with_simulation_state", None)
        if callable(list_state_users):
            candidate_user_ids.update(int(user_id) for user_id in list_state_users())

        for record in self.db.list_open_positions():
            user_id = self._normalize_user_id(record.get("user_id"))
            if user_id:
                candidate_user_ids.add(user_id)

        restored = 0
        for user_id in sorted(candidate_user_ids):
            session = self._restore_session(user_id)
            if session is None:
                continue
            self._user_sessions[user_id] = session
            restored += 1

        if restored:
            self.logger.info(f"Restored {restored} persisted simulation session(s).")

    def _settings_for_session(self, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        return getattr(target, "market_scan_settings", None) or self.market_scan_settings

    def get_strategy_config(self, user_id: Optional[int] = None) -> dict[str, Any]:
        if self._user_scoped_simulation and user_id is not None:
            session = self.get_user_session(user_id, create=True)
            if session is not None and session.strategy_profile:
                return normalize_strategy_profile(self.config, {}, current=session.strategy_profile)

        session = self._global_session
            if not self.use_market_scan_engine or target.is_paused:
                return []

            scanner_type = self.config.get("scanner", "standard").lower()
            settings = self._settings_for_session(target)
            max_positions = int(self.config["risk"].get("max_positions", 1))
            available_slots = max_positions - len(target.positions)
            if available_slots <= 0:
                return []
            if target.balance < settings.margin_usdt:
                return []
            locked_margin = sum(float(getattr(position, "margin_used", 0.0) or 0.0) for position in target.positions.values())
            if locked_margin + settings.margin_usdt > settings.max_margin_usdt:
                return []

            now_ms = int(time.time() * 1000)
            expired = [symbol for symbol, expires_at in target.symbol_cooldowns.items() if int(expires_at or 0) <= now_ms]
            for symbol in expired:
                target.symbol_cooldowns.pop(symbol, None)

            plans: list[dict[str, Any]] = []
            if scanner_type == "advanced":
                # Use advanced scanner for candidate selection
                # Example: advanced_run_scan returns sorted_assets: [(symbol, info_dict), ...]
                # You may want to map info_dict to your plan format as needed
                funds = {}  # TODO: Provide actual funds mapping if needed
                syms = list(settings.symbols) if hasattr(settings, "symbols") else []
                results = advanced_run_scan(syms, funds)
                for sym, info in results:
                    if info["side"] == "neutral":
                        continue
                    plan = {"symbol": sym, "direction": info["side"], "score": info["score"]}
                    if plan["symbol"] in target.symbol_cooldowns:
                        continue
                    plans.append(plan)
                return plans
            else:
                candidates = run_market_scan(
                    settings,
                    in_position=set(target.positions.keys()),
                    available_slots=available_slots,
                )
                for result, direction in candidates:
                    plan = build_entry_plan(result, direction, settings)
                    if not plan or not plan.get("symbol"):
                        continue
                    if plan["symbol"] in target.symbol_cooldowns:
                        continue
                    plans.append(plan)
                return plans
    def get_user_session(self, user_id: Optional[int], *, create: bool = False) -> Optional[SimulationSession]:
        normalized_user_id = self._normalize_user_id(user_id)
        if not self._user_scoped_simulation or normalized_user_id is None:
            return self._global_session

        session = self._user_sessions.get(normalized_user_id)
        if session is None:
            session = self._restore_session(normalized_user_id)
            if session is not None:
                self._user_sessions[normalized_user_id] = session
        if session is None and create:
            session = self._build_session(normalized_user_id)
            self._user_sessions[normalized_user_id] = session
        return session

    def list_user_sessions(self) -> list[SimulationSession]:
        if not self._user_scoped_simulation:
            return [self._global_session]
        return list(self._user_sessions.values())

    def _runtime_sessions(self) -> list[SimulationSession]:
        if not self._user_scoped_simulation:
            return [self._global_session]
        return list(self._user_sessions.values())

    def _start_new_session(self, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        target.session_started_at = self._now_iso()
        target.session_started_epoch = time.time()
        target.reference_balance = float(target.balance)
        self._persist_session_state(target)

    def _record_trade_event(
        self,
        trade_data: Dict[str, Any],
        session: Optional[SimulationSession] = None,
    ) -> Dict[str, Any]:
        target = session or self._global_session
        payload = dict(trade_data)
        payload.setdefault("timestamp", int(time.time() * 1000))
        payload.setdefault("created_at", self._now_iso())
        if target.user_id is not None:
            payload.setdefault("user_id", target.user_id)
        target.trade_history.append(payload)
        if len(target.trade_history) > 500:
            target.trade_history = target.trade_history[-500:]
        return payload

    def _runtime_api_ready(self, session: Optional[SimulationSession] = None) -> bool:
        if self._user_scoped_simulation and session is not None:
            return bool(session.runtime_api_ready)

        api_key = self.config.get(self.exchange_id, {}).get("api_key") or self.config.get("api_key")
        api_secret = self.config.get(self.exchange_id, {}).get("api_secret") or self.config.get("api_secret")
        return bool(api_key and api_secret and api_key != "YOUR_API_KEY" and api_secret != "YOUR_API_SECRET")

    def _apply_runtime_api_keys(self, user_id: int, api_key: str, api_secret: str):
        if self._user_scoped_simulation:
            session = self.get_user_session(user_id, create=True)
            if session is not None:
                session.active_api_user_id = user_id
                session.runtime_api_ready = True
                session.runtime_api_key = api_key
                session.runtime_api_secret = api_secret
            return

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
                recorder = getattr(self.notifier, "record_message", None)
                if callable(recorder):
                    recorder(text, source="command")
                return
            except Exception as exc:
                self.logger.warning(f"Failed to send direct command response to chat {chat_id}: {exc}")

        self.notifier.send_message(text)

    def _ensure_symbol_state(self, symbol: str, *, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        scanner_type = self.config.get("scanner", "standard").lower()
        if scanner_type == "advanced":
            # Use advanced scanner wrappers (stateless, so just a marker)
            if symbol not in target.long_scanners:
                target.long_scanners[symbol] = "advanced"
            if symbol not in target.short_scanners:
                target.short_scanners[symbol] = "advanced"
        else:
            if symbol not in target.long_scanners:
                target.long_scanners[symbol] = LongScanner(self.config)
            if symbol not in target.short_scanners:
                target.short_scanners[symbol] = ShortScanner(self.config)

    def _subscribe_payload(self, symbol: str) -> dict[str, Any]:
        return {
            "id": self._next_request_id(),
            "method": "kline.subscribe",
            "params": [symbol, 60],
        }

    def _market_price_subscribe_payload(self, symbol: str) -> dict[str, Any]:
        return {
            "id": self._next_request_id(),
            "method": "market24h_p.subscribe",
            "params": [symbol],
        }

    def _next_request_id(self) -> int:
        request_id = self._next_ws_request_id
        self._next_ws_request_id += 1
        return request_id

    def _update_position_marks(self, symbol: str, current_price: float, timestamp_ms: Optional[int] = None):
        normalized_price = float(current_price)
        stamp = int(timestamp_ms or time.time() * 1000)
        self._latest_market_prices[symbol] = (stamp, normalized_price)

        for session in self._runtime_sessions():
            position = session.positions.get(symbol)
            if position is None:
                continue

            position.mark_price = normalized_price
            if position.direction == "short":
                position.current_pnl = (position.entry_price - normalized_price) * position.quantity
            else:
                position.current_pnl = (normalized_price - position.entry_price) * position.quantity

    def _subscribe_symbol(self, symbol: str):
        if not symbol or symbol in self._subscribed_symbols:
            return

        self._ensure_symbol_state(symbol)
        self._subscribed_symbols.add(symbol)
        if self._websocket and self._loop and self._loop.is_running():

            async def _send():
                for payload in (self._subscribe_payload(symbol), self._market_price_subscribe_payload(symbol)):
                    await self._websocket.send(json.dumps(payload))

            try:
                asyncio.run_coroutine_threadsafe(_send(), self._loop)
            except RuntimeError:
                pass

    def _scan_market_candidates(self, session: Optional[SimulationSession] = None) -> list[dict[str, Any]]:
        target = session or self._global_session
        if not self.use_market_scan_engine or target.is_paused:
            return []

        settings = self._settings_for_session(target)
        max_positions = int(self.config["risk"].get("max_positions", 1))
        available_slots = max_positions - len(target.positions)
        if available_slots <= 0:
            return []
        if target.balance < settings.margin_usdt:
            return []
        locked_margin = sum(float(getattr(position, "margin_used", 0.0) or 0.0) for position in target.positions.values())
        if locked_margin + settings.margin_usdt > settings.max_margin_usdt:
            return []

        now_ms = int(time.time() * 1000)
        expired = [symbol for symbol, expires_at in target.symbol_cooldowns.items() if int(expires_at or 0) <= now_ms]
        for symbol in expired:
            target.symbol_cooldowns.pop(symbol, None)

        candidates = run_market_scan(
            settings,
            in_position=set(target.positions.keys()),
            available_slots=available_slots,
        )
        plans: list[dict[str, Any]] = []
        for result, direction in candidates:
            plan = build_entry_plan(result, direction, settings)
            if not plan or not plan.get("symbol"):
                continue
            if plan["symbol"] in target.symbol_cooldowns:
                continue
            if locked_margin + float(plan.get("margin_used") or settings.margin_usdt) > settings.max_margin_usdt:
                continue
            locked_margin += float(plan.get("margin_used") or settings.margin_usdt)
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

    def _tracked_symbols(self) -> set[str]:
        if not self._user_scoped_simulation:
            return set(self.positions.keys())

        tracked: set[str] = set()
        for session in self._runtime_sessions():
            tracked.update(session.positions.keys())
        return tracked

    def get_latest_market_price(self, symbol: str) -> Optional[float]:
        latest = self._latest_market_prices.get(symbol)
        if latest is None:
            return None
        return float(latest[1])

    async def _subscribe(self, websocket):
        symbols = sorted(self._tracked_symbols()) if self.use_market_scan_engine else list(self.symbols)
        self._subscribed_symbols = set()

        for index, symbol in enumerate(symbols, start=1):
            for subscribe_msg in (self._subscribe_payload(symbol), self._market_price_subscribe_payload(symbol)):
                await websocket.send(json.dumps(subscribe_msg))
            self._subscribed_symbols.add(symbol)
            if index % SUBSCRIPTION_PAUSE_EVERY == 0:
                await asyncio.sleep(SUBSCRIPTION_PAUSE_SECONDS)
            self.logger.debug(f"Subscribed to {symbol}")

    def _extract_market_price(self, data: Dict[str, Any]) -> Optional[tuple[str, float]]:
        tick = data.get("market24h_p")
        if not isinstance(tick, dict):
            return None

        symbol = tick.get("symbol")
        price = tick.get("closeRp")
        if price is None:
            price = tick.get("lastRp")
        if not symbol or price is None:
            return None

        try:
            return str(symbol), float(price)
        except (TypeError, ValueError):
            return None

    async def _handle_ws_message(self, data: Dict[str, Any]):
        market_price = self._extract_market_price(data)
        if market_price is not None:
            symbol, price = market_price
            self._update_position_marks(symbol, price)

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

    async def _process_candle_for_session(self, session: SimulationSession, symbol: str, candle: Candle):
        if session.is_paused:
            return

        settings = self._settings_for_session(session)
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

            if pos.direction == "long":
                pos.high_water = max(float(pos.high_water or pos.entry_price), float(candle.high))
                if float(pos.trail_pct or 0.0) > 0 and pos.high_water > 0:
                    trailed_stop = pos.high_water * (1.0 - float(pos.trail_pct))
                    pos.stop_loss = max(float(pos.stop_loss or trailed_stop), trailed_stop)
            elif pos.direction == "short":
                current_low = float(candle.low)
                existing_low = float(pos.low_water or pos.entry_price)
                pos.low_water = min(existing_low, current_low)
                if float(pos.trail_pct or 0.0) > 0 and pos.low_water > 0:
                    trailed_stop = pos.low_water * (1.0 + float(pos.trail_pct))
                    pos.stop_loss = min(float(pos.stop_loss or trailed_stop), trailed_stop)

            if (
                exit_price is None
                and int(pos.max_hold_candles or 0) > 0
                and int(candle.timestamp) - int(pos.open_time) >= int(pos.max_hold_candles) * int(settings.candle_seconds) * 1000
            ):
                exit_price = candle.close
                reason = "Max Hold"

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
                self._execute_trade_for_session(
                    session,
                    symbol,
                    pos.direction,
                    exit_price,
                    pos.quantity,
                    is_entry=False,
                    reason=reason,
                )
                if pos.direction == "long":
                    long_scanner.has_position = False
                if pos.direction == "short":
                    short_scanner.has_position = False
            return

        if self.use_market_scan_engine:
            return

        if len(session.positions) >= self.config["risk"].get("max_positions", 1):
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
            session.balance,
            self.risk_per_trade,
            stop_distance,
            signal.entry_price,
        )
        if quantity <= 0:
            return

        self._execute_trade_for_session(
            session,
            symbol,
            signal.direction,
            signal.entry_price,
            quantity,
            is_entry=True,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

    async def _process_candle(self, symbol: str, candle: Candle):
        sessions = self._runtime_sessions()
        if not sessions:
            return

        self._update_position_marks(symbol, float(candle.close), timestamp_ms=int(candle.timestamp))

        for session in sessions:
            await self._process_candle_for_session(session, symbol, candle)

    async def _market_scan_loop(self):
        if not self.use_market_scan_engine:
            return

        await asyncio.sleep(1.0)
        while self.is_running:
            try:
                sessions = self._runtime_sessions()
                for session in sessions:
                    if not self.is_running or session.is_paused:
                        continue

                    # Periodic membership check: enforcement during runtime.
                    if session.user_id:
                        mode = str(self.config.get("mode") or "simulation").strip().lower()
                        if not self.db.user_can_access_mode(session.user_id, mode):
                            self.logger.warning(
                                f"User {session.user_id} does not have active paid access for {mode}. Pausing session."
                            )
                            session.is_paused = True
                            self.notifier.send_message(
                                "🔒 *Membership Expired or Unverified*\n\n"
                                f"Your active {mode} session has been paused because a paid membership is required.\n\n"
                                "Please verify your email or subscribe to continue.",
                                user_id=str(session.user_id),
                            )
                            continue

                    plans = await asyncio.to_thread(self._scan_market_candidates, session)
                    for plan in plans:
                        if not self.is_running or session.is_paused:
                            break
                        if plan["symbol"] in session.positions:
                            continue
                        if len(session.positions) >= self.config["risk"].get("max_positions", 1):
                            break
                        self._execute_trade_for_session(
                            session,
                            plan["symbol"],
                            plan["direction"],
                            plan["price"],
                            plan["quantity"],
                            is_entry=True,
                            stop_loss=plan["stop_loss"],
                            take_profit=plan["take_profit"],
                            leverage=plan.get("leverage"),
                            margin_used=plan.get("margin_used"),
                            score=plan.get("score"),
                            signals_count=plan.get("signals_count"),
                            trail_pct=plan.get("trail_pct"),
                            max_hold_candles=plan.get("max_hold_candles"),
                        )
            except Exception as exc:
                self.logger.error(f"Market scan loop error: {exc}")

            runtime_settings = [self._settings_for_session(session) for session in self._runtime_sessions()]
            sleep_seconds = max(5, min((int(settings.interval_seconds) for settings in runtime_settings), default=int(self.market_scan_settings.interval_seconds)))
            for _ in range(sleep_seconds):
                if not self.is_running:
                    return
                await asyncio.sleep(1)

    def _check_safety_timeout(self, session: Optional[SimulationSession] = None):
        target = session or self._global_session
        if target.is_paused:
            return

        consecutive_losses = 0
        for trade in reversed(target.trade_history):
            if trade["pnl"] < 0:
                consecutive_losses += 1
            else:
                break

        max_losses = self.config["safety"]["max_consecutive_losses"]
        if consecutive_losses < max_losses:
            return

        target.is_paused = True
        target.safety_paused_until = time.time() + (self.config["safety"]["timeout_duration_minutes"] * 60)
        msg = (
            "🛡️ *SAFETY TIMEOUT TRIGGERED*\n\n"
            f"Reason: {consecutive_losses} consecutive losses.\n"
            f"Trading paused for {self.config['safety']['timeout_duration_minutes']} minutes."
        )
        self.notifier.send_message(msg, user_id=target.user_id)
        self.logger.warning(
            f"Safety timeout triggered for user {target.user_id or 'global'}: {consecutive_losses} losses."
        )
        self._persist_session_state(target)

    def _execute_trade(
        self,
        symbol,
        direction,
        price,
        qty,
        is_entry,
        stop_loss=None,
        take_profit=None,
        reason=None,
    ):
        return self._execute_trade_for_session(
            self._global_session,
            symbol,
            direction,
            price,
            qty,
            is_entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason,
        )

    def _execute_trade_for_session(
        self,
        session: SimulationSession,
        symbol,
        direction,
        price,
        qty,
        is_entry,
        stop_loss=None,
        take_profit=None,
        reason=None,
        leverage: Optional[int] = None,
        margin_used: Optional[float] = None,
        score: Optional[int] = None,
        signals_count: Optional[int] = None,
        trail_pct: Optional[float] = None,
        max_hold_candles: Optional[int] = None,
    ):
        adjusted_direction = direction if is_entry else ("short" if direction == "long" else "long")
        adjusted_price = apply_slippage(price, self.slippage, adjusted_direction)
        fee = calculate_fee(qty, adjusted_price, self.fee_rate)
        notify_user_id = session.user_id
        settings = self._settings_for_session(session)

        if is_entry:
            session.balance -= fee
            resolved_margin = float(margin_used if margin_used is not None else settings.margin_usdt)
            resolved_leverage = int(leverage if leverage is not None else settings.leverage)
            position = Position(
                symbol,
                direction,
                adjusted_price,
                qty,
                stop_loss,
                take_profit,
                int(time.time() * 1000),
                leverage=resolved_leverage,
                margin_used=resolved_margin,
                score=score,
                signals_count=signals_count,
                trail_pct=float(trail_pct if trail_pct is not None else settings.trail_pct),
                high_water=adjusted_price if direction == "long" else None,
                low_water=adjusted_price if direction == "short" else None,
                max_hold_candles=int(max_hold_candles if max_hold_candles is not None else settings.max_hold_candles),
            )
            position.mark_price = adjusted_price
            position.current_pnl = 0.0
            session.positions[symbol] = position
            self._subscribe_symbol(symbol)
            self._update_position_marks(symbol, adjusted_price)

            entry_payload = self._record_trade_event(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "price": adjusted_price,
                    "qty": qty,
                    "type": "entry",
                    "margin_used": resolved_margin,
                    "leverage": resolved_leverage,
                    "score": score,
                    "signals_count": signals_count,
                },
                session=session,
            )
            self.db.log_trade(entry_payload, user_id=session.user_id)
            self.db.update_position(
                symbol,
                {
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": adjusted_price,
                    "qty": qty,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "open_time": position.open_time,
                    "margin_used": resolved_margin,
                    "leverage": resolved_leverage,
                    "score": score,
                    "signals_count": signals_count,
                    "trail_pct": position.trail_pct,
                    "high_water": position.high_water,
                    "low_water": position.low_water,
                    "max_hold_candles": position.max_hold_candles,
                    "mark_price": position.mark_price,
                    "current_pnl": position.current_pnl,
                },
                user_id=session.user_id,
            )
            self._persist_session_state(session)

            self.notifier.send_message(
                f"🔵 SIM ENTRY: {direction.upper()} {symbol} @ {adjusted_price:.2f} Qty: {qty:.4f} "
                f"Margin: ${resolved_margin:.2f} @ {resolved_leverage}x",
                user_id=notify_user_id,
            )
            self.logger.info(f"Entry {symbol} {direction} @ {adjusted_price} for user {session.user_id or 'global'}")
            return

        position = session.positions[symbol]
        if direction == "long":
            pnl = (adjusted_price - position.entry_price) * qty
        else:
            pnl = (position.entry_price - adjusted_price) * qty

        pnl -= fee
        session.balance += pnl

        exit_payload = self._record_trade_event(
            {
                "symbol": symbol,
                "direction": direction,
                "price": adjusted_price,
                "qty": qty,
                "type": "exit",
                "pnl": pnl,
                "reason": reason,
            },
            session=session,
        )
        self.db.log_trade(exit_payload, user_id=session.user_id)
        self.db.remove_position(symbol, user_id=session.user_id)

        del session.positions[symbol]
        if int(settings.cooldown_candles or 0) > 0:
            session.symbol_cooldowns[symbol] = int(time.time() * 1000) + (int(settings.cooldown_candles) * int(settings.candle_seconds) * 1000)
        self._persist_session_state(session)
        self.notifier.send_message(
            f"🔴 SIM EXIT: {direction.upper()} {symbol} @ {adjusted_price:.2f} PnL: {pnl:.2f} Reason: {reason}",
            user_id=notify_user_id,
        )
        self.logger.info(f"Exit {symbol} {direction} @ {adjusted_price} PnL: {pnl} for user {session.user_id or 'global'}")
        self._check_safety_timeout(session)

    def _positions_summary_text(self, session: Optional[SimulationSession] = None) -> str:
        target = session or self._global_session
        if not target.positions:
            return "No open positions right now."

        lines = ["Open Positions:"]
        for symbol, position in target.positions.items():
            lines.append(
                f"{symbol}: {position.direction.upper()} | Entry {position.entry_price:.4f} | "
                f"Qty {position.quantity:.4f} | Margin ${float(position.margin_used or 0.0):.2f} | "
                f"Lev {int(position.leverage or 0)}x | SL {position.stop_loss:.4f} | TP {position.take_profit:.4f}"
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

    def _unpack_command(self, cmd) -> tuple[str, list[str], Optional[int], Optional[int]]:
        if not isinstance(cmd, (list, tuple)):
            raise ValueError("Unsupported command payload.")

        if len(cmd) == 4:
            command, args, chat_id, user_id = cmd
            return command, list(args or []), chat_id, self._normalize_user_id(user_id, chat_id)

        if len(cmd) == 3:
            command, args, chat_id = cmd
            return command, list(args or []), chat_id, self._normalize_user_id(None, chat_id)

        raise ValueError("Unsupported command payload.")

    def _reset_session(self, session: SimulationSession):
        session.balance = self.initial_balance
        session.positions = {}
        session.trade_history = []
        session.symbol_cooldowns = {}
        session.is_paused = False
        session.safety_paused_until = 0.0
        self._start_new_session(session)
        for scanner in session.long_scanners.values():
            scanner.reset()
        for scanner in session.short_scanners.values():
            scanner.reset()

    async def _handle_command(self, cmd):
        command, args, chat_id, user_id = self._unpack_command(cmd)
        response = ""
        session = self.get_user_session(user_id, create=self._user_scoped_simulation)

        if command == "/status":
            target = session or self._global_session
            response = (
                f"Balance: {target.balance:.2f}\n"
                f"Open Positions: {len(target.positions)}\n"
                f"Paused: {target.is_paused}\n"
                f"API Vault Unlocked: {self._runtime_api_ready(target)}"
            )
        elif command == "/positions":
            response = self._positions_summary_text(session)
        elif command == "/pause":
            target = session or self._global_session
            target.is_paused = True
            self._persist_session_state(target)
            response = "Simulation paused."
        elif command == "/resume":
            target = session or self._global_session
            now = time.time()
            if now < target.safety_paused_until:
                remaining = int((target.safety_paused_until - now) / 60)
                response = f"⚠️ Still in Safety Timeout. {remaining} minutes remaining."
            else:
                target.is_paused = False
                target.safety_paused_until = 0
                self._persist_session_state(target)
                response = "Simulation resumed."
        elif command == "/reset":
            self._reset_session(session or self._global_session)
            response = "Simulation reset."
        elif command == "/set_balance":
            target = session or self._global_session
            if args:
                try:
                    target.balance = float(args[0])
                    target.reference_balance = float(target.balance)
                    self._persist_session_state(target)
                    response = f"Balance set to {target.balance}"
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
                    target_user_id = int(args[0])
                except ValueError:
                    response = "Invalid user ID for vault unlock."
                else:
                    passphrase = " ".join(args[1:])
                    credentials = self.db.get_user_api_keys(
                        target_user_id,
                        passphrase=passphrase,
                        exchange=self.exchange_id,
                    )
                    if not credentials:
                        response = "Could not unlock the API vault. Check your passphrase and stored keys."
                    else:
                        self._apply_runtime_api_keys(
                            target_user_id,
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
