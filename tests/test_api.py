from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api import create_app
from common import Position


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
