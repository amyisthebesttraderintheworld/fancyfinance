from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api
from api import create_app
from common import Position
from dashboard_access import generate_member_dashboard_token
from strategy_profile import normalize_strategy_profile


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
    db.get_user.return_value = {
        "telegram_id": 12345,
        "username": "amy",
        "first_name": "Amy",
        "email": "amy@example.com",
        "is_verified": True,
    }
    db.get_membership_summary.return_value = {
        "tier": "pro",
        "status": "active",
        "source": "stripe",
        "can_live": True,
        "can_simulation": True,
    }
    db.get_user_api_key_status.return_value = {
        "configured": True,
        "zero_knowledge": True,
    }
    db.get_user_member_state.return_value = {"live_enabled": False}
    db.store_user_member_state = MagicMock()
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
    engine.trade_history = [
        {
            "symbol": "BTCUSD",
            "direction": "long",
            "price": 42000.0,
            "qty": 0.1,
            "type": "exit",
            "pnl": 125.5,
            "created_at": "2026-03-25T12:05:00+00:00",
            "timestamp": 1742904300000,
        }
    ]
    engine.session_started_at = "2026-03-25T12:00:00+00:00"
    engine.command_queue = SimpleNamespace(qsize=lambda: 3)
    engine.safety_paused_until = 0
    engine._websocket = object()
    engine.active_api_user_id = 12345
    engine._runtime_api_ready = lambda: True
    engine.db = db
    engine.stop = MagicMock()
    return engine


def _build_user_scoped_engine(sample_config):
    config = dict(sample_config)
    config["mode"] = "simulation"
    config["phemex"] = dict(sample_config["phemex"])

    sessions = {
        12345: SimpleNamespace(
            user_id=12345,
            balance=1200.0,
            positions={
                "BTCUSD": Position(
                    symbol="BTCUSD",
                    direction="long",
                    entry_price=42000.0,
                    quantity=0.1,
                    stop_loss=41000.0,
                    take_profit=43500.0,
                    open_time=1711320000000,
                )
            },
            trade_history=[
                {
                    "user_id": 12345,
                    "symbol": "BTCUSD",
                    "direction": "long",
                    "price": 42000.0,
                    "qty": 0.1,
                    "type": "exit",
                    "pnl": 125.5,
                    "created_at": "2026-03-25T12:05:00+00:00",
                    "timestamp": 1742904300000,
                }
            ],
            is_paused=False,
            safety_paused_until=0,
            session_started_at="2026-03-25T12:00:00+00:00",
        ),
        67890: SimpleNamespace(
            user_id=67890,
            balance=300.0,
            positions={
                "ETHUSD": Position(
                    symbol="ETHUSD",
                    direction="short",
                    entry_price=2500.0,
                    quantity=0.2,
                    stop_loss=2550.0,
                    take_profit=2400.0,
                    open_time=1711320000001,
                )
            },
            trade_history=[
                {
                    "user_id": 67890,
                    "symbol": "ETHUSD",
                    "direction": "short",
                    "price": 2500.0,
                    "qty": 0.2,
                    "type": "entry",
                    "created_at": "2026-03-25T12:06:00+00:00",
                    "timestamp": 1742904360000,
                }
            ],
            is_paused=True,
            safety_paused_until=0,
            session_started_at="2026-03-25T12:01:00+00:00",
        ),
    }

    def get_user_session(user_id, create=False):
        return sessions.get(user_id)

    def list_user_sessions():
        return list(sessions.values())

    db = MagicMock()
    db.get_recent_trades.return_value = []
    db.get_user_summary.return_value = {"total": 2, "verified": 2, "unverified": 0, "with_api_keys": 0, "recent": []}
    db.get_user.side_effect = lambda user_id: {
        "telegram_id": user_id,
        "username": "user",
        "first_name": "User",
        "email": "user@example.com",
        "is_verified": True,
    }
    db.get_membership_summary.side_effect = lambda user_id, username="", first_name="": {
        "tier": "pro",
        "status": "active",
        "source": "stripe",
        "can_live": True,
        "can_simulation": True,
    }
    db.get_user_api_key_status.side_effect = lambda user_id: {
        "configured": True,
        "zero_knowledge": True,
    }
    db.get_user_member_state.side_effect = lambda user_id: {"live_enabled": not sessions[user_id].is_paused}
    db.store_user_member_state = MagicMock()
    db.url = "https://example.supabase.co"
    db.key = "service-role"
    db.client = object()
    db.cipher = SimpleNamespace(status="configured", using_fallback_key=False)

    engine = SimpleNamespace()
    engine._user_scoped_simulation = True
    engine.config = config
    engine.exchange_id = "phemex"
    engine.is_running = True
    engine.is_paused = False
    engine.balance = 0.0
    engine.symbols = ["BTCUSD", "ETHUSD"]
    engine.positions = {}
    engine.trade_history = []
    engine.session_started_at = "2026-03-25T12:00:00+00:00"
    engine.command_queue = SimpleNamespace(qsize=lambda: 1)
    engine.safety_paused_until = 0
    engine._websocket = object()
    engine.db = db
    engine.get_user_session = get_user_session
    engine.list_user_sessions = list_user_sessions
    engine.stop = MagicMock()
    return engine


