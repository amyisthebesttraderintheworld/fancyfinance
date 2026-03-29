from __future__ import annotations

import asyncio
import inspect
import os
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backtest_service import ALLOWED_REMOTE_CANDLE_COUNTS, BacktestServiceError, run_backtest, run_backtest_recent, run_backtest_recent_universe
from common import get_logger
from dashboard_access import (
    DEFAULT_TOKEN_TTL_SECONDS,
    DashboardAccessError,
    generate_member_dashboard_token,
    verify_member_dashboard_token,
    verify_telegram_login_payload,
)
from dashboard_ui import build_dashboard_html, build_login_html
from fancyfinance import APP_NAME, __version__
from stripe_service import StripeService
from strategy_profile import normalize_strategy_profile


DASHBOARD_ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"
DASHBOARD_LOGO_PATH = DASHBOARD_ASSETS_DIR / "logo.png"
LANDING_DIR = Path(__file__).resolve().parent / "landing"
LANDING_PUBLIC_DIR = LANDING_DIR / "public"
LANDING_DIST_DIR = LANDING_DIR / "dist"
PRIVACY_POLICY_PATH = LANDING_DIST_DIR / "privacy-policy.html"
TERMS_OF_USE_PATH = LANDING_DIST_DIR / "terms-of-use.html"
MEMBER_ACCESS_COOKIE = "fancyfinance_member_access"
logger = get_logger("API")


@lru_cache(maxsize=8)
def _telegram_bot_username_from_token(bot_token: str) -> str:
    normalized_token = str(bot_token or "").strip()
    if not normalized_token:
        return ""

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{normalized_token}/getMe",
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(f"Could not resolve Telegram bot username for dashboard login: {exc}")
        return ""

    result = payload.get("result") or {}
    return str(result.get("username") or "").strip()


