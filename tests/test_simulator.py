import pytest
import asyncio
import queue
import json
from unittest.mock import MagicMock, AsyncMock, patch
from simulator import Simulator
from common import Candle, Position, TelegramNotifier

@pytest.fixture
def mock_notifier():
    return MagicMock(spec=TelegramNotifier)

@pytest.fixture
def command_queue():
    return queue.Queue()

@pytest.fixture
def sim(mock_config, mock_notifier, command_queue):
    return Simulator(mock_config, mock_notifier, command_queue)

@pytest.mark.asyncio
async def test_simulator_command_handler(sim, command_queue, mock_notifier):
    # Set running for listener
    sim.is_running = True
    
    # Put a command in queue
    command_queue.put(('/status', [], 12345))
    
    # Manually run handle_command since we can't easily block in tests
    with patch("simulator.requests.post", side_effect=RuntimeError("offline")):
        await sim._handle_command(('/status', [], 12345))
    
    # Notifier should have sent status after direct Telegram delivery failed.
    mock_notifier.send_message.assert_called()
    assert "Balance" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_simulator_pause_resume(sim):
    session = sim.get_user_session(12345, create=True)
    await sim._handle_command(('/pause', [], 12345))
    assert session.is_paused
    await sim._handle_command(('/resume', [], 12345))
    assert not session.is_paused

@pytest.mark.asyncio
async def test_simulator_process_candle_entry(sim, mock_notifier):
    candle = Candle(1704067200000, 40000, 40100, 39900, 40050, 100)
    symbol = "BTCUSD"
    sim.use_market_scan_engine = False
    session = sim.get_user_session(12345, create=True)
    
    # Mock long scanner to trigger signal
    session.long_scanners[symbol] = MagicMock()
    # Return long signal on first call
    session.long_scanners[symbol].update.return_value = MagicMock(
        direction='long', entry_price=40050, stop_loss=39000, take_profit=42000
    )
    session.short_scanners[symbol] = MagicMock()
    session.short_scanners[symbol].update.return_value = None
    
    await sim._process_candle(symbol, candle)
    
    # Should have executed entry
    assert symbol in session.positions
    assert session.positions[symbol].direction == 'long'
    assert session.trade_history[-1]["type"] == "entry"
    assert session.trade_history[-1]["symbol"] == symbol
    mock_notifier.send_message.assert_called()
    assert "SIM ENTRY" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_simulator_process_candle_exit_sl(sim, mock_notifier):
    symbol = "BTCUSD"
    sim.use_market_scan_engine = False
    session = sim.get_user_session(12345, create=True)
    # Create position manually
    session.positions[symbol] = MagicMock(
        direction='long', entry_price=40000, quantity=1.0, stop_loss=39000, take_profit=45000
    )
    
    # Price hits stop loss
    candle = Candle(1704067200000, 38500, 39000, 38000, 38500, 100)
    
    # Mock scanners to return neutral
    session.long_scanners[symbol] = MagicMock()
    session.long_scanners[symbol].update.return_value = None
    session.short_scanners[symbol] = MagicMock()
    session.short_scanners[symbol].update.return_value = None
    
    await sim._process_candle(symbol, candle)
    
    # Position should be closed
    assert symbol not in session.positions
    assert session.trade_history[-1]["type"] == "exit"
    assert session.trade_history[-1]["reason"] == "Stop Loss"
    mock_notifier.send_message.assert_called()
    assert "SIM EXIT" in mock_notifier.send_message.call_args[0][0]
    assert "Stop Loss" in mock_notifier.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_simulator_unlock_api_command(sim):
    sim.db.get_user_api_keys = MagicMock(return_value={"api_key": "vault_key", "api_secret": "vault_secret"})

    with patch("simulator.requests.post", side_effect=RuntimeError("offline")):
        await sim._handle_command(('/unlock_api', ['12345', 'correct horse battery staple'], 12345))

    session = sim.get_user_session(12345, create=False)
    assert session is not None
    assert session.runtime_api_ready is True
    assert session.active_api_user_id == 12345


