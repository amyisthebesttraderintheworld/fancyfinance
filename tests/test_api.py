from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api
from api import create_app
from common import Position
from dashboard_access import generate_member_dashboard_token


def _build_engine(sample_config):
    config = dict(sample_config)
    config["email"] = {"confirm_webhook_url": "https://example.com/webhook"}
    config["phemex"] = dict(sample_config["phemex"])
    config["phemex"]["scan_all_symbols"] = True
    config["phemex"]["market_type"] = "all"

    db = MagicMock()
    db.get_recent_trades.return_value = [
        {
            "symbol": "BTCUSD",
            "direction": "long",
            "price": 42000.0,
            "qty": 0.1,
            "type": "exit",
            "pnl": 125.5,
            "created_at": "2026-03-24T23:00:00+00:00",
        }
    ]
    db.get_user_summary.return_value = {
        "total": 2,
        "verified": 1,
        "unverified": 1,
        "with_api_keys": 1,
        "recent": [
            {
                "telegram_id": 1,
                "username": "amy",
                "first_name": "Amy",
                "email": "amy@example.com",
                "pending_email": None,
                "is_verified": True,
                "created_at": "2026-03-24T22:00:00+00:00",
                "updated_at": "2026-03-24T22:10:00+00:00",
            }
        ],
    }
    db.url = "https://example.supabase.co"
    db.key = "service-role"
    db.client = object()
    db.cipher = SimpleNamespace(status="configured", using_fallback_key=False)

    engine = SimpleNamespace()
    engine.config = config
    engine.exchange_id = "phemex"
    engine.is_running = True
    engine.is_paused = False
    engine.balance = 10125.5
    engine.symbols = ["BTCUSD", "ETHUSD"]
    engine.positions = {
        "BTCUSD": Position(
            symbol="BTCUSD",
            direction="long",
            entry_price=42000.0,
            quantity=0.1,
            stop_loss=41000.0,
            take_profit=43500.0,
            open_time=1711320000000,
        )
    }
    engine.trade_history = [{"symbol": "BTCUSD", "pnl": 125.5, "timestamp": 1711321200}]
    engine.command_queue = SimpleNamespace(qsize=lambda: 3)
    engine.safety_paused_until = 0
    engine._websocket = object()
    engine.db = db
    engine.stop = MagicMock()
    return engine


def test_dashboard_page_renders(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "FancyFinance Control Center" in response.text


def test_dashboard_data_requires_auth(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/data")

    assert response.status_code == 401


def test_dashboard_data_returns_live_payload(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/data", headers={"x-api-key": "secret-token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["symbol_count"] == 2
    assert payload["performance"]["realized_pnl"] == 125.5
    assert payload["users"]["total"] == 2
    assert payload["positions"][0]["symbol"] == "BTCUSD"


def test_dashboard_data_accepts_member_token_for_read_only_payload(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/data", headers={"x-api-key": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["member_access"] is True
    assert payload["user_id"] == 12345
    assert payload["snapshot"]["balance"] is None
    assert payload["positions"][0]["symbol"] == "BTCUSD"


def test_member_dashboard_page_renders(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/member")

    assert response.status_code == 200
    assert "FancyFinance Member Dashboard" in response.text
    assert "Telegram-issued dashboard token" in response.text


def test_member_dashboard_data_requires_valid_token(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/member-data")

    assert response.status_code == 401


def test_member_dashboard_data_returns_read_only_payload(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/member-data", params={"access": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["member_access"] is True
    assert payload["user_id"] == 12345
    assert payload["snapshot"]["balance"] is None
    assert payload["users"] == {}
    assert payload["positions"][0]["symbol"] == "BTCUSD"


def test_backtest_run_endpoint_returns_report(sample_config, monkeypatch):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    monkeypatch.setattr(
        api,
        "run_backtest",
        lambda config, symbol, start_date=None, end_date=None, timeframe=None: {
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "start_date": start_date or "2024-01-01",
            "end_date": end_date or "2024-01-31",
            "candles": 500,
            "report": {"final_balance": 10500.0, "total_return": 5.0},
        },
    )

    response = client.post(
        "/backtest/run",
        params={"symbol": "BTCUSD", "start": "2024-01-01", "end": "2024-01-31", "timeframe": "1m"},
        headers={"x-api-key": "secret-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSD"
    assert payload["report"]["final_balance"] == 10500.0


def test_backtest_run_endpoint_supports_recent_candle_mode(sample_config, monkeypatch):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    monkeypatch.setattr(
        api,
        "run_backtest_recent",
        lambda config, symbol, timeframe=None, candles=500: {
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "start_date": "2026-03-24 00:00:00",
            "end_date": "2026-03-24 08:19:00",
            "candles": candles,
            "window": f"latest_{candles}_candles",
            "report": {"final_balance": 10250.0, "total_return": 2.5},
        },
    )

    response = client.post(
        "/backtest/run",
        params={"symbol": "BTCUSD", "timeframe": "5m", "candles": 1000},
        headers={"x-api-key": "secret-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSD"
    assert payload["candles"] == 1000
    assert payload["window"] == "latest_1000_candles"


def test_backtest_run_endpoint_supports_scanner_universe_recent_mode(sample_config, monkeypatch):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    monkeypatch.setattr(
        api,
        "run_backtest_recent_universe",
        lambda config, timeframe=None, candles=500: {
            "symbol": "SCANNER_UNIVERSE",
            "scope": "universe",
            "scope_label": "scanner universe",
            "timeframe": timeframe or "1m",
            "start_date": "2026-03-24 00:00:00",
            "end_date": "2026-03-24 08:19:00",
            "candles": candles,
            "window": f"latest_{candles}_candles",
            "symbols": ["BTCUSD", "ETHUSD"],
            "successful_symbols": 2,
            "failed_symbols": [],
            "top_symbols": [{"symbol": "BTCUSD", "total_return": 5.0}],
            "capital_model": "Each asset ran independently with the same starting balance.",
            "report": {"final_balance": 20500.0, "total_return": 2.5},
        },
    )

    response = client.post(
        "/backtest/run",
        params={"timeframe": "5m", "candles": 1000},
        headers={"x-api-key": "secret-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "universe"
    assert payload["candles"] == 1000