def _telegram_login_context(config: Dict[str, Any], auth_token: Optional[str]) -> Dict[str, Any]:
    telegram_config = (config or {}).get("telegram", {})
    bot_token = str(telegram_config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    bot_username = str(telegram_config.get("bot_username") or os.getenv("TELEGRAM_BOT_USERNAME") or "").strip()
    if not bot_username and bot_token:
        bot_username = _telegram_bot_username_from_token(bot_token)

    enabled = bool(bot_token and bot_username)
    return {
        "enabled": enabled,
        "bot_token": bot_token,
        "bot_username": bot_username,
        "bot_url": f"https://t.me/{bot_username}" if bot_username else "https://t.me",
        "auth_url": "/dashboard/login/telegram",
    }


def _authorize(expected_token: Optional[str], provided_token: Optional[str]):
    if expected_token and provided_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _authorize_member_dashboard(expected_token: Optional[str], provided_token: Optional[str]) -> int:
    if not expected_token:
        raise HTTPException(status_code=503, detail="Dashboard access is not configured")
    try:
        payload = verify_member_dashboard_token(expected_token, provided_token or "")
    except DashboardAccessError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return int(payload["sub"])


def _authorize_dashboard_request(expected_token: Optional[str], provided_token: Optional[str]) -> Optional[int]:
    if not expected_token:
        raise HTTPException(status_code=401, detail="Dashboard access is not configured")
    if not provided_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if provided_token == expected_token:
        return None

    try:
        payload = verify_member_dashboard_token(expected_token, provided_token)
    except DashboardAccessError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return int(payload["sub"])


def _resolve_dashboard_token(
    request: Optional[Request],
    provided_token: Optional[str] = None,
    access: Optional[str] = None,
) -> Optional[str]:
    for candidate in (
        provided_token,
        access,
        request.cookies.get(MEMBER_ACCESS_COOKIE) if request is not None else None,
    ):
        if candidate:
            return candidate
    return None


def _member_access_cookie_secure(request: Optional[Request]) -> bool:
    if request is None:
        return False
    return request.url.scheme == "https"


def _apply_no_store(
    response,
    *,
    private: bool = False,
    vary_cookie: bool = False,
):
    directives = ["no-store", "max-age=0", "must-revalidate"]
    if private:
        directives.insert(0, "private")
    response.headers["Cache-Control"] = ", ".join(directives)
    response.headers["Pragma"] = "no-cache"
    if vary_cookie:
        existing_vary = str(response.headers.get("Vary") or "").strip()
        vary_values = [value.strip() for value in existing_vary.split(",") if value.strip()]
        if "Cookie" not in vary_values:
            vary_values.append("Cookie")
        response.headers["Vary"] = ", ".join(vary_values)
    return response


def _first_existing_path(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _invoke_with_supported_kwargs(func, *args, **kwargs):
    parameters = inspect.signature(func).parameters
    supported = {key: value for key, value in kwargs.items() if key in parameters}
    return func(*args, **supported)


def _uses_user_sessions(engine) -> bool:
    return bool(getattr(engine, "_user_scoped_simulation", False))


def _get_user_session(engine, user_id: Optional[int], *, create: bool = False):
    getter = getattr(engine, "get_user_session", None)
    if callable(getter):
        return getter(user_id, create=create)
    return None


def _list_user_sessions(engine) -> list[Any]:
    getter = getattr(engine, "list_user_sessions", None)
    if callable(getter):
        return list(getter())
    return []


def _latest_scanner_close(scanners: Any, symbol: str) -> Optional[tuple[int, float]]:
    if not isinstance(scanners, dict):
        return None

    scanner = scanners.get(symbol)
    candles = getattr(scanner, "candles", None) or []
    if not candles:
        return None

    latest = candles[-1]
    if isinstance(latest, dict):
        timestamp = int(_coerce_float(latest.get("timestamp")) or 0)
        close = _coerce_float(latest.get("close"))
    else:
        timestamp = int(_coerce_float(getattr(latest, "timestamp", None)) or 0)
        close = _coerce_float(getattr(latest, "close", None))

    if close is None or close <= 0:
        return None
    return timestamp, close


def _position_mark_price(engine, symbol: str, user_id: Optional[int] = None) -> Optional[float]:
    latest_price_getter = getattr(engine, "get_latest_market_price", None)
    if callable(latest_price_getter):
        latest_price = _coerce_float(latest_price_getter(symbol))
        if latest_price is not None and latest_price > 0:
            return latest_price

    latest_prices = getattr(engine, "_latest_market_prices", None)
    if isinstance(latest_prices, dict):
        latest = latest_prices.get(symbol)
        if isinstance(latest, (list, tuple)) and len(latest) >= 2:
            latest_price = _coerce_float(latest[1])
        else:
            latest_price = _coerce_float(latest)
        if latest_price is not None and latest_price > 0:
            return latest_price

    candidates: list[tuple[int, float]] = []
    if _uses_user_sessions(engine):
        session = _get_user_session(engine, user_id, create=True) if user_id is not None else None
        if session is None:
            return None
        for scanner_map in (getattr(session, "long_scanners", None), getattr(session, "short_scanners", None)):
            latest = _latest_scanner_close(scanner_map, symbol)
            if latest is not None:
                candidates.append(latest)
    else:
        for scanner_map in (getattr(engine, "long_scanners", None), getattr(engine, "short_scanners", None)):
            latest = _latest_scanner_close(scanner_map, symbol)
            if latest is not None:
                candidates.append(latest)

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _position_unrealized_pnl(position: Dict[str, Any]) -> Optional[float]:
    direct_pnl = _coerce_float(position.get("current_pnl", position.get("pnl")))
    if direct_pnl is not None:
        return direct_pnl

    entry = _coerce_float(position.get("entry_price"))
    quantity = _coerce_float(position.get("quantity"))
    mark = _coerce_float(position.get("mark_price"))
    direction = str(position.get("direction") or "").strip().lower()
    if entry is None or quantity is None or mark is None:
        return None
    if direction == "short":
        return (entry - mark) * quantity
    return (mark - entry) * quantity


def _portfolio_summary(snapshot: Dict[str, Any], positions: list[Dict[str, Any]]) -> Dict[str, Any]:
    balance = _coerce_float(snapshot.get("balance"))
    reference_balance = _coerce_float(snapshot.get("reference_balance"))
    marked_positions = 0
    winning_positions = 0
    losing_positions = 0
    live_upnl = 0.0
    notional_exposure = 0.0

    for position in positions:
        entry = _coerce_float(position.get("entry_price"))
        quantity = _coerce_float(position.get("quantity"))
        if entry is not None and quantity is not None:
            notional_exposure += abs(entry * quantity)

        pnl = _position_unrealized_pnl(position)
        if pnl is None:
            continue
        marked_positions += 1
        live_upnl += pnl
        if pnl > 0:
            winning_positions += 1
        elif pnl < 0:
            losing_positions += 1

    return {
        "balance": balance,
        "reference_balance": reference_balance,
        "live_upnl": round(live_upnl, 4),
        "marked_equity": round(balance + live_upnl, 4) if balance is not None else None,
        "session_delta": round((balance + live_upnl) - reference_balance, 4)
        if balance is not None and reference_balance is not None
        else None,
        "notional_exposure": round(notional_exposure, 4),
        "marked_positions": marked_positions,
        "winning_positions": winning_positions,
        "losing_positions": losing_positions,
    }


def _activity_payload(
    engine,
    user_id: Optional[int] = None,
    limit: int = 25,
    recent_trades: Optional[list[Dict[str, Any]]] = None,
) -> list[Dict[str, Any]]:
    notifier = getattr(engine, "notifier", None)
    getter = getattr(notifier, "get_recent_messages", None)
    if callable(getter):
        messages = getter(user_id=user_id, limit=limit)
        if messages:
            return list(messages)

    fallback = []
    trades = list(recent_trades or [])[-limit:] if recent_trades is not None else _recent_trades(engine, limit=limit, user_id=user_id)
    for trade in trades:
        symbol = str(trade.get("symbol") or "UNK")
        trade_type = str(trade.get("type") or "trade").upper()
        direction = str(trade.get("direction") or "").upper()
        price = _coerce_float(trade.get("price"))
        pnl = _coerce_float(trade.get("pnl"))
        suffix = ""
        if price is not None:
            suffix += f" @ {price:.4f}"
        if pnl is not None:
            suffix += f" PnL {pnl:+.2f}"
        fallback.append(
            {
                "timestamp": trade.get("timestamp"),
                "created_at": trade.get("created_at"),
                "text": f"{trade_type} {symbol} {direction}{suffix}".strip(),
                "user_id": None if user_id is None else str(user_id),
                "source": "trade",
            }
        )
    return fallback[-limit:]


def _trade_count(engine, user_id: Optional[int] = None) -> int:
    if _uses_user_sessions(engine):
        if user_id is not None:
            session = _get_user_session(engine, user_id, create=True)
            return len(getattr(session, "trade_history", []) or []) if session is not None else 0
        return sum(len(getattr(session, "trade_history", []) or []) for session in _list_user_sessions(engine))
    if hasattr(engine, "trade_history"):
        return len(engine.trade_history)
    if hasattr(engine, "trades"):
        return len(engine.trades)
    return 0


def _snapshot(engine, user_id: Optional[int] = None):
    symbols = list(engine.symbols)
    if _uses_user_sessions(engine):
        if user_id is not None:
            session = _get_user_session(engine, user_id, create=True)
            balance = getattr(session, "balance", 0.0) if session is not None else 0.0
            reference_balance = (
                getattr(session, "reference_balance", balance)
                if session is not None
                else balance
            )
            started_at = getattr(session, "session_started_at", None) if session is not None else None
            paused = getattr(session, "is_paused", False) if session is not None else False
            open_positions = len(getattr(session, "positions", {}) or {}) if session is not None else 0
            initial_balance = engine.config.get("backtest", {}).get("initial_balance")
            active_user_count = 1 if session is not None else 0
        else:
            sessions = _list_user_sessions(engine)
            balance = sum(float(getattr(session, "balance", 0.0) or 0.0) for session in sessions)
            reference_balance = sum(
                float(getattr(session, "reference_balance", getattr(session, "balance", 0.0)) or 0.0)
                for session in sessions
            )
            started_at = min((session.session_started_at for session in sessions if session.session_started_at), default=None)
            paused = bool(sessions) and all(bool(getattr(session, "is_paused", False)) for session in sessions)
            open_positions = sum(len(getattr(session, "positions", {}) or {}) for session in sessions)
            initial_balance = (engine.config.get("backtest", {}).get("initial_balance") or 0) * len(sessions)
            active_user_count = len(sessions)
        return {
            "app": APP_NAME,
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_started_at": started_at,
            "mode": engine.config.get("mode"),
            "exchange": engine.exchange_id,
            "running": engine.is_running,
            "paused": paused,
            "balance": 0.0 if user_id is None else balance,
            "reference_balance": 0.0 if user_id is None else reference_balance,
            "initial_balance": 0.0 if user_id is None else initial_balance,
            "symbols": symbols,
            "symbol_count": len(symbols),
            "open_positions": open_positions,
            "trade_count": _trade_count(engine, user_id=user_id),
            "active_user_count": active_user_count,
        }

    global_session = getattr(engine, "_global_session", None)
    reference_balance = getattr(global_session, "reference_balance", None)
    if reference_balance is None:
        reference_balance = getattr(engine, "reference_balance", engine.balance)

    balance = getattr(engine, "balance", 0.0)
    initial_balance = engine.config.get("backtest", {}).get("initial_balance") or 0.0

    return {
        "app": APP_NAME,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_started_at": getattr(engine, "session_started_at", None),
        "mode": engine.config.get("mode"),
        "exchange": engine.exchange_id,
        "running": engine.is_running,
        "paused": engine.is_paused,
        "balance": 0.0 if user_id is None else balance,
        "reference_balance": 0.0 if user_id is None else reference_balance,
        "initial_balance": 0.0 if user_id is None else initial_balance,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "open_positions": len(engine.positions),
        "trade_count": _trade_count(engine, user_id=user_id),
    }


def _serialize_position(symbol: str, position: Any, *, mark_price: Optional[float] = None) -> Dict[str, Any]:
    if isinstance(position, dict):
        resolved_mark_price = position.get("mark_price")
        if resolved_mark_price is None:
            resolved_mark_price = position.get("current_price")
        if resolved_mark_price is None:
            resolved_mark_price = mark_price
        payload = {
            "symbol": symbol,
            "direction": position.get("direction"),
            "entry_price": position.get("entry_price"),
            "quantity": position.get("quantity", position.get("qty")),
            "stop_loss": position.get("stop_loss"),
            "take_profit": position.get("take_profit"),
            "entry_time": position.get("entry_time", position.get("open_time")),
            "mark_price": resolved_mark_price,
            "current_pnl": position.get("current_pnl", position.get("pnl")),
        }
        for key, value in (
            ("leverage", position.get("leverage")),
            ("margin_used", position.get("margin_used", position.get("margin"))),
            ("score", position.get("score")),
            ("signals_count", position.get("signals_count")),
        ):
            if value is not None:
                payload[key] = value
        return payload

    resolved_mark_price = getattr(position, "mark_price", None)
    if resolved_mark_price is None:
        resolved_mark_price = mark_price
    payload = {
        "symbol": symbol,
        "direction": getattr(position, "direction", None),
        "entry_price": getattr(position, "entry_price", None),
        "quantity": getattr(position, "quantity", None),
        "stop_loss": getattr(position, "stop_loss", None),
        "take_profit": getattr(position, "take_profit", None),
        "entry_time": getattr(position, "open_time", None),
        "mark_price": resolved_mark_price,
        "current_pnl": getattr(position, "current_pnl", None),
    }
    for key in ("leverage", "margin_used", "score", "signals_count"):
        value = getattr(position, key, None)
        if value is not None:
            payload[key] = value
    return payload


def _positions_payload(engine, user_id: Optional[int] = None):
    if _uses_user_sessions(engine):
        if user_id is not None:
            session = _get_user_session(engine, user_id, create=True)
            positions = getattr(session, "positions", {}) if session is not None else {}
            return [
                _serialize_position(
                    symbol,
                    position,
                    mark_price=_position_mark_price(engine, symbol, user_id=user_id),
                )
                for symbol, position in positions.items()
            ]

        payload = []
        for session in _list_user_sessions(engine):
            for symbol, position in getattr(session, "positions", {}).items():
                item = _serialize_position(
                    symbol,
                    position,
                    mark_price=_position_mark_price(engine, symbol, user_id=getattr(session, "user_id", None)),
                )
                item["user_id"] = getattr(session, "user_id", None)
                payload.append(item)
        return payload

    return [
        _serialize_position(
            symbol,
            position,
            mark_price=_position_mark_price(engine, symbol),
        )
        for symbol, position in engine.positions.items()
    ]


def _recent_trades(engine, limit: int = 20, user_id: Optional[int] = None):
    if _uses_user_sessions(engine):
        if user_id is not None:
            session = _get_user_session(engine, user_id, create=True)
            history = list(getattr(session, "trade_history", []) or []) if session is not None else []
            if history:
                return history[-limit:]
            since = getattr(session, "session_started_at", None) if session is not None else None
        else:
            history = []
            for session in _list_user_sessions(engine):
                history.extend(list(getattr(session, "trade_history", []) or []))
            if history:
                history.sort(key=lambda trade: int(trade.get("timestamp") or 0))
                return history[-limit:]
            since = getattr(engine, "session_started_at", None)

        db = getattr(engine, "db", None)
        if db and hasattr(db, "get_recent_trades"):
            kwargs = {"limit": limit, "since": since}
            if user_id is not None:
                kwargs["user_id"] = user_id
            return db.get_recent_trades(**kwargs)
        return []

    history = list(getattr(engine, "trade_history", []) or [])
    if history:
        return history[-limit:]

    db = getattr(engine, "db", None)
    if db and hasattr(db, "get_recent_trades"):
        kwargs = {"limit": limit, "since": getattr(engine, "session_started_at", None)}
        if user_id is not None:
            kwargs["user_id"] = user_id
        return db.get_recent_trades(**kwargs)
    return []


def _performance_summary(engine, trades):
    exit_trades = [trade for trade in trades if trade.get("type") == "exit" and trade.get("pnl") is not None]
    wins = sum(1 for trade in exit_trades if float(trade.get("pnl", 0)) > 0)
    losses = sum(1 for trade in exit_trades if float(trade.get("pnl", 0)) < 0)
    total_closed = len(exit_trades)
    realized_pnl = sum(float(trade.get("pnl", 0) or 0) for trade in exit_trades)
    initial_balance = engine.config.get("backtest", {}).get("initial_balance") or 0

    return {
        "wins": wins,
        "losses": losses,
        "closed_trades": total_closed,
        "win_rate": round((wins / total_closed) * 100, 1) if total_closed else 0.0,
        "realized_pnl": round(realized_pnl, 2),
        "return_percent": round((realized_pnl / initial_balance) * 100, 2) if initial_balance else 0.0,
    }


def _runtime_summary(engine, user_id: Optional[int] = None):
    queue_depth = None
    command_queue = getattr(engine, "command_queue", None)
    if command_queue is not None and hasattr(command_queue, "qsize"):
        try:
            queue_depth = command_queue.qsize()
        except Exception:  # pragma: no cover - defensive
            queue_depth = None

    if _uses_user_sessions(engine):
        if user_id is not None:
            session = _get_user_session(engine, user_id, create=True)
            is_paused = bool(getattr(session, "is_paused", False)) if session is not None else False
            paused_until = float(getattr(session, "safety_paused_until", 0) or 0) if session is not None else 0.0
            active_user_count = 1 if session is not None else 0
            runtime_api_ready = bool(getattr(session, "runtime_api_ready", False)) if session is not None else False
        else:
            sessions = _list_user_sessions(engine)
            is_paused = bool(sessions) and all(bool(getattr(session, "is_paused", False)) for session in sessions)
            paused_until = max((float(getattr(session, "safety_paused_until", 0) or 0) for session in sessions), default=0.0)
            active_user_count = len(sessions)
            runtime_api_ready = any(bool(getattr(session, "runtime_api_ready", False)) for session in sessions)
    else:
        is_paused = bool(engine.is_paused)
        paused_until = float(getattr(engine, "safety_paused_until", 0) or 0)
        active_user_count = None
        checker = getattr(engine, "_runtime_api_ready", None)
        runtime_api_ready = bool(checker()) if callable(checker) else False

    remaining_seconds = max(paused_until - time.time(), 0)
    return {
        "engine_status": "paused" if is_paused else ("running" if engine.is_running else "stopped"),
        "websocket_connected": getattr(engine, "_websocket", None) is not None,
        "command_queue_depth": queue_depth,
        "safety_pause_remaining_seconds": int(remaining_seconds),
        "safety_paused_until": (
            datetime.fromtimestamp(paused_until, tz=timezone.utc).isoformat()
            if remaining_seconds
            else None
        ),
        "active_user_count": active_user_count,
        "runtime_api_ready": runtime_api_ready,
    }


def _member_profile(engine, user_id: int, stripe_service: StripeService) -> Dict[str, Any]:
    db = getattr(engine, "db", None)
    user: Dict[str, Any] = {}
    user_getter = getattr(db, "get_user", None)
    if callable(user_getter):
        raw_user = user_getter(user_id)
        if isinstance(raw_user, dict):
            user = dict(raw_user)

    membership: Dict[str, Any] = {}
    membership_getter = getattr(db, "get_membership_summary", None)
    if callable(membership_getter):
        raw_membership = membership_getter(
            user_id,
            str(user.get("username") or ""),
            str(user.get("first_name") or ""),
        )
        if isinstance(raw_membership, dict):
            membership = dict(raw_membership)

    vault: Dict[str, Any] = {}
    vault_getter = getattr(db, "get_user_api_key_status", None)
    if callable(vault_getter):
        raw_vault = vault_getter(user_id)
        if isinstance(raw_vault, dict):
            vault = dict(raw_vault)

    stored_state: Dict[str, Any] = {}
    member_state_getter = getattr(db, "get_user_member_state", None)
    if callable(member_state_getter):
        raw_member_state = member_state_getter(user_id)
        if isinstance(raw_member_state, dict):
            stored_state = dict(raw_member_state)

    mode = str(getattr(engine, "config", {}).get("mode") or "").strip().lower()
    runtime = _runtime_summary(engine, user_id=user_id)
    active_api_user_id: Optional[int]
    effective_enabled: bool
    if _uses_user_sessions(engine):
        session = _get_user_session(engine, user_id, create=True)
        active_api_user_id = _coerce_int(getattr(session, "active_api_user_id", None)) if session is not None else None
        effective_enabled = bool(session is not None and not getattr(session, "is_paused", False))
    else:
        # Use global session for non-user-scoped simulation
        global_session = getattr(engine, "_global_session", None)
        active_api_user_id = _coerce_int(getattr(global_session, "active_api_user_id", None)) if global_session is not None else None
        effective_enabled = bool(
            getattr(engine, "is_running", False)
            and not getattr(engine, "is_paused", False)
            and (active_api_user_id is None or active_api_user_id == user_id)
        )

    desired_enabled = bool(stored_state.get("live_enabled", effective_enabled))
    is_verified = bool(user.get("is_verified"))
    email = user.get("email") or user.get("pending_email")
    membership_expires_at = user.get("membership_expires_at")
    trial_started_at = user.get("trial_started_at")
    stripe_customer_id = str(user.get("stripe_customer_id") or "").strip()
    stripe_subscription_id = str(user.get("stripe_subscription_id") or "").strip()
    stripe_subscription_status = str(user.get("stripe_subscription_status") or "").strip()
    owns_runtime_session = active_api_user_id in {None, user_id}
    can_live = bool(membership.get("can_live"))
    can_simulation = bool(membership.get("can_simulation"))
    vault_configured = bool(vault.get("configured"))
    runtime_api_ready = bool(runtime.get("runtime_api_ready"))
    pause_remaining = int(runtime.get("safety_pause_remaining_seconds") or 0)
    billing_portal_ready = bool(stripe_customer_id and stripe_service.is_portal_configured())

    status_label = "Locked"
    status_tone = "negative"
    detail = "Use /dashboard_login in Telegram again if this session expires."
    can_toggle = False

    if mode == "live":
        if not can_live:
            detail = "An active Pro membership is required for live trading."
        elif not is_verified:
            detail = "Verify your email in Telegram before enabling live trading."
        elif not vault_configured:
            detail = "Store exchange API keys with /setup_api before enabling live trading."
        elif not owns_runtime_session:
            detail = "Another Telegram account currently owns the live vault on this deployment."
        elif desired_enabled and effective_enabled:
            status_label = "Live enabled"
            status_tone = "positive"
            detail = "This Railway live engine is armed and trading under your Telegram-linked vault."
            can_toggle = True
        elif pause_remaining > 0:
            status_label = "Safety pause"
            status_tone = "amber"
            detail = f"Safety pause is still active for about {max(1, int((pause_remaining + 59) / 60))} minute(s)."
        elif not runtime_api_ready or active_api_user_id != user_id:
            status_label = "Vault locked"
            status_tone = "amber"
            detail = "Unlock your API vault in Telegram with /unlock_api before enabling live trading."
            can_toggle = True
        else:
            status_label = "Live ready"
            status_tone = "amber"
            detail = "Your account is eligible. Enable live trading when you are ready."
            can_toggle = True
    elif _uses_user_sessions(engine):
        if not can_simulation:
            detail = "A paid membership is required before this deployment can trade for your session."
        elif effective_enabled:
            status_label = "Simulation running"
            status_tone = "positive"
            detail = "Your Telegram-linked simulation session is active on this deployment."
            can_toggle = True
        elif pause_remaining > 0:
            status_label = "Safety pause"
            status_tone = "amber"
            detail = f"Safety pause is still active for about {max(1, int((pause_remaining + 59) / 60))} minute(s)."
            can_toggle = True
        else:
            status_label = "Simulation paused"
            status_tone = "amber"
            detail = "Enable trading to let your saved strategy resume on this simulation deployment."
            can_toggle = True
    else:
        detail = "Member live control is unavailable for this deployment mode."

    return {
        "telegram_id": user_id,
        "mode": mode or "unknown",
        "email": email,
        "is_verified": is_verified,
        "membership_tier": membership.get("tier", "free"),
        "membership_status": membership.get("status", "free"),
        "membership_source": membership.get("source", "manual"),
        "membership_expires_at": membership_expires_at,
        "trial_started_at": trial_started_at,
        "can_live": can_live,
        "can_simulation": can_simulation,
        "vault_configured": vault_configured,
        "vault_zero_knowledge": bool(vault.get("zero_knowledge")),
        "runtime_api_ready": runtime_api_ready,
        "active_api_user_id": active_api_user_id,
        "owns_runtime_session": owns_runtime_session,
        "live_enabled": desired_enabled,
        "effective_enabled": effective_enabled,
        "can_toggle": can_toggle,
        "billing_portal_ready": billing_portal_ready,
        "billing_customer_on_file": bool(stripe_customer_id),
        "billing_subscription_on_file": bool(stripe_subscription_id),
        "stripe_subscription_status": stripe_subscription_status,
        "status_label": status_label,
        "status_tone": status_tone,
        "detail": detail,
    }


def _set_member_enabled(engine, user_id: int, enabled: bool, stripe_service: StripeService) -> Dict[str, Any]:
    mode = str(getattr(engine, "config", {}).get("mode") or "").strip().lower()
    db = getattr(engine, "db", None)
    profile = _member_profile(engine, user_id, stripe_service)

    if mode == "live":
        if not profile["can_live"]:
            raise HTTPException(status_code=403, detail="Live trading requires an active Pro membership.")
        if not profile["is_verified"]:
            raise HTTPException(status_code=403, detail="Verify your email in Telegram before enabling live trading.")
        if not profile["vault_configured"]:
            raise HTTPException(status_code=409, detail="Store exchange API keys with /setup_api before enabling live trading.")
        if not profile["owns_runtime_session"]:
            raise HTTPException(status_code=409, detail="Another Telegram account currently owns the live vault on this deployment.")
        if enabled:
            if not profile["runtime_api_ready"] or profile["active_api_user_id"] != user_id:
                raise HTTPException(status_code=409, detail="Unlock your API vault in Telegram with /unlock_api before enabling live trading.")
            remaining = int(_runtime_summary(engine, user_id=user_id).get("safety_pause_remaining_seconds") or 0)
            if remaining > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Safety pause is still active for about {max(1, int((remaining + 59) / 60))} minute(s).",
                )
            engine.is_paused = False
            engine.safety_paused_until = 0
        else:
            engine.is_paused = True
    elif _uses_user_sessions(engine):
        if not profile["can_simulation"]:
            raise HTTPException(status_code=403, detail="A paid membership is required before this deployment can trade for your session.")
        session = _get_user_session(engine, user_id, create=True)
        if session is None:
            raise HTTPException(status_code=503, detail="Could not load your session.")
        if enabled:
            remaining = int(max(float(getattr(session, "safety_paused_until", 0) or 0) - time.time(), 0))
            if remaining > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Safety pause is still active for about {max(1, int((remaining + 59) / 60))} minute(s).",
                )
            session.is_paused = False
            session.safety_paused_until = 0
        else:
            session.is_paused = True
        persister = getattr(engine, "_persist_session_state", None)
        if callable(persister):
            persister(session)
    else:
        raise HTTPException(status_code=409, detail="Member live control is unavailable for this deployment.")

    if db and hasattr(db, "store_user_member_state"):
        db.store_user_member_state(
            user_id,
            {
                "live_enabled": bool(enabled),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return _member_profile(engine, user_id, stripe_service)


def _config_summary(engine, auth_token: Optional[str], stripe_service: StripeService):
    exchange_config = engine.config.get(engine.exchange_id, {})
    telegram_config = engine.config.get("telegram", {})
    email_config = engine.config.get("email", {})
    db = getattr(engine, "db", None)
    cipher = getattr(db, "cipher", None)

    return {
        "timeframe": engine.config.get("strategy", {}).get("timeframe"),
        "market_type": exchange_config.get("market_type") or exchange_config.get("symbol_type") or "swap",
        "scan_all_symbols": bool(exchange_config.get("scan_all_symbols", False)),
        "testnet": bool(exchange_config.get("testnet", False)),
        "telegram_polling_enabled": _coerce_bool(telegram_config.get("polling_enabled", True)),
        "telegram_notifications_enabled": bool(telegram_config.get("enable_notifications", False)),
        "email_webhook_configured": bool(email_config.get("confirm_webhook_url")),
        "stripe_checkout_configured": stripe_service.is_checkout_configured(),
        "stripe_webhook_configured": stripe_service.is_webhook_configured(),
        "stripe_portal_configured": stripe_service.is_portal_configured(),
        "supabase_configured": bool(getattr(db, "url", "")) and bool(getattr(db, "key", "")),
        "supabase_connected": getattr(db, "client", None) is not None,
        "encryption_status": getattr(cipher, "status", "unknown"),
        "using_fallback_encryption": bool(getattr(cipher, "using_fallback_key", False)),
        "api_token_required": bool(auth_token),
    }


def _strategy_payload(engine, user_id: Optional[int] = None):
    getter = getattr(engine, "get_strategy_config", None)
    if callable(getter):
        profile = getter(user_id)
    else:
        profile = {}
    profile = normalize_strategy_profile(getattr(engine, "config", {}), profile)
    return {
        "profile": profile,
        "timeframes": ["1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D"],
        "directions": ["LONG", "SHORT", "BOTH"],
        "allowed_backtest_candles": sorted(ALLOWED_REMOTE_CANDLE_COUNTS),
    }


def _user_summary(engine):
    db = getattr(engine, "db", None)
    if db and hasattr(db, "get_user_summary"):
        return db.get_user_summary(limit=15)
    return {
        "total": 0,
        "verified": 0,
        "unverified": 0,
        "with_api_keys": 0,
        "free": 0,
        "trial_pro": 0,
        "pro": 0,
        "expired": 0,
        "recent": [],
    }


def _dashboard_payload(engine, auth_token: Optional[str], stripe_service: StripeService):
    snapshot = _snapshot(engine)
    return {
        "snapshot": snapshot,
        "runtime": _runtime_summary(engine),
        "config": _config_summary(engine, auth_token, stripe_service),
        "positions": [],
        "recent_trades": [],
        "performance": _performance_summary(engine, []),
        "portfolio": _portfolio_summary(snapshot, []),
        "activity": [],
        "users": {},
        "strategy": _strategy_payload(engine),
    }


def _member_dashboard_payload(engine, user_id: int, stripe_service: StripeService):
    trades = _recent_trades(engine, user_id=user_id)
    snapshot = _snapshot(engine, user_id=user_id)
    snapshot["initial_balance"] = None
    positions = _positions_payload(engine, user_id=user_id)
    return {
        "member_access": True,
        "user_id": user_id,
        "snapshot": snapshot,
        "runtime": _runtime_summary(engine, user_id=user_id),
        "positions": positions,
        "recent_trades": trades,
        "performance": _performance_summary(engine, trades),
        "portfolio": _portfolio_summary(snapshot, positions),
        "activity": _activity_payload(engine, user_id=user_id, recent_trades=trades),
        "config": {},
        "users": {},
        "strategy": _strategy_payload(engine, user_id=user_id),
        "member": _member_profile(engine, user_id, stripe_service),
    }


def _public_dashboard_payload(engine):
    snapshot = _snapshot(engine)
    positions = _positions_payload(engine)
    trades = _recent_trades(engine)
    return {
        "public_bootstrap": True,
        "snapshot": snapshot,
        "runtime": _runtime_summary(engine),
        "positions": [],
        "recent_trades": [],
        "performance": _performance_summary(engine, trades),
        "portfolio": _portfolio_summary(snapshot, positions),
        "activity": [],
        "users": {},
        "config": {},
        "strategy": {},
    }


def create_app(engine, auth_token: Optional[str] = None) -> FastAPI:
    app = FastAPI(title=f"{APP_NAME} API", version=__version__)
    stripe_service = StripeService(engine.config)
    telegram_login = _telegram_login_context(engine.config, auth_token)
    app.mount("/assets", StaticFiles(directory=str(LANDING_DIST_DIR / "assets"), check_dir=False), name="landing-assets")

    def _authorized_actor(
        request: Optional[Request],
        provided_token: Optional[str],
        access: Optional[str] = None,
    ) -> Optional[int]:
        token = _resolve_dashboard_token(request, provided_token, access)
        return _authorize_dashboard_request(auth_token, token)

    def _authorized_member(
        request: Optional[Request],
        provided_token: Optional[str],
        access: Optional[str] = None,
    ) -> int:
        token = _resolve_dashboard_token(request, provided_token, access)
        return _authorize_member_dashboard(auth_token, token)

    @app.get("/", response_class=FileResponse)
    def root():
        landing_index = _first_existing_path(LANDING_DIST_DIR / "index.html")
        if landing_index is None:
            raise HTTPException(status_code=503, detail="Landing page is not built")
        return FileResponse(landing_index, media_type="text/html")

    @app.get("/dashboard/login", response_class=HTMLResponse)
    def dashboard_login(request: Request, login_error: Optional[str] = None):
        # If already logged in, redirect to dashboard
        token = _resolve_dashboard_token(request)
        if token:
            try:
                _authorize_dashboard_request(auth_token, token)
                return RedirectResponse(url="/dashboard", status_code=307)
            except HTTPException:
                pass

        return HTMLResponse(
            build_login_html(
                APP_NAME,
                telegram_login_enabled=bool(telegram_login["enabled"]),
                telegram_login_bot_username=str(telegram_login["bot_username"]),
                telegram_login_url=str(telegram_login["auth_url"]),
                redirect_to="/dashboard",
            )
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, access: Optional[str] = None):
        if access:
            return _apply_no_store(
                RedirectResponse(url=f"/dashboard/member?access={quote(access, safe='')}", status_code=307),
                private=True,
                vary_cookie=True,
            )

        token = _resolve_dashboard_token(request)
        if not token:
            return RedirectResponse(url="/dashboard/login")

        try:
            _authorize_dashboard_request(auth_token, token)
        except HTTPException:
            return RedirectResponse(url="/dashboard/login")

        response = HTMLResponse(
            build_dashboard_html(
                APP_NAME,
                __version__,
                auth_required=True,
                public_mode=True,
                member_session_mode=False,
                data_endpoint="/dashboard/member-data",
                token_storage_key="fancyfinance_member_dashboard_token",
                query_token_param="access",
                persist_token=False,
                telegram_login_enabled=bool(telegram_login["enabled"]),
                telegram_login_bot_username=str(telegram_login["bot_username"]),
                telegram_login_url=str(telegram_login["auth_url"]),
                telegram_bot_url=str(telegram_login["bot_url"]),
            )
        )
        return _apply_no_store(response, vary_cookie=True)

    @app.get("/dashboard/login/telegram", response_class=RedirectResponse)
    def dashboard_login_via_telegram(request: Request):
        if not auth_token or not telegram_login.get("bot_token"):
            return _apply_no_store(
                RedirectResponse(
                    url=f"/dashboard/login?login_error={quote('Telegram dashboard login is not configured yet.', safe='')}",
                    status_code=307,
                ),
                private=True,
                vary_cookie=True,
            )

        try:
            telegram_user = verify_telegram_login_payload(
                str(telegram_login["bot_token"]),
                dict(request.query_params),
            )
        except DashboardAccessError as exc:
            logger.warning(f"Rejected Telegram dashboard login: {exc}")
            return _apply_no_store(
                RedirectResponse(
                    url=f"/dashboard/login?login_error={quote(str(exc), safe='')}",
                    status_code=307,
                ),
                private=True,
                vary_cookie=True,
            )

        user_id = int(telegram_user["id"])
        db = getattr(engine, "db", None)
        get_or_create_user = getattr(db, "get_or_create_user", None)
        if callable(get_or_create_user):
            try:
                _invoke_with_supported_kwargs(
                    get_or_create_user,
                    user_id,
                    str(telegram_user.get("username") or ""),
                    str(telegram_user.get("first_name") or ""),
                )
            except Exception as exc:
                logger.warning(f"Failed to sync Telegram dashboard login for {user_id}: {exc}")

        member_token = generate_member_dashboard_token(
            auth_token,
            user_id,
            ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
        )
        response = RedirectResponse(url="/dashboard/member", status_code=307)
        response.set_cookie(
            MEMBER_ACCESS_COOKIE,
            member_token,
            httponly=True,
            samesite="lax",
            secure=_member_access_cookie_secure(request),
            path="/",
        )
        return _apply_no_store(response, private=True, vary_cookie=True)

    @app.get("/dashboard/admin", response_class=HTMLResponse)
    def dashboard_admin():
        return HTMLResponse(
            build_dashboard_html(
                APP_NAME,
                __version__,
                auth_required=bool(auth_token),
                token_storage_key="fancyfinance_admin_dashboard_token",
            )
        )

    @app.get("/dashboard/assets/logo.png")
    def dashboard_logo():
        if not DASHBOARD_LOGO_PATH.exists():
            raise HTTPException(status_code=404, detail="Dashboard logo not found")
        return FileResponse(DASHBOARD_LOGO_PATH, media_type="image/png")

    @app.get("/favicon.ico")
    def favicon():
        if not DASHBOARD_LOGO_PATH.exists():
            raise HTTPException(status_code=404, detail="Favicon not found")
        return FileResponse(DASHBOARD_LOGO_PATH, media_type="image/png")

    @app.get("/privacy-policy", response_class=HTMLResponse)
    def privacy_policy():
        privacy_policy_path = _first_existing_path(
            PRIVACY_POLICY_PATH,
            LANDING_PUBLIC_DIR / "privacy-policy.html",
        )
        if privacy_policy_path is None:
            raise HTTPException(status_code=404, detail="Privacy policy not found")
        return FileResponse(privacy_policy_path, media_type="text/html")

    @app.get("/terms-of-use", response_class=HTMLResponse)
    def terms_of_use():
        terms_path = _first_existing_path(
            TERMS_OF_USE_PATH,
            LANDING_PUBLIC_DIR / "terms-of-use.html",
        )
        if terms_path is None:
            raise HTTPException(status_code=404, detail="Terms of use not found")
        return FileResponse(terms_path, media_type="text/html")

    @app.get("/terms-of-service", response_class=RedirectResponse)
    def terms_of_service_alias():
        return RedirectResponse(url="/terms-of-use", status_code=307)

    @app.get("/dashboard/member", response_class=HTMLResponse)
    def member_dashboard(request: Request, access: Optional[str] = None):
        landing_index = _first_existing_path(LANDING_DIST_DIR / "index.html")
        
        if access:
            try:
                _authorize_member_dashboard(auth_token, access)
                
                # If SPA exists, let it handle the access token (it will save to localStorage and clean URL)
                if landing_index:
                    response = FileResponse(landing_index, media_type="text/html")
                    response.set_cookie(
                        MEMBER_ACCESS_COOKIE,
                        access,
                        httponly=True,
                        samesite="lax",
                        secure=_member_access_cookie_secure(request),
                        path="/",
                    )
                    return _apply_no_store(response, private=True, vary_cookie=True)
                
                # Legacy fallback redirect
                response = RedirectResponse(url="/dashboard/member", status_code=307)
                response.set_cookie(
                    MEMBER_ACCESS_COOKIE,
                    access,
                    httponly=True,
                    samesite="lax",
                    secure=_member_access_cookie_secure(request),
                    path="/",
                )
                return _apply_no_store(response, private=True, vary_cookie=True)
            except HTTPException:
                return RedirectResponse(url=f"/dashboard/login?login_error={quote('Invalid or expired access token.')}")

        token = _resolve_dashboard_token(request)
        if not token:
            return RedirectResponse(url="/dashboard/login")

        try:
            _authorize_member_dashboard(auth_token, token)
        except HTTPException:
            response = RedirectResponse(url="/dashboard/login")
            response.delete_cookie(MEMBER_ACCESS_COOKIE, path="/")
            return response

        # Prefer the new React SPA for the member dashboard
        if landing_index:
            return FileResponse(landing_index, media_type="text/html")

        # Fallback to legacy dashboard
        response = HTMLResponse(
            build_dashboard_html(
                APP_NAME,
                __version__,
                auth_required=True,
                public_mode=True,
                member_session_mode=True,
                data_endpoint="/dashboard/member-data",
                token_storage_key="fancyfinance_member_dashboard_token",
                query_token_param="access",
                persist_token=False,
                telegram_login_enabled=bool(telegram_login["enabled"]),
                telegram_login_bot_username=str(telegram_login["bot_username"]),
                telegram_login_url=str(telegram_login["auth_url"]),
                telegram_bot_url=str(telegram_login["bot_url"]),
            )
        )
        return _apply_no_store(response, private=True, vary_cookie=True)

    @app.get("/auth/callback", response_class=HTMLResponse)
    def auth_callback():
        landing_index = _first_existing_path(LANDING_DIST_DIR / "index.html")
        if landing_index:
            return FileResponse(landing_index, media_type="text/html")
        raise HTTPException(status_code=503, detail="Landing page is not built")

    @app.get("/webhook/telegram-login", response_class=RedirectResponse)
    def telegram_login_alias(request: Request):
        # Alias for the Telegram login webhook mentioned in AuthCallback.tsx
        return dashboard_login_via_telegram(request)

    @app.get("/account", response_class=RedirectResponse)
    def member_account(access: Optional[str] = None):
        target = "/dashboard/member#account-panel"
        if access:
            target = f"/dashboard/member?access={quote(access, safe='')}#account-panel"
        return _apply_no_store(RedirectResponse(url=target, status_code=307), private=True, vary_cookie=True)

    @app.post("/account/portal-session")
    async def member_account_portal_session(
        request: Request,
        x_api_key: Optional[str] = Header(default=None),
        access: Optional[str] = None,
    ):
        user_id = _authorized_member(request, x_api_key, access)
        if not stripe_service.is_portal_configured():
            raise HTTPException(status_code=503, detail="Stripe billing portal is not fully configured")

        try:
            raw_payload = await request.json()
        except Exception:
            raw_payload = {}

        flow = "portal"
        if isinstance(raw_payload, dict):
            flow = str(raw_payload.get("flow") or "portal").strip().lower()

        db = getattr(engine, "db", None)
        user = None
        get_user = getattr(db, "get_user", None)
        if callable(get_user):
            user = get_user(user_id)
        if not isinstance(user, dict):
            raise HTTPException(status_code=404, detail="Could not load your account profile")

        stripe_customer_id = str(user.get("stripe_customer_id") or "").strip()
        stripe_subscription_id = str(user.get("stripe_subscription_id") or "").strip()
        if not stripe_customer_id:
            raise HTTPException(status_code=404, detail="No Stripe billing account is linked to this member yet")

        portal_kwargs: Dict[str, Any] = {}
        if flow in {"portal", "receipts", "billing"}:
            normalized_flow = "portal"
        elif flow in {"payment", "payment_method", "payment_method_update"}:
            normalized_flow = "payment_method_update"
            portal_kwargs["flow_type"] = normalized_flow
        elif flow in {"cancel", "cancel_membership", "subscription_cancel"}:
            if not stripe_subscription_id:
                raise HTTPException(status_code=404, detail="No Stripe subscription is linked to this member yet")
            normalized_flow = "subscription_cancel"
            portal_kwargs["flow_type"] = normalized_flow
            portal_kwargs["subscription_id"] = stripe_subscription_id
        else:
            raise HTTPException(status_code=400, detail="Unsupported billing portal action")

        base_url = str(request.base_url).rstrip("/")
        return_url = f"{base_url}/account"
        try:
            session = await asyncio.to_thread(
                stripe_service.create_customer_portal_session,
                customer_id=stripe_customer_id,
                return_url=return_url,
                **portal_kwargs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(f"Failed to create member billing portal session for {user_id}: {exc}")
            raise HTTPException(status_code=502, detail="Could not open the billing portal right now") from exc

        portal_url = str(session.get("url") or "").strip()
        if not portal_url:
            raise HTTPException(status_code=502, detail="Stripe did not return a billing portal URL")

        return _apply_no_store(
            JSONResponse(
                {
                    "ok": True,
                    "flow": normalized_flow,
                    "url": portal_url,
                }
            ),
            private=True,
            vary_cookie=True,
        )

    @app.post("/dashboard/session/clear")
    def clear_dashboard_session():
        response = HTMLResponse("")
        response.delete_cookie(MEMBER_ACCESS_COOKIE, path="/")
        return _apply_no_store(response, private=True, vary_cookie=True)

    @app.get("/dashboard/data")
    def dashboard_data(request: Request, x_api_key: Optional[str] = Header(default=None)):
        member_user_id = _authorized_actor(request, x_api_key)
        if member_user_id is not None:
            return _apply_no_store(
                JSONResponse(_member_dashboard_payload(engine, member_user_id, stripe_service)),
                private=True,
                vary_cookie=True,
            )
        return _apply_no_store(JSONResponse(_dashboard_payload(engine, auth_token, stripe_service)), private=True, vary_cookie=True)

    @app.get("/dashboard/member-data")
    def dashboard_member_data(
        request: Request,
        x_api_key: Optional[str] = Header(default=None),
        access: Optional[str] = None,
    ):
        user_id = _authorized_member(request, x_api_key, access)
        return _apply_no_store(
            JSONResponse(_member_dashboard_payload(engine, user_id, stripe_service)),
            private=True,
            vary_cookie=True,
        )

    @app.get("/dashboard/bootstrap")
    def dashboard_bootstrap():
        return _apply_no_store(JSONResponse(_public_dashboard_payload(engine)), vary_cookie=True)

    @app.post("/strategy/config")
    async def strategy_config_save(request: Request, x_api_key: Optional[str] = Header(default=None), access: Optional[str] = None):
        actor_user_id = _authorized_actor(request, x_api_key, access)
        setter = getattr(engine, "set_strategy_config", None)
        if not callable(setter):
            raise HTTPException(status_code=503, detail="Strategy configuration is unavailable")

        try:
            raw_payload = await request.json()
        except Exception:
            raw_payload = {}
        payload = raw_payload.get("profile") if isinstance(raw_payload, dict) and isinstance(raw_payload.get("profile"), dict) else raw_payload
        if not isinstance(payload, dict):
            payload = {}

        try:
            profile = setter(payload, user_id=actor_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "ok": True,
            "member_access": actor_user_id is not None,
            "strategy": {"profile": profile},
        }

    @app.post("/dashboard/member/live-toggle")
    async def member_live_toggle(request: Request, x_api_key: Optional[str] = Header(default=None), access: Optional[str] = None):
        actor_user_id = _authorized_member(request, x_api_key, access)
        try:
            raw_payload = await request.json()
        except Exception:
            raw_payload = {}

        enabled = True
        if isinstance(raw_payload, dict) and "enabled" in raw_payload:
            enabled = _coerce_bool(raw_payload.get("enabled"))

        member_state = _set_member_enabled(engine, actor_user_id, enabled, stripe_service)
        return {
            "ok": True,
            "enabled": bool(member_state.get("effective_enabled")),
            "member": member_state,
            "snapshot": _snapshot(engine, user_id=actor_user_id),
            "runtime": _runtime_summary(engine, user_id=actor_user_id),
        }

    @app.post("/dashboard/member/billing-portal")
    async def member_dashboard_billing_portal(
        request: Request,
        x_api_key: Optional[str] = Header(default=None),
        access: Optional[str] = None,
    ):
        user_id = _authorized_member(request, x_api_key, access)
        if not stripe_service.is_portal_configured():
            raise HTTPException(status_code=503, detail="Stripe billing portal is not fully configured")

        db = getattr(engine, "db", None)
        user = None
        get_user = getattr(db, "get_user", None)
        if callable(get_user):
            user = get_user(user_id)
        if not isinstance(user, dict):
            raise HTTPException(status_code=404, detail="Could not load your account profile")

        stripe_customer_id = str(user.get("stripe_customer_id") or "").strip()
        if not stripe_customer_id:
            raise HTTPException(status_code=404, detail="No Stripe billing account is linked to this member yet")

        base_url = str(request.base_url).rstrip("/")
        return_url = f"{base_url}/dashboard/member"
        try:
            session = await asyncio.to_thread(
                stripe_service.create_customer_portal_session,
                customer_id=stripe_customer_id,
                return_url=return_url,
            )
        except Exception as exc:
            logger.error(f"Failed to create member billing portal session for {user_id}: {exc}")
            raise HTTPException(status_code=502, detail="Could not open the billing portal right now") from exc

        return {"url": session.get("url")}

    @app.get("/health")
    def health():
        return {"status": "ok", **_snapshot(engine)}

    @app.get("/robots.txt")
    def robots():
        robots_path = _first_existing_path(
            LANDING_DIST_DIR / "robots.txt",
            LANDING_PUBLIC_DIR / "robots.txt",
        )
        if robots_path is None:
            raise HTTPException(status_code=404, detail="robots.txt not found")
        return FileResponse(robots_path, media_type="text/plain")

    @app.get("/billing/success", response_class=RedirectResponse)
    def billing_success():
        return RedirectResponse(url="/dashboard?subscribed=1", status_code=307)

    @app.get("/billing/cancel", response_class=RedirectResponse)
    def billing_cancel():
        return RedirectResponse(url="/#plans", status_code=307)

    @app.post("/billing/checkout-link")
    async def billing_checkout_link(request: Request):
        try:
            raw_payload = await request.json()
        except Exception:
            raw_payload = {}

        email = ""
        if isinstance(raw_payload, dict):
            email = str(raw_payload.get("email") or "").strip().lower()

        user_payload: Dict[str, Any] = {}
        if email:
            user_payload["email"] = email

        base_url = str(request.base_url).rstrip("/")
        try:
            session = await asyncio.to_thread(
                stripe_service.create_checkout_session,
                user_payload,
                success_url=f"{base_url}/billing/success",
                cancel_url=f"{base_url}/billing/cancel",
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(f"Failed to create public checkout session: {exc}")
            raise HTTPException(status_code=502, detail="Could not create checkout session") from exc

        checkout_url = str(session.get("url") or "").strip()
        if not checkout_url:
            raise HTTPException(status_code=502, detail="Stripe did not return a checkout URL")
        return {"url": checkout_url}

    @app.post("/billing/stripe/webhook")
    async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(default=None, alias="stripe-signature")):
        payload = await request.body()
        db = getattr(engine, "db", None)
        if db is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        try:
            return stripe_service.process_webhook(
                payload=payload,
                signature_header=stripe_signature or "",
                db=db,
            )
        except ValueError as exc:
            logger.warning(f"Stripe webhook rejected: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(f"Stripe webhook failed unexpectedly: {exc}")
            raise

    @app.get("/stats")
    def stats(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        payload = _snapshot(engine)
        payload["positions"] = {position["symbol"]: position for position in _positions_payload(engine)}
        return payload

    @app.post("/backtest/run")
    def backtest_run(
        request: Request,
        symbol: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        timeframe: Optional[str] = None,
        candles: Optional[int] = None,
        min_score: Optional[int] = None,
        min_signals: Optional[int] = None,
        leverage: Optional[int] = None,
        margin: Optional[float] = None,
        max_margin: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        trail_pct: Optional[float] = None,
        max_hold: Optional[int] = None,
        direction: Optional[str] = None,
        min_score_gap: Optional[int] = None,
        cooldown: Optional[int] = None,
        csv_output: Optional[bool] = None,
        x_api_key: Optional[str] = Header(default=None),
        access: Optional[str] = None,
    ):
        actor_user_id = _authorized_actor(request, x_api_key, access)
        getter = getattr(engine, "get_strategy_config", None)
        base_profile = getter(actor_user_id) if callable(getter) else normalize_strategy_profile(engine.config, {})
        try:
            strategy_profile = normalize_strategy_profile(
                engine.config,
                {
                    "timeframe": timeframe,
                    "candles": candles,
                    "min_score": min_score,
                    "min_signals": min_signals,
                    "leverage": leverage,
                    "margin": margin,
                    "max_margin": max_margin,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct,
                    "trail_pct": trail_pct,
                    "max_hold": max_hold,
                    "direction": direction,
                    "min_score_gap": min_score_gap,
                    "cooldown": cooldown,
                    "csv": csv_output,
                },
                current=base_profile,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        resolved_timeframe = timeframe or strategy_profile["timeframe"]
        resolved_candles = int(candles or strategy_profile["candles"])
        include_csv = bool(strategy_profile.get("csv"))
        try:
            if candles is not None:
                if not symbol:
                    return _invoke_with_supported_kwargs(
                        run_backtest_recent_universe,
                        engine.config,
                        timeframe=resolved_timeframe,
                        candles=resolved_candles,
                        strategy_profile=strategy_profile,
                        csv_output=include_csv,
                    )
                return _invoke_with_supported_kwargs(
                    run_backtest_recent,
                    engine.config,
                    symbol=symbol,
                    timeframe=resolved_timeframe,
                    candles=resolved_candles,
                    strategy_profile=strategy_profile,
                    csv_output=include_csv,
                )
            if not symbol:
                raise BacktestServiceError("A symbol is required for date-range backtests. Use `candles=500` or `candles=1000` for scanner-universe runs.")
            return _invoke_with_supported_kwargs(
                run_backtest,
                engine.config,
                symbol=symbol,
                start_date=start,
                end_date=end,
                timeframe=resolved_timeframe,
                strategy_profile=strategy_profile,
                csv_output=include_csv,
            )
        except BacktestServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/control/pause")
    def pause(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        engine.is_paused = True
        return {"status": "paused", **_snapshot(engine)}

    @app.post("/control/resume")
    def resume(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        engine.is_paused = False
        engine.safety_paused_until = 0
        return {"status": "running", **_snapshot(engine)}

    @app.post("/control/shutdown")
    def shutdown(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        engine.stop()
        return {"status": "stopped", **_snapshot(engine)}

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def catch_all(full_path: str):
        # Catch-all to support SPA client-side routing
        landing_index = _first_existing_path(LANDING_DIST_DIR / "index.html")
        if landing_index:
            return FileResponse(landing_index, media_type="text/html")
        raise HTTPException(status_code=404)

    return app


def start_api_server(engine, config):
    api_config = config.get("api", {})
    if not api_config.get("enabled", False):
        return None

    host = api_config.get("host", "0.0.0.0")
    port = int(os.getenv("PORT") or api_config.get("port", 8000))
    auth_token = api_config.get("auth_token") or None
    app = create_app(engine, auth_token=auth_token)

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
        )
    )
    thread = threading.Thread(target=server.run, name="FancyFinanceAPI", daemon=True)
    thread.start()
    return thread