def test_dashboard_page_renders(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "FancyFinance Control Center" in response.text
    assert '/dashboard/assets/logo.png' in response.text
    assert '/favicon.ico' in response.text
    assert '/privacy-policy' in response.text
    assert '/terms-of-use' in response.text
    assert 'fancyfinance_api_token' in response.text
    assert '<option value="500">500</option>' in response.text
    assert '<option value="1000">1000</option>' in response.text


def test_dashboard_logo_route_serves_png(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/assets/logo.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0


def test_favicon_route_serves_logo(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0


def test_privacy_policy_route_is_public(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/privacy-policy")

    assert response.status_code == 200
    assert "Fancy Finance Privacy Policy" in response.text
    assert "Last updated: March 25, 2026" in response.text


def test_terms_of_use_route_is_public(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/terms-of-use")

    assert response.status_code == 200
    assert "Fancy Finance Terms of Use" in response.text
    assert "Last updated: March 25, 2026" in response.text


def test_terms_of_service_alias_redirects(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/terms-of-service", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/terms-of-use"


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
    assert payload["portfolio"]["marked_equity"] == 10125.5
    assert payload["activity"][0]["source"] == "trade"
    assert payload["users"]["total"] == 2
    assert payload["positions"][0]["symbol"] == "BTCUSD"
    assert payload["positions"][0]["entry_time"] == 1711320000000
    assert payload["positions"][0]["mark_price"] is None
    assert payload["recent_trades"][0]["type"] == "exit"


def test_dashboard_data_filters_db_trades_to_current_session(sample_config):
    engine = _build_engine(sample_config)
    engine.trade_history = []
    engine.session_started_at = "2026-03-25T12:00:00+00:00"
    engine.db.get_recent_trades.return_value = []
    app = create_app(engine, auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/data", headers={"x-api-key": "secret-token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_trades"] == []
    assert payload["performance"]["realized_pnl"] == 0.0
    engine.db.get_recent_trades.assert_called_once_with(limit=20, since="2026-03-25T12:00:00+00:00")


def test_dashboard_data_accepts_member_token_for_read_only_payload(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/data", headers={"x-api-key": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["member_access"] is True
    assert payload["user_id"] == 12345
    assert payload["snapshot"]["balance"] == 10125.5
    assert payload["portfolio"]["balance"] == 10125.5
    assert payload["positions"][0]["symbol"] == "BTCUSD"
    assert payload["positions"][0]["entry_time"] == 1711320000000
    assert payload["positions"][0]["mark_price"] is None


def test_member_dashboard_page_renders(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/member")

    assert response.status_code == 200
    assert "FancyFinance Member Dashboard" in response.text
    assert "signed access link binds the page to your Telegram ID" in response.text


def test_member_dashboard_page_uses_api_token_fallback_and_shows_positions(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/member")

    assert response.status_code == 200
    assert 'const TOKEN_KEYS = ["fancyfinance_member_dashboard_token", "fancyfinance_api_token"];' in response.text
    assert 'id="positions-panel" style=""' in response.text
    assert 'id="setup-panel" style="display:none;"' in response.text
    assert 'id="member-live-toggle-btn"' in response.text


def test_dashboard_redirects_member_access_links_to_member_route(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard", params={"access": token}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"/dashboard/member?access={token}"


def test_member_dashboard_query_token_sets_cookie_and_redirects_clean(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/member", params={"access": token}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard/member"
    assert f"{api.MEMBER_ACCESS_COOKIE}=" in response.headers["set-cookie"]


def test_dashboard_page_uses_member_token_fallback(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'const BOOTSTRAP_ENDPOINT = "/dashboard/bootstrap";' in response.text
    assert 'const TOKEN_KEYS = ["fancyfinance_api_token", "fancyfinance_member_dashboard_token"];' in response.text


def test_dashboard_bootstrap_returns_public_summary(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.get("/dashboard/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["public_bootstrap"] is True
    assert payload["snapshot"]["balance"] == 10125.5
    assert payload["runtime"]["engine_status"] == "running"
    assert payload["positions"] == []
    assert payload["recent_trades"] == []
    assert payload["portfolio"]["notional_exposure"] == 4200.0
    assert payload["performance"]["realized_pnl"] == 125.5


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
    assert payload["snapshot"]["balance"] == 10125.5
    assert payload["users"] == {}
    assert payload["positions"][0]["symbol"] == "BTCUSD"
    assert payload["positions"][0]["entry_time"] == 1711320000000
    assert payload["positions"][0]["mark_price"] is None
    assert payload["activity"][0]["source"] == "trade"
    assert payload["member"]["telegram_id"] == 12345
    assert payload["member"]["can_live"] is True


def test_member_dashboard_data_accepts_cookie_session(sample_config):
    app = create_app(_build_user_scoped_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    priming = client.get("/dashboard/member", params={"access": token}, follow_redirects=False)
    assert priming.status_code == 307

    response = client.get("/dashboard/member-data")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == 12345
    assert payload["member"]["telegram_id"] == 12345


def test_member_dashboard_data_returns_user_scoped_positions_and_trades(sample_config):
    app = create_app(_build_user_scoped_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/member-data", params={"access": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == 12345
    assert payload["snapshot"]["open_positions"] == 1
    assert payload["snapshot"]["balance"] == 1200.0
    assert payload["portfolio"]["balance"] == 1200.0
    assert payload["positions"] == [
        {
            "symbol": "BTCUSD",
            "direction": "long",
            "entry_price": 42000.0,
            "quantity": 0.1,
            "stop_loss": 41000.0,
            "take_profit": 43500.0,
            "entry_time": 1711320000000,
            "mark_price": None,
            "current_pnl": None,
        }
    ]
    assert payload["recent_trades"][0]["symbol"] == "BTCUSD"


def test_member_dashboard_data_uses_latest_market_price_for_live_upnl(sample_config):
    engine = _build_user_scoped_engine(sample_config)
    engine.get_user_session(12345).reference_balance = 100.0
    engine.get_latest_market_price = lambda symbol: 42150.0 if symbol == "BTCUSD" else None
    app = create_app(engine, auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    response = client.get("/dashboard/member-data", params={"access": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["positions"][0]["mark_price"] == 42150.0
    assert payload["portfolio"]["live_upnl"] == 15.0
    assert payload["portfolio"]["marked_equity"] == 1215.0
    assert payload["portfolio"]["reference_balance"] == 100.0
    assert payload["portfolio"]["session_delta"] == 1115.0
    assert payload["portfolio"]["marked_positions"] == 1
    assert payload["portfolio"]["winning_positions"] == 1


def test_member_live_toggle_updates_user_scoped_session(sample_config):
    engine = _build_user_scoped_engine(sample_config)
    app = create_app(engine, auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    client.get("/dashboard/member", params={"access": token}, follow_redirects=False)

    disable_response = client.post("/dashboard/member/live-toggle", json={"enabled": False})

    assert disable_response.status_code == 200
    assert engine.get_user_session(12345).is_paused is True
    assert disable_response.json()["member"]["effective_enabled"] is False

    enable_response = client.post("/dashboard/member/live-toggle", json={"enabled": True})

    assert enable_response.status_code == 200
    assert engine.get_user_session(12345).is_paused is False
    assert enable_response.json()["member"]["effective_enabled"] is True
    engine.db.store_user_member_state.assert_called()


def test_member_live_toggle_resumes_live_engine_for_matching_runtime_owner(sample_config):
    engine = _build_engine(sample_config)
    engine.config["mode"] = "live"
    engine.is_paused = True
    app = create_app(engine, auth_token="secret-token")
    client = TestClient(app)
    token = generate_member_dashboard_token("secret-token", 12345, ttl_seconds=3600)

    client.get("/dashboard/member", params={"access": token}, follow_redirects=False)

    response = client.post("/dashboard/member/live-toggle", json={"enabled": True})

    assert response.status_code == 200
    assert engine.is_paused is False
    assert response.json()["member"]["effective_enabled"] is True


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


def test_backtest_run_endpoint_rejects_invalid_recent_candle_mode(sample_config):
    app = create_app(_build_engine(sample_config), auth_token="secret-token")
    client = TestClient(app)

    response = client.post(
        "/backtest/run",
        params={"symbol": "BTCUSD", "timeframe": "5m", "candles": 750},
        headers={"x-api-key": "secret-token"},
    )

    assert response.status_code == 400
    assert "Backtest candles must be one of" in response.json()["detail"]


def test_strategy_config_endpoint_saves_member_profile(sample_config):
    engine = _build_user_scoped_engine(sample_config)
    base_profile = normalize_strategy_profile(sample_config, {})
    saved = {}

    def set_strategy_config(payload, user_id=None):
        saved["payload"] = payload
        saved["user_id"] = user_id
        return normalize_strategy_profile(sample_config, payload, current=base_profile)

    engine.get_strategy_config = lambda user_id=None: dict(base_profile)
    engine.set_strategy_config = MagicMock(side_effect=set_strategy_config)

    app = create_app(engine, auth_token="secret-token")
    client = TestClient(app)
    member_token = generate_member_dashboard_token("secret-token", 12345)

    response = client.post(
        "/strategy/config",
        json={"profile": {"timeframe": "15m", "margin": 10, "leverage": 5, "direction": "SHORT"}},
        headers={"x-api-key": member_token},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["member_access"] is True
    assert payload["strategy"]["profile"]["timeframe"] == "15m"
    assert payload["strategy"]["profile"]["margin"] == 10.0
    assert payload["strategy"]["profile"]["leverage"] == 5
    assert payload["strategy"]["profile"]["direction"] == "SHORT"
    assert saved["user_id"] == 12345
    assert saved["payload"]["timeframe"] == "15m"
