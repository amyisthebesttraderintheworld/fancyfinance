import pytest
import asyncio
import queue
from unittest.mock import MagicMock, AsyncMock, patch
from live_engine import LiveEngine
from common import Candle, TelegramNotifier, Position

@pytest.fixture
def mock_notifier():
    return MagicMock(spec=TelegramNotifier)

@pytest.fixture
def command_queue():
    return queue.Queue()

@pytest.fixture
def live_engine(mock_config, mock_notifier, command_queue):
    with patch('live_engine.PhemexClient') as mock_client:
        mock_client.return_value.get_account.return_value = 1.0
        return LiveEngine(mock_config, mock_notifier, command_queue)

@pytest.mark.asyncio
async def test_live_engine_safety_stop(live_engine, mock_notifier):
    # Mock current balance to trigger max daily loss
    live_engine.client.get_account.return_value = 0.5 # 50% drop from 1.0 start
    
    # Try to execute a trade
    live_engine._execute_trade("BTCUSD", 'long', 40000, 1.0, is_entry=True)
    
    # Engine should stop
    assert not live_engine.is_running
    mock_notifier.send_message.assert_called()
    assert "Max daily loss exceeded" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_live_engine_order_placement(live_engine, mock_notifier):
    # Success balance
    live_engine.client.get_account.return_value = 1.0
    
    # Execute entry
    live_engine._execute_trade("BTCUSD", 'long', 40000, 0.1, is_entry=True)
    
    # Client's place_order should be called
    live_engine.client.place_order.assert_called_with("BTCUSD", "Buy", 0.1)
    assert "BTCUSD" in live_engine.positions
    mock_notifier.send_message.assert_called()
    assert "LIVE ENTRY" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_live_engine_order_exit(live_engine, mock_notifier):
    # Mock position
    live_engine.positions["BTCUSD"] = Position("BTCUSD", 'long', 40000, 0.1, 39000, 42000, 1000)
    live_engine.client.get_account.return_value = 1.0
    
    # Execute exit
    live_engine._execute_trade("BTCUSD", 'long', 41000, 0.1, is_entry=False, reason="Take Profit")
    
    # Should place sell order
    live_engine.client.place_order.assert_called_with("BTCUSD", "Sell", 0.1)
    assert "BTCUSD" not in live_engine.positions
    mock_notifier.send_message.assert_called()
    assert "LIVE EXIT" in mock_notifier.send_message.call_args[0][0]
