import pytest
import queue
from unittest.mock import MagicMock, AsyncMock, patch
from telegram.error import Conflict
from telegram_bot import (
    agree_command,
    backtest_command,
    dashboard_api_command,
    error_handler,
    post_init,
    start_trial_command,
    start,
    help_command,
    menu_button_handler,
    proxy_command,
    button_handler,
    set_config_command,
    verify_email_command,
    setup_api_command,
    unlock_api_command,
    subscribe_command,
    manage_subscription_command,
    plans_command,
)
import telegram_bot # to get global variables if needed

@pytest.fixture(autouse=True)
def clear_cooldowns():
    telegram_bot.bot_context.command_cooldowns.clear()
    yield
    telegram_bot.bot_context.command_cooldowns.clear()

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "tester"
    update.effective_user.first_name = "Test"
    update.effective_chat.id = 12345
    update.message.text = "/status"
    update.message.reply_text = AsyncMock()
    return update

@pytest.fixture
def mock_context():
    return MagicMock()

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    telegram_bot.settings_mgr.settings.pop("user_agreed_12345", None)
    await start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called()
    assert "IMPORTANT LEGAL" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_help_command(mock_update, mock_context):
    await help_command(mock_update, mock_context)
    # Check if a long help message was sent
    mock_update.message.reply_text.assert_called()
    assert "Available Commands" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_post_init_clears_webhook_and_starts_watchdog():
    application = MagicMock()
    application.bot = MagicMock()
    application.bot_data = {}
    scheduled_tasks = []

    def _capture_task(coro):
        scheduled_tasks.append(coro)
        coro.close()
        return MagicMock()

    with patch("telegram_bot._clear_telegram_webhook", new=AsyncMock(return_value=telegram_bot.TELEGRAM_WEBHOOK_CLEARED)) as clear_mock:
        with patch("telegram_bot.set_commands", new=AsyncMock()) as set_commands_mock:
            with patch("telegram_bot.asyncio.create_task", side_effect=_capture_task) as create_task_mock:
                await post_init(application)

    clear_mock.assert_awaited_once()
    set_commands_mock.assert_awaited_once_with(application)
    create_task_mock.assert_called_once()
    assert len(scheduled_tasks) == 1
    assert "_ownership_watchdog_task" in application.bot_data


@pytest.mark.asyncio
async def test_error_handler_recovers_from_conflict_when_webhook_cleared():
    telegram_bot._conflict_logged = False
    telegram_bot._ownership_recovery_logged = False

    application = MagicMock()
    application.bot = MagicMock()
    application.running = True
    application.stop_running = MagicMock()

    context = MagicMock()
    context.error = Conflict("webhook active")
    context.application = application

    with patch("telegram_bot._clear_telegram_webhook", new=AsyncMock(return_value=telegram_bot.TELEGRAM_WEBHOOK_CLEARED)) as clear_mock:
        await error_handler(None, context)

    clear_mock.assert_awaited_once()
    application.stop_running.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_treats_startup_polling_handoff_as_recoverable():
    telegram_bot._conflict_logged = False
    telegram_bot._ownership_recovery_logged = False

    application = MagicMock()
    application.bot = MagicMock()
    application.running = True
    application.stop_running = MagicMock()

    context = MagicMock()
    context.error = Conflict("another poller")
    context.application = application

    with patch("telegram_bot._clear_telegram_webhook", new=AsyncMock(return_value=telegram_bot.TELEGRAM_WEBHOOK_ABSENT)) as clear_mock:
        with patch("telegram_bot._polling_conflict_is_startup_handoff", return_value=True):
            await error_handler(None, context)

    clear_mock.assert_awaited_once()
    application.stop_running.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_stops_when_conflict_not_recovered():
    telegram_bot._conflict_logged = False
    telegram_bot._ownership_recovery_logged = False

    application = MagicMock()
    application.bot = MagicMock()
    application.running = True
    application.stop_running = MagicMock()

    context = MagicMock()
    context.error = Conflict("another poller")
    context.application = application

    with patch("telegram_bot._clear_telegram_webhook", new=AsyncMock(return_value=telegram_bot.TELEGRAM_WEBHOOK_FAILED)) as clear_mock:
        await error_handler(None, context)

    clear_mock.assert_awaited_once()
    application.stop_running.assert_called_once()


