from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException

from fancyfinance import APP_NAME, __version__


def _authorize(expected_token: Optional[str], provided_token: Optional[str]):
    if expected_token and provided_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _trade_count(engine) -> int:
    if hasattr(engine, "trade_history"):
        return len(engine.trade_history)
    if hasattr(engine, "trades"):
        return len(engine.trades)
    return 0


def _snapshot(engine):
    return {
        "app": APP_NAME,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": engine.config.get("mode"),
        "exchange": engine.exchange_id,
        "running": engine.is_running,
        "paused": engine.is_paused,
        "balance": engine.balance,
        "initial_balance": engine.config.get("backtest", {}).get("initial_balance"),
        "symbols": engine.symbols,
        "open_positions": len(engine.positions),
        "trade_count": _trade_count(engine),
    }


def create_app(engine, auth_token: Optional[str] = None) -> FastAPI:
    app = FastAPI(title=f"{APP_NAME} API", version=__version__)

    @app.get("/health")
    def health(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        return {"status": "ok", **_snapshot(engine)}

    @app.get("/stats")
    def stats(x_api_key: Optional[str] = Header(default=None)):
        _authorize(auth_token, x_api_key)
        payload = _snapshot(engine)
        payload["positions"] = {
            symbol: {
                "direction": position.direction,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
            }
            for symbol, position in engine.positions.items()
        }
        return payload

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
    port = int(api_config.get("port", 8000))
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