def test_simulator_parse_phemex_kline_row_uses_correct_ohlcv_columns(sim):
    row = [1774433940, 60, 713869000, 713984000, 714100000, 713900000, 714050000, 411561, 576447970]

    candle = sim._parse_candle("BTCUSD", row)

    assert candle is not None
    assert candle.symbol == "BTCUSD"
    assert candle.open == 71398.4
    assert candle.high == 71410.0
    assert candle.low == 71390.0
    assert candle.close == 71405.0
    assert candle.volume == 411561.0


@pytest.mark.asyncio
async def test_simulator_positions_command_reports_open_positions(sim, mock_notifier):
    session = sim.get_user_session(12345, create=True)
    session.positions["BTCUSD"] = MagicMock(
        direction="long",
        entry_price=40000.0,
        quantity=0.5,
        stop_loss=39000.0,
        take_profit=42000.0,
    )

    with patch("simulator.requests.post", side_effect=RuntimeError("offline")):
        await sim._handle_command(("/positions", [], 12345))

    mock_notifier.send_message.assert_called()
    message = mock_notifier.send_message.call_args[0][0]
    assert "Open Positions" in message
    assert "BTCUSD" in message


@pytest.mark.asyncio
async def test_simulator_set_balance_is_isolated_per_user(sim):
    await sim._handle_command(("/set_balance", ["100"], 12345))
    await sim._handle_command(("/status", [], 67890))

    primary = sim.get_user_session(12345, create=False)
    secondary = sim.get_user_session(67890, create=False)

    assert primary is not None
    assert secondary is not None
    assert primary.balance == 100.0
    assert primary.reference_balance == 100.0
    assert secondary.balance == sim.initial_balance
    assert secondary.reference_balance == sim.initial_balance


@pytest.mark.asyncio
async def test_simulator_tracks_latest_market_price_while_session_is_paused(sim):
    session = sim.get_user_session(12345, create=True)
    session.is_paused = True
    candle = Candle(1704067200000, 40000, 40100, 39900, 40050, 100)

    await sim._process_candle("BTCUSD", candle)

    assert sim.get_latest_market_price("BTCUSD") == 40050.0


@pytest.mark.asyncio
async def test_simulator_market_tick_updates_position_mark_and_upnl(sim):
    session = sim.get_user_session(12345, create=True)
    session.positions["BTCUSD"] = Position(
        symbol="BTCUSD",
        direction="long",
        entry_price=40000.0,
        quantity=0.5,
        stop_loss=39000.0,
        take_profit=42000.0,
        open_time=1704067200000,
    )

    await sim._handle_ws_message({"market24h_p": {"symbol": "BTCUSD", "closeRp": "40120.5"}})

    position = session.positions["BTCUSD"]
    assert sim.get_latest_market_price("BTCUSD") == 40120.5
    assert position.mark_price == 40120.5
    assert position.current_pnl == pytest.approx(60.25)


def test_simulator_scan_market_candidates_builds_fang_entry_plans(sim):
    sim.balance = 500.0
    sim.positions = {}

    expected_plan = {
        "symbol": "BTCUSDT",
        "direction": "long",
        "price": 40000.0,
        "quantity": 0.02,
        "stop_loss": 39200.0,
        "take_profit": 41600.0,
    }

    with patch(
        "simulator.run_market_scan",
        return_value=[({"inst_id": "BTCUSDT", "price": 40000.0, "score": 142}, "LONG")],
    ) as run_scan_mock:
        with patch("simulator.build_entry_plan", return_value=expected_plan) as build_plan_mock:
            plans = sim._scan_market_candidates()

    assert plans == [expected_plan]
    run_scan_mock.assert_called_once()
    build_plan_mock.assert_called_once()
