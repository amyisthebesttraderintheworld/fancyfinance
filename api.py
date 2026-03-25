from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backtest_service import BacktestServiceError, run_backtest, run_backtest_recent, run_backtest_recent_universe
from dashboard_access import DashboardAccessError, verify_member_dashboard_token
from dashboard_ui import build_dashboard_html
from fancyfinance import APP_NAME, __version__
from stripe_service import StripeService


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
        return None
    if not provided_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if provided_token == expected_token:
        return None

    try:
        payload = verify_member_dashboard_token(expected_token, provided_token)
    except DashboardAccessError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return int(payload["sub"])


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _trade_count(engine) -> int:
    if hasattr(engine, "trade_history"):
        return len(engine.trade_history)
    if hasattr(engine, "trades"):
        return len(engine.trades)
    return 0


def _snapshot(engine):
    symbols = list(engine.symbols)
    return {
        "app": APP_NAME,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_started_at": getattr(engine, "session_started_at", None),
        "mode": engine.config.get("mode"),
        "exchange": engine.exchange_id,
        "running": engine.is_running,
        "paused": engine.is_paused,
        "balance": engine.balance,
        "initial_balance": engine.config.get("backtest", {}).get("initial_balance"),
        "symbols": symbols,
        "symbol_count": len(symbols),
        "open_positions": len(engine.positions),
        "trade_count": _trade_count(engine),
    }


def _serialize_position(symbol: str, position: Any) -> Dict[str, Any]:
    if isinstance(position, dict):
        return {
            "symbol": symbol,
            "direction": position.get("direction"),
            "entry_price": position.get("entry_price"),
            "quantity": position.get("quantity", position.get("qty")),
            "stop_loss": position.get("stop_loss"),
            "take_profit": position.get("take_profit"),
        }

    return {
        "symbol": symbol,
        "direction": getattr(position, "direction", None),
        "entry_price": getattr(position, "entry_price", None),
        "quantity": getattr(position, "quantity", None),
        "stop_loss": getattr(position, "stop_loss", None),
        "take_profit": getattr(position, "take_profit", None),
    }


def _positions_payload(engine):
    return [_serialize_position(symbol, position) for symbol, position in engine.positions.items()]


def _recent_trades(engine, limit: int = 20):
    history = list(getattr(engine, "trade_history", []) or [])
    if history:
        return history[-limit:]

    db = getattr(engine, "db", None)
    if db and hasattr(db, "get_recent_trades"):
        return db.get_recent_trades(limit=limit, since=getattr(engine, "session_started_at", None))
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


def _runtime_summary(engine):
    queue_depth = None
    command_queue = getattr(engine, "command_queue", None)
    if command_queue is not None and hasattr(command_queue, "qsize"):
        try:
            queue_depth = command_queue.qsize()
        except Exception:  # pragma: no cover - defensive
            queue_depth = None

    remaining_seconds = max(getattr(engine, "safety_paused_until", 0) - time.time(), 0)
    return {
        "engine_status": "paused" if engine.is_paused else ("running" if engine.is_running else "stopped"),
        "websocket_connected": getattr(engine, "_websocket", None) is not None,
        "command_queue_depth": queue_depth,
        "safety_pause_remaining_seconds": int(remaining_seconds),
        "safety_paused_until": (
            datetime.fromtimestamp(getattr(engine, "safety_paused_until", 0), tz=timezone.utc).isoformat()
            if remaining_seconds
            else None
        ),
    }


def _config_summary(engine, auth_token: Optional[str]):
    exchange_config = engine.config.get(engine.exchange_id, {})
    telegram_config = engine.config.get("telegram", {})
    email_config = engine.config.get("email", {})
    stripe_service = StripeService(engine.config)
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


def _dashboard_payload(engine, auth_token: Optional[str]):
    trades = _recent_trades(engine)
    return {
        "snapshot": _snapshot(engine),
        "runtime": _runtime_summary(engine),
        "config": _config_summary(engine, auth_token),
        "positions": _positions_payload(engine),
        "recent_trades": trades,
        "performance": _performance_summary(engine, trades),
        "users": _user_summary(engine),
    }


