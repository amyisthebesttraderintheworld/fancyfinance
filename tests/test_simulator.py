import pytest
import asyncio
import queue
import json
from unittest.mock import MagicMock, AsyncMock, patch
from simulator import Simulator
from common import Candle, TelegramNotifier

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
    await sim._handle_command(('/status', [], 12345))
    
    # Notifier should have sent status
    mock_notifier.send_message.assert_called()
    assert "Balance" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_simulator_pause_resume(sim):
    await sim._handle_command(('/pause', [], 12345))
    assert sim.is_paused
    await sim._handle_command(('/resume', [], 12345))
    assert not sim.is_paused

@pytest.mark.asyncio
async def test_simulator_process_candle_entry(sim, mock_notifier):
    candle = Candle(1704067200000, 40000, 40100, 39900, 40050, 100)
    symbol = "BTCUSD"
    
    # Mock long scanner to trigger signal
    sim.long_scanners[symbol] = MagicMock()
    # Return long signal on first call
    sim.long_scanners[symbol].update.return_value = MagicMock(
        direction='long', entry_price=40050, stop_loss=39000, take_profit=42000
    )
    
    await sim._process_candle(symbol, candle)
    
    # Should have executed entry
    assert symbol in sim.positions
    assert sim.positions[symbol].direction == 'long'
    mock_notifier.send_message.assert_called()
    assert "SIM ENTRY" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_simulator_process_candle_exit_sl(sim, mock_notifier):
    symbol = "BTCUSD"
    # Create position manually
    sim.positions[symbol] = MagicMock(
        direction='long', entry_price=40000, quantity=1.0, stop_loss=39000, take_profit=45000
    )
    
    # Price hits stop loss
    candle = Candle(1704067200000, 38500, 39000, 38000, 38500, 100)
    
    # Mock scanners to return neutral
    sim.long_scanners[symbol] = MagicMock()
    sim.long_scanners[symbol].update.return_value = None
    sim.short_scanners[symbol] = MagicMock()
    sim.short_scanners[symbol].update.return_value = None
    
    await sim._process_candle(symbol, candle)
    
    # Position should be closed
    assert symbol not in sim.positions
    mock_notifier.send_message.assert_called()
    assert "SIM EXIT" in mock_notifier.send_message.call_args[0][0]
    assert "Stop Loss" in mock_notifier.send_message.call_args[0][0]
