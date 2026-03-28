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
        mock_client.return_value.get_positions.return_value = []
        mock_client.return_value.place_order.return_value = {"avgFillPrice": 40000.0, "orderQty": 0.1}
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
    live_engine.client.get_positions.side_effect = [
        [],
        [
            {
                "symbol": "BTCUSD",
                "side": "Buy",
                "size": 0.1,
                "avgEntryPrice": 40000.0,
                "stopLoss": 39000.0,
                "takeProfit": 42000.0,
            }
        ],
    ]

    with patch.object(live_engine, "_subscribe_symbol") as subscribe_symbol:
        # Execute entry
        live_engine._execute_trade("BTCUSD", 'long', 40000, 0.1, is_entry=True)

    # Client's place_order should be called
    live_engine.client.place_order.assert_called_with(
        "BTCUSD",
        "Buy",
        0.1,
        stop_loss=None,
        take_profit=None,
    )
    assert "BTCUSD" in live_engine.positions
    assert live_engine.trade_history[-1]["type"] == "entry"
    subscribe_symbol.assert_called_once_with("BTCUSD")
    mock_notifier.send_message.assert_called()
    assert "LIVE ENTRY" in mock_notifier.send_message.call_args[0][0]


def test_live_engine_order_placement_requires_exchange_reconciliation(live_engine, mock_notifier):
    live_engine.client.get_account.return_value = 1.0
    live_engine.client.get_positions.return_value = []

    live_engine._execute_trade("BTCUSD", "long", 40000, 0.1, is_entry=True)

    assert "BTCUSD" not in live_engine.positions
    mock_notifier.send_message.assert_called()
    assert "Order Execution Failed" in mock_notifier.send_message.call_args[0][0]

@pytest.mark.asyncio
async def test_live_engine_order_exit(live_engine, mock_notifier):
    # Mock position
    live_engine.positions["BTCUSD"] = Position("BTCUSD", 'long', 40000, 0.1, 39000, 42000, 1000)
    live_engine.client.get_account.return_value = 1.0
    live_engine.client.get_positions.side_effect = [
        [
            {
                "symbol": "BTCUSD",
                "side": "Buy",
                "size": 0.1,
                "avgEntryPrice": 40000.0,
                "stopLoss": 39000.0,
                "takeProfit": 42000.0,
            }
        ],
        []
    ]
    
    # Execute exit
    live_engine._execute_trade("BTCUSD", 'long', 41000, 0.1, is_entry=False, reason="Take Profit")
    
    # Should place sell order
    live_engine.client.place_order.assert_called_with("BTCUSD", "Sell", 0.1, reduce_only=True)
    assert "BTCUSD" not in live_engine.positions
    assert live_engine.trade_history[-1]["type"] == "exit"
    mock_notifier.send_message.assert_called()
    assert "LIVE EXIT" in mock_notifier.send_message.call_args[0][0]


def test_live_engine_reconciliation_subscribes_new_symbols(live_engine):
    live_engine.client.get_positions.return_value = [
        {
            "symbol": "BTCUSD",
            "side": "Buy",
            "size": 0.25,
            "avgEntryPrice": 40123.5,
            "stopLoss": 39000,
            "takeProfit": 42000,
        }
    ]

    with patch.object(live_engine, "_subscribe_symbol") as subscribe_symbol:
        live_engine._reconcile_positions_once()

    assert "BTCUSD" in live_engine.positions
    subscribe_symbol.assert_called_once_with("BTCUSD")


@pytest.mark.asyncio
async def test_live_engine_process_candle_does_not_open_direct_entries_when_market_scan_enabled(live_engine):
    symbol = "BTCUSD"
    live_engine.use_market_scan_engine = True
    live_engine.positions = {}
    live_engine.client.get_account.return_value = 1.0
    candle = Candle(1704067200000, 40000, 40100, 39900, 40050, 100, symbol=symbol)

    live_engine.long_scanners[symbol] = MagicMock()
    live_engine.short_scanners[symbol] = MagicMock()
    live_engine.long_scanners[symbol].update.return_value = MagicMock(
        direction="long", entry_price=40050, stop_loss=39000, take_profit=42000
    )
    live_engine.short_scanners[symbol].update.return_value = None

    with patch.object(live_engine, "_execute_trade") as execute_trade:
        await live_engine._process_candle(symbol, candle)

    execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_live_engine_run_includes_market_scan_loop(live_engine):
    live_engine._ws_handler = AsyncMock()
    live_engine._command_listener = AsyncMock()
    live_engine._market_scan_loop = AsyncMock()
    live_engine._reconciliation_loop = AsyncMock()

    await live_engine._run()

    live_engine._ws_handler.assert_awaited_once()
    live_engine._command_listener.assert_awaited_once()
    live_engine._market_scan_loop.assert_awaited_once()
    live_engine._reconciliation_loop.assert_awaited_once()