def _member_dashboard_payload(engine, user_id: int):
    trades = _recent_trades(engine)
    snapshot = _snapshot(engine)
    snapshot["balance"] = None
    snapshot["initial_balance"] = None
    return {
        "member_access": True,
        "user_id": user_id,
        "snapshot": snapshot,
        "runtime": _runtime_summary(engine),
        "positions": _positions_payload(engine),
        "recent_trades": trades,
        "performance": _performance_summary(engine, trades),
        "config": {},
        "users": {},
    }


def create_app(engine, auth_token: Optional[str] = None) -> FastAPI:
    app = FastAPI(title=f"{APP_NAME} API", version=__version__)
    stripe_service = StripeService(engine.config)

    @app.get("/", response_class=RedirectResponse)
    def root():
        return RedirectResponse(url="/dashboard", status_code=307)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return HTMLResponse(build_dashboard_html(APP_NAME, __version__, auth_required=bool(auth_token)))

    @app.get("/dashboard/member", response_class=HTMLResponse)
    def member_dashboard():
        return HTMLResponse(
            build_dashboard_html(
                APP_NAME,
                __version__,
                auth_required=True,
                public_mode=True,
                data_endpoint="/dashboard/member-data",
                token_storage_key="fancyfinance_member_dashboard_token",
                query_token_param="access",
            )
        )

    @app.get("/dashboard/data")
    def dashboard_data(x_api_key: Optional[str] = Header(default=None)):
        member_user_id = _authorize_dashboard_request(auth_token, x_api_key)
        if member_user_id is not None:
            return _member_dashboard_payload(engine, member_user_id)
        return _dashboard_payload(engine, auth_token)

    @app.get("/dashboard/member-data")
    def dashboard_member_data(x_api_key: Optional[str] = Header(default=None), access: Optional[str] = None):
        user_id = _authorize_member_dashboard(auth_token, x_api_key or access)
        return _member_dashboard_payload(engine, user_id)

    @app.get("/health")
    def health():
        return {"status": "ok", **_snapshot(engine)}

    @app.get("/billing/success", response_class=HTMLResponse)
    def billing_success():
        return HTMLResponse(
            """
            <html><body style="font-family: sans-serif; padding: 32px; background: #0f172a; color: white;">
            <h1>Checkout Completed</h1>
            <p>Your Stripe checkout completed successfully.</p>
            <p>If this was your first upgrade, your 7-day Trial Pro access should activate automatically before full Pro billing begins.</p>
            <p>Return to Telegram and use <strong>/profile</strong> or <strong>/plans</strong> to confirm your current access.</p>
            </body></html>
            """
        )

    @app.get("/billing/cancel", response_class=HTMLResponse)
    def billing_cancel():
        return HTMLResponse(
            """
            <html><body style="font-family: sans-serif; padding: 32px; background: #0f172a; color: white;">
            <h1>Checkout Canceled</h1>
            <p>No payment was completed.</p>
            <p>You can return to Telegram and run <strong>/subscribe</strong> whenever you're ready.</p>
            </body></html>
            """
        )

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/stats")
    def stats(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        payload = _snapshot(engine)
        payload["positions"] = {position["symbol"]: position for position in _positions_payload(engine)}
        return payload

    @app.post("/backtest/run")
    def backtest_run(
        symbol: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        timeframe: Optional[str] = None,
        candles: Optional[int] = None,
        x_api_key: Optional[str] = Header(default=None),
    ):
        _authorize(auth_token, x_api_key)
        try:
            if candles is not None:
                if not symbol:
                    return run_backtest_recent_universe(
                        engine.config,
                        timeframe=timeframe,
                        candles=int(candles),
                    )
                return run_backtest_recent(
                    engine.config,
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=int(candles),
                )
            if not symbol:
                raise BacktestServiceError("A symbol is required for date-range backtests. Use `candles=500` or `candles=1000` for scanner-universe runs.")
            return run_backtest(
                engine.config,
                symbol=symbol,
                start_date=start,
                end_date=end,
                timeframe=timeframe,
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