def test_polling_startup_delay_defaults_on_railway(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj_123")
    monkeypatch.delenv("TELEGRAM_POLLING_STARTUP_DELAY_SECONDS", raising=False)
    telegram_bot.bot_context.config = {"telegram": {"polling_enabled": True}}

    assert telegram_bot._polling_startup_delay_seconds() == 20


def test_polling_startup_delay_env_override_wins(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj_123")
    monkeypatch.setenv("TELEGRAM_POLLING_STARTUP_DELAY_SECONDS", "7")
    telegram_bot.bot_context.config = {"telegram": {"polling_enabled": True}}

    assert telegram_bot._polling_startup_delay_seconds() == 7

@pytest.mark.asyncio
async def test_proxy_command_authorized(mock_update, mock_context, mock_config):
    # Set globals for telegram_bot module
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()
    
    mock_update.message.text = "/status"
    mock_update.effective_chat.id = 12345 # Authorized in mock_config
    
    await proxy_command(mock_update, mock_context)
    
    # Check if command put in queue
    assert not telegram_bot.bot_context.command_queue.empty()
    cmd, args, chat_id, user_id = telegram_bot.bot_context.command_queue.get()
    assert cmd == "/status"
    assert chat_id == 12345
    assert user_id == 12345
    mock_update.message.reply_text.assert_called_with("Command /status queued.")

@pytest.mark.asyncio
async def test_proxy_command_requires_paid_membership_for_sim_self_service(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()
    
    mock_update.message.text = "/pause"
    mock_update.effective_chat.id = 99999
    
    await proxy_command(mock_update, mock_context)
    
    assert telegram_bot.bot_context.command_queue.empty()
    assert "Paid Membership Required" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_proxy_command_allows_paid_member_to_control_own_simulation(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()

    mock_update.message.text = "/pause"
    mock_update.effective_chat.id = 99999

    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        return_value={"can_simulation": True, "tier": "pro", "status": "active"},
    ):
        await proxy_command(mock_update, mock_context)

    assert not telegram_bot.bot_context.command_queue.empty()
    cmd, args, chat_id, user_id = telegram_bot.bot_context.command_queue.get()
    assert cmd == "/pause"
    assert args == []
    assert chat_id == 99999
    assert user_id == 12345
    mock_update.message.reply_text.assert_called_with("Command /pause queued.")


@pytest.mark.asyncio
async def test_proxy_command_status_allowed_for_non_admin(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()

    mock_update.message.text = "/status"
    mock_update.effective_chat.id = 99999

    await proxy_command(mock_update, mock_context)

    assert not telegram_bot.bot_context.command_queue.empty()
    cmd, args, chat_id, user_id = telegram_bot.bot_context.command_queue.get()
    assert cmd == "/status"
    assert chat_id == 99999
    assert user_id == 12345
    mock_update.message.reply_text.assert_called_with("Command /status queued.")


@pytest.mark.asyncio
async def test_button_handler_agree_shows_main_menu(mock_context):
    query = MagicMock()
    query.data = "agree_12345"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.chat.id = 12345
    mock_context.bot.send_message = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await button_handler(update, mock_context)

    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    assert "Trading Bot Connected" in query.edit_message_text.call_args.args[0]
    assert query.edit_message_text.call_args.kwargs["reply_markup"] is not None
    mock_context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_button_handler_agree_falls_back_to_new_message(mock_context):
    query = MagicMock()
    query.data = "agree_12345"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock(side_effect=RuntimeError("cannot edit"))
    query.message.chat.id = 12345
    mock_context.bot.send_message = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await button_handler(update, mock_context)

    query.answer.assert_called_once()
    mock_context.bot.send_message.assert_called_once()
    assert "Trading Bot Connected" in mock_context.bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_verify_email_command_success(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["user@example.com"]

    with patch.object(telegram_bot.db, "request_email_verification", return_value="123456"):
        with patch("telegram_bot.EmailService") as mock_email_service:
            mock_email_service.return_value.send_verification_email.return_value = True

            await verify_email_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "Verification Email Sent" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_verify_email_command_failure(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["user@example.com"]

    with patch.object(telegram_bot.db, "request_email_verification", return_value="123456"):
        with patch("telegram_bot.EmailService") as mock_email_service:
            mock_email_service.return_value.send_verification_email.return_value = False

            await verify_email_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "EMAIL_CONFIRM_WEBHOOK_URL" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_agree_command_sends_menu(mock_update, mock_context):
    telegram_bot.settings_mgr.settings.pop("user_agreed_12345", None)

    await agree_command(mock_update, mock_context)

    assert telegram_bot.settings_mgr.get("user_agreed_12345") is True
    assert mock_update.message.reply_text.call_count == 2
    assert "Agreement recorded" in mock_update.message.reply_text.call_args_list[0].args[0]
    assert "Trading Bot Connected" in mock_update.message.reply_text.call_args_list[1].args[0]


@pytest.mark.asyncio
async def test_menu_button_handler_routes_status(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()
    mock_update.message.text = "📊 Status"
    mock_update.effective_chat.id = 99999

    await menu_button_handler(mock_update, mock_context)

    assert not telegram_bot.bot_context.command_queue.empty()
    cmd, args, chat_id, user_id = telegram_bot.bot_context.command_queue.get()
    assert cmd == "/status"
    assert chat_id == 99999
    assert user_id == 12345


@pytest.mark.asyncio
async def test_menu_button_handler_routes_settings(mock_update, mock_context):
    mock_update.message.text = "⚙️ Settings"

    await menu_button_handler(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "Persistent Settings" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_subscribe_command_returns_subscription_page_url(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = {
        **mock_config,
        "api": {
            **mock_config["api"],
            "base_url": "https://fancyfinance-production.up.railway.app",
        },
        "stripe": {
            "display_price": "$6.99/month",
            "trial_days": 7,
            "subscribe_url": "https://fancy-bot-front.lovable.app/",
        },
    }

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345, "email": "user@example.com"}):
        await subscribe_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "https://fancyfinance-production.up.railway.app" in mock_update.message.reply_text.call_args[0][0]
    assert "Trial Pro" in mock_update.message.reply_text.call_args[0][0]
    assert "same email address you verified in Telegram" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_manage_subscription_command_returns_portal_url(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = {
        **mock_config,
        "stripe": {
            "secret_key": "sk_test_123",
            "portal_return_url": "https://example.com/dashboard",
        },
    }

    with patch.object(
        telegram_bot.db,
        "get_or_create_user",
        return_value={"telegram_id": 12345, "stripe_customer_id": "cus_123"},
    ):
        with patch("telegram_bot.StripeService") as mock_stripe:
            mock_stripe.return_value.is_portal_configured.return_value = True
            mock_stripe.return_value.create_customer_portal_session.return_value = {
                "url": "https://billing.stripe.com/session/test"
            }

            await manage_subscription_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "billing.stripe.com" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_setup_api_command_stores_zero_knowledge_vault(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["api_key_123", "api_secret_456", "correct", "horse", "battery", "staple"]
    mock_context.bot.delete_message = AsyncMock()

    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        return_value={"can_live": True, "tier": "pro", "status": "active"},
    ):
        with patch.object(telegram_bot.db, "store_user_api_keys", return_value=True) as store_mock:
            await setup_api_command(mock_update, mock_context)

    store_mock.assert_called_once_with(
        12345,
        "api_key_123",
        "api_secret_456",
        "correct horse battery staple",
        exchange="phemex",
    )
    mock_context.bot.delete_message.assert_called_once()


@pytest.mark.asyncio
async def test_unlock_api_command_queues_sensitive_request(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    telegram_bot.bot_context.command_queue = queue.Queue()
    mock_context.args = ["correct", "horse", "battery", "staple"]
    mock_context.bot.delete_message = AsyncMock()

    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        return_value={"can_live": True, "tier": "pro", "status": "active"},
    ):
        await unlock_api_command(mock_update, mock_context)

    assert not telegram_bot.bot_context.command_queue.empty()
    command, args, chat_id, user_id = telegram_bot.bot_context.command_queue.get()
    assert command == "/unlock_api"
    assert args == ["12345", "correct horse battery staple"]
    assert chat_id == 12345
    assert user_id == 12345
    mock_context.bot.delete_message.assert_called_once()


@pytest.mark.asyncio
async def test_backtest_command_returns_summary(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["BTCUSD", "1m", "500"]

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        with patch(
            "telegram_bot.run_backtest_recent",
            return_value={
                "symbol": "BTCUSD",
                "timeframe": "1m",
                "start_date": "2026-03-24 00:00:00",
                "end_date": "2026-03-24 08:19:00",
                "candles": 500,
                "window": "latest_500_candles",
                "report": {
                    "final_balance": 10500.0,
                    "total_return": 5.0,
                    "total_trades": 12,
                    "win_rate": 58.33,
                    "max_drawdown": -3.2,
                    "sharpe_ratio": 1.42,
                    "profit_factor": 1.8,
                },
            },
    ):
            await backtest_command(mock_update, mock_context)

    assert mock_update.message.reply_text.call_count == 2
    assert "Running your free backtest" in mock_update.message.reply_text.call_args_list[0].args[0]
    assert "Backtest Complete" in mock_update.message.reply_text.call_args_list[1].args[0]


@pytest.mark.asyncio
async def test_backtest_command_runs_scanner_universe_without_args(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = []

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        with patch(
            "telegram_bot.run_backtest_recent_universe",
            return_value={
                "symbol": "SCANNER_UNIVERSE",
                "scope": "universe",
                "scope_label": "scanner universe",
                "timeframe": "1m",
                "start_date": "2026-03-24 00:00:00",
                "end_date": "2026-03-24 08:19:00",
                "candles": 500,
                "window": "latest_500_candles",
                "symbols": ["BTCUSD", "ETHUSD"],
                "successful_symbols": 2,
                "failed_symbols": [],
                "top_symbols": [
                    {"symbol": "BTCUSD", "total_return": 5.0},
                    {"symbol": "ETHUSD", "total_return": 2.0},
                ],
                "capital_model": "Each asset ran independently with the same starting balance.",
                "report": {
                    "final_balance": 20500.0,
                    "total_return": 2.5,
                    "total_trades": 24,
                    "win_rate": 54.17,
                    "max_drawdown": -4.8,
                    "sharpe_ratio": 1.11,
                    "profit_factor": 1.5,
                },
            },
        ):
            await backtest_command(mock_update, mock_context)

    assert mock_update.message.reply_text.call_count == 2
    assert "all scanner-picked assets" in mock_update.message.reply_text.call_args_list[0].args[0]
    assert "Assets Tested" in mock_update.message.reply_text.call_args_list[1].args[0]


@pytest.mark.asyncio
async def test_backtest_command_shows_usage_for_invalid_args(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["BTCUSD", "ETHUSD"]

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        await backtest_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "Free Backtesting" in mock_update.message.reply_text.call_args[0][0]
    assert "scanner universe" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_backtest_command_rejects_invalid_candle_count(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = mock_config
    mock_context.args = ["BTCUSD", "1m", "750"]

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        await backtest_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "only support" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_backtest_command_supports_flag_profile(mock_update, mock_context, mock_config, monkeypatch):
    telegram_bot.bot_context.config = mock_config
    active_engine = MagicMock()
    active_engine.get_strategy_config.return_value = {
        "timeframe": "1m",
        "candles": 500,
        "min_score": 45,
        "min_signals": 1,
        "leverage": 3,
        "margin": 10.0,
        "max_margin": 30.0,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04,
        "trail_pct": 0.01,
        "max_hold": 0,
        "direction": "BOTH",
        "min_score_gap": 30,
        "cooldown": 0,
        "csv": False,
    }
    monkeypatch.setattr(telegram_bot.bot_context, "active_engine", active_engine)
    mock_context.args = [
        "--timeframe", "15m",
        "--candles", "1000",
        "--min-score", "5",
        "--min-signals", "4",
        "--leverage", "5",
        "--margin", "10",
        "--max-margin", "150",
        "--direction", "SHORT",
        "--csv",
        "BTCUSD",
    ]

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        with patch(
            "telegram_bot.run_backtest_recent",
            return_value={
                "symbol": "BTCUSD",
                "timeframe": "15m",
                "start_date": "2026-03-24 00:00:00",
                "end_date": "2026-03-24 08:19:00",
                "candles": 1000,
                "window": "latest_1000_candles",
                "csv": "symbol,return\nBTCUSD,5.0",
                "report": {
                    "final_balance": 10500.0,
                    "total_return": 5.0,
                    "total_trades": 12,
                    "win_rate": 58.33,
                    "max_drawdown": -3.2,
                    "sharpe_ratio": 1.42,
                    "profit_factor": 1.8,
                },
            },
        ) as backtest_mock:
            await backtest_command(mock_update, mock_context)

    assert mock_update.message.reply_text.call_count == 2
    assert "configured backtest" in mock_update.message.reply_text.call_args_list[0].args[0]
    assert "CSV" in mock_update.message.reply_text.call_args_list[1].args[0]
    call = backtest_mock.call_args.args
    assert call[1] == "BTCUSD"
    assert call[2] == "15m"
    assert call[3] == 1000
    assert call[4]["direction"] == "SHORT"
    assert call[4]["leverage"] == 5
    assert call[5] is True


@pytest.mark.asyncio
async def test_set_config_command_updates_active_engine_profile(mock_update, mock_context, mock_config, monkeypatch):
    telegram_bot.bot_context.config = mock_config
    active_engine = MagicMock()
    active_engine.set_strategy_config.return_value = {
        "timeframe": "15m",
        "candles": 1000,
        "min_score": 5,
        "min_signals": 4,
        "leverage": 5,
        "margin": 10.0,
        "max_margin": 150.0,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
        "trail_pct": 0.025,
        "max_hold": 72,
        "direction": "SHORT",
        "min_score_gap": 2,
        "cooldown": 2,
        "csv": True,
    }
    monkeypatch.setattr(telegram_bot.bot_context, "active_engine", active_engine)
    mock_context.args = [
        "--timeframe", "15m",
        "--candles", "1000",
        "--min-score", "5",
        "--min-signals", "4",
        "--leverage", "5",
        "--margin", "10",
        "--max-margin", "150",
        "--stop-loss-pct", "0.04",
        "--take-profit-pct", "0.08",
        "--trail-pct", "0.025",
        "--max-hold", "72",
        "--direction", "SHORT",
        "--min-score-gap", "2",
        "--cooldown", "2",
        "--csv",
    ]

    with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345}):
        await set_config_command(mock_update, mock_context)

    active_engine.set_strategy_config.assert_called_once()
    _, kwargs = active_engine.set_strategy_config.call_args
    assert kwargs["user_id"] == 12345
    message = mock_update.message.reply_text.call_args[0][0]
    assert "Strategy Updated" in message
    assert "15m" in message
    assert "SHORT" in message


@pytest.mark.asyncio
async def test_start_trial_command_unlocks_trial_pro(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = {
        **mock_config,
        "api": {
            **mock_config["api"],
            "auth_token": "secret-token",
            "base_url": "https://fancyfinance-production.up.railway.app",
        },
        "stripe": {"trial_days": 7},
    }

    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        side_effect=[
            {"tier": "free", "status": "free", "can_backtest": True, "can_simulation": False, "can_live": False},
            {"tier": "trial_pro", "status": "trial_pro", "can_backtest": True, "can_simulation": True, "can_live": True},
        ],
    ):
        with patch.object(telegram_bot.db, "get_or_create_user", return_value={"telegram_id": 12345, "trial_started_at": None}):
            with patch.object(telegram_bot.db, "start_trial_membership", return_value={"telegram_id": 12345, "membership_tier": "trial_pro"}):
                await start_trial_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    message = mock_update.message.reply_text.call_args[0][0]
    assert "Trial Pro unlocked" in message
    assert "/dashboard_login" in message


@pytest.mark.asyncio
async def test_dashboard_api_command_returns_member_link(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = {
        **mock_config,
        "api": {
            **mock_config["api"],
            "auth_token": "secret-token",
            "base_url": "https://fancyfinance-production.up.railway.app",
        },
    }
    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        return_value={"tier": "trial_pro", "status": "trial_pro", "can_backtest": True, "can_simulation": True, "can_live": True},
    ):
        with patch("telegram_bot.generate_member_dashboard_token", return_value="signed-token"):
            await dashboard_api_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    message = mock_update.message.reply_text.call_args[0][0]
    assert "`signed-token`" in message
    assert "/dashboard?access=signed-token" in message
    assert "https://fancyfinance-production.up.railway.app" in message
    assert "/dashboard_login" in message


@pytest.mark.asyncio
async def test_plans_command_shows_trial_pro_status(mock_update, mock_context, mock_config):
    telegram_bot.bot_context.config = {
        **mock_config,
        "stripe": {
            "display_price": "$6.99/month",
            "trial_days": 7,
        },
    }

    with patch.object(
        telegram_bot.db,
        "get_membership_summary",
        return_value={
            "tier": "trial_pro",
            "status": "trial_pro",
            "expires_at": "2026-04-01T00:00:00+00:00",
            "can_backtest": True,
            "can_simulation": True,
            "can_live": True,
            "source": "stripe",
        },
    ):
        await plans_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    message = mock_update.message.reply_text.call_args[0][0]
    assert "7-day Trial Pro" in message
    assert "Trial Pro" in message
