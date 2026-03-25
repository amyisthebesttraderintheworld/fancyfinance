import unittest
from unittest.mock import MagicMock, patch
import datetime
import time
from argparse import Namespace

# Temporarily add bots to path to allow import
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../bots'))

# We need to import the modules to be tested
from bots import live_bot
from core import bot_core


class LoopStop(Exception):
    pass


class TestScanOne(unittest.TestCase):

    @patch('core.bot_core.logging.basicConfig') # To prevent it from interfering with the mock
    @patch('core.bot_core.logger')
    def test_scan_one_error_handling(self, mock_logger, mock_basic_config):
        # 1. Setup Mocks
        mock_scanner_module = MagicMock()
        
        # Mock tickers
        mock_tickers = [
            {'symbol': 'BTCUSDT', 'turnoverRv': '2000000'},
            {'symbol': 'ETHUSDT', 'turnoverRv': '3000000'},
            {'symbol': 'SOLUSDT', 'turnoverRv': '500000'}, # This one will be filtered out by volume
            {'symbol': 'ADAUSDT', 'turnoverRv': '4000000'}, # This one will raise an exception
        ]
        mock_scanner_module.get_tickers.return_value = mock_tickers

        # Mock analyse function
        def mock_analyse(ticker, cfg, no_ai, no_entity, _):
            if ticker['symbol'] == 'ADAUSDT':
                raise ValueError("Analysis failed for ADA")
            return {'inst_id': ticker['symbol'], 'score': 150, 'price': 50000}
            
        mock_scanner_module.analyse.side_effect = mock_analyse

        # Mock args and cfg
        mock_args = Namespace(no_ai=False, no_entity=False, direction='BOTH')
        mock_cfg = {
            'MIN_VOLUME': 1000000,
            'MAX_WORKERS': 2,
            'RATE_LIMIT_RPS': 10,
            'SYMBOLS': None
        }

        # 2. Call the function
        results = bot_core._scan_one(mock_scanner_module, 'LONG', mock_cfg, mock_args, show_progress=False)

        # 3. Assertions
        # Check that we have 2 results (BTC and ETH)
        self.assertEqual(len(results), 2)
        
        # Check that the results are correct
        result_symbols = {r['inst_id'] for r in results}
        self.assertIn('BTCUSDT', result_symbols)
        self.assertIn('ETHUSDT', result_symbols)
        self.assertNotIn('SOLUSDT', result_symbols)
        self.assertNotIn('ADAUSDT', result_symbols)

        # Check that logger.error was called for the failed analysis
        mock_logger.error.assert_called_once_with(
            "Error analyzing ticker ADAUSDT: Analysis failed for ADA",
            exc_info=True
        )

class TestLiveRuntimeConfig(unittest.TestCase):
    def setUp(self):
        self._orig_direction = bot_core.DIRECTION
        self._orig_min_score = bot_core.MIN_SCORE
        self._orig_min_score_gap = bot_core.MIN_SCORE_GAP
        self._orig_timeframe = bot_core.TIMEFRAME
        self._orig_min_volume = bot_core.MIN_VOLUME
        self._orig_workers = bot_core.MAX_WORKERS
        self._orig_rate_limit = bot_core.RATE_LIMIT_RPS
        self._orig_scan_interval = bot_core.SCAN_INTERVAL

    def tearDown(self):
        bot_core.DIRECTION = self._orig_direction
        bot_core.MIN_SCORE = self._orig_min_score
        bot_core.MIN_SCORE_GAP = self._orig_min_score_gap
        bot_core.TIMEFRAME = self._orig_timeframe
        bot_core.MIN_VOLUME = self._orig_min_volume
        bot_core.MAX_WORKERS = self._orig_workers
        bot_core.RATE_LIMIT_RPS = self._orig_rate_limit
        bot_core.SCAN_INTERVAL = self._orig_scan_interval

    @patch.dict(os.environ, {"BOT_ENABLED": "true"}, clear=False)
    def test_resolve_live_runtime_config_uses_dashboard_overrides(self):
        args = Namespace(
            direction="BOTH",
            min_score=125,
            min_score_gap=30,
            timeframe="4H",
            min_vol=1_000_000,
            workers=100,
            rate=50.0,
            interval=300,
        )

        runtime = live_bot._resolve_live_runtime_config(
            args,
            {
                "enabled": True,
                "direction": "short",
                "min_score": "140",
                "min_score_gap": "18",
                "timeframe": "1h",
                "min_volume": "2500000",
                "workers": "42",
                "rate_limit_rps": "12.5",
                "interval": "180",
            },
        )

        self.assertEqual(runtime.direction, "SHORT")
        self.assertEqual(runtime.min_score, 140)
        self.assertEqual(runtime.min_score_gap, 18)
        self.assertEqual(runtime.timeframe, "1H")
        self.assertEqual(runtime.min_volume, 2_500_000)
        self.assertEqual(runtime.workers, 42)
        self.assertEqual(runtime.rate_limit_rps, 12.5)
        self.assertEqual(runtime.interval, 180)
        self.assertTrue(runtime.enabled)

    def test_apply_runtime_config_updates_args_and_bot_core(self):
        args = Namespace(
            direction="BOTH",
            min_score=125,
            min_score_gap=30,
            timeframe="4H",
            min_vol=1_000_000,
            workers=100,
            rate=50.0,
            interval=300,
        )
        runtime = live_bot.LiveRuntimeConfig(
            enabled=True,
            direction="LONG",
            min_score=150,
            min_score_gap=12,
            timeframe="1H",
            min_volume=3_000_000,
            workers=24,
            rate_limit_rps=8.5,
            interval=90,
        )

        live_bot._apply_runtime_config(args, runtime)

        self.assertEqual(args.direction, "LONG")
        self.assertEqual(args.min_score, 150)
        self.assertEqual(args.min_score_gap, 12)
        self.assertEqual(args.timeframe, "1H")
        self.assertEqual(args.min_vol, 3_000_000)
        self.assertEqual(args.workers, 24)
        self.assertEqual(args.rate, 8.5)
        self.assertEqual(args.interval, 90)
        self.assertEqual(bot_core.DIRECTION, "LONG")
        self.assertEqual(bot_core.MIN_SCORE, 150)
        self.assertEqual(bot_core.MIN_SCORE_GAP, 12)
        self.assertEqual(bot_core.TIMEFRAME, "1H")
        self.assertEqual(bot_core.MIN_VOLUME, 3_000_000)
        self.assertEqual(bot_core.MAX_WORKERS, 24)
        self.assertEqual(bot_core.RATE_LIMIT_RPS, 8.5)
        self.assertEqual(bot_core.SCAN_INTERVAL, 90)

    def test_next_engine_wait_seconds_caps_to_maintenance_window(self):
        self.assertEqual(live_bot._next_engine_wait_seconds(0.0, 300, now=100.0), 60.0)
        self.assertEqual(live_bot._next_engine_wait_seconds(100.0, 300, now=100.0), 60.0)
        self.assertEqual(live_bot._next_engine_wait_seconds(100.0, 45, now=100.0), 45.0)
        self.assertEqual(live_bot._next_engine_wait_seconds(100.0, 45, now=170.0), 0.0)

    def test_next_loop_wait_seconds_uses_skip_backoff_when_due_scan_is_skipped(self):
        self.assertEqual(
            live_bot._next_loop_wait_seconds(100.0, 300, scan_due=True, scan_executed=False, now=500.0),
            live_bot.LOOP_SKIP_BACKOFF_SECONDS,
        )
        self.assertEqual(
            live_bot._next_loop_wait_seconds(100.0, 10, scan_due=True, scan_executed=False, now=500.0),
            10.0,
        )


class TestBotLoopHardening(unittest.TestCase):
    def setUp(self):
        self._orig_no_tui = live_bot._no_tui
        self._orig_loop_state_key = live_bot._loop_state_key
        self._orig_loop_state_logged_at = live_bot._loop_state_logged_at
        live_bot._no_tui = True
        live_bot._loop_state_key = ""
        live_bot._loop_state_logged_at = 0.0
        live_bot._slot_available_event.clear()

    def tearDown(self):
        live_bot._no_tui = self._orig_no_tui
        live_bot._loop_state_key = self._orig_loop_state_key
        live_bot._loop_state_logged_at = self._orig_loop_state_logged_at
        live_bot._slot_available_event.clear()

    @patch.object(live_bot, "tui_log")
    def test_log_loop_state_once_throttles_duplicates_until_cleared(self, mock_tui_log):
        self.assertTrue(live_bot._log_loop_state_once("disabled", "Bot is DISABLED.", now=100.0))
        self.assertFalse(live_bot._log_loop_state_once("disabled", "Bot is DISABLED.", now=110.0))

        live_bot._clear_loop_state_notice()

        self.assertTrue(live_bot._log_loop_state_once("disabled", "Bot is DISABLED.", now=111.0))
        self.assertEqual(mock_tui_log.call_count, 2)

    def test_bot_loop_uses_skip_backoff_when_due_scan_is_skipped(self):
        runtime = live_bot.LiveRuntimeConfig(
            enabled=True,
            direction="BOTH",
            min_score=120,
            min_score_gap=30,
            timeframe="4H",
            min_volume=1_000_000,
            workers=10,
            rate_limit_rps=5.0,
            interval=300,
        )
        account = {"balance": 50.0, "free_balance": 50.0, "used_balance": 0.0, "positions": []}
        wait_calls = []

        def stop_wait(timeout_seconds: float) -> None:
            wait_calls.append(timeout_seconds)
            raise LoopStop()

        with patch("bots.live_bot.time.sleep", return_value=None), \
             patch.object(live_bot, "load_live_cooldowns"), \
             patch.object(live_bot, "_load_positions_from_disk"), \
             patch.object(live_bot, "_ensure_ws_started"), \
             patch.object(live_bot, "_load_live_runtime_config", return_value=runtime), \
             patch.object(live_bot, "update_pnl_and_stops"), \
             patch.object(live_bot, "fetch_live_account_state", return_value=account), \
             patch.object(live_bot, "_run_live_scan_cycle", return_value=False), \
             patch.object(live_bot, "_wait_for_engine_wake", side_effect=stop_wait), \
             patch.object(live_bot, "tui_log"):
            with self.assertRaises(LoopStop):
                live_bot.bot_loop(Namespace())

        self.assertEqual(wait_calls[-1], live_bot.LOOP_SKIP_BACKOFF_SECONDS)

    def test_bot_loop_retries_after_iteration_error(self):
        account = {"balance": 50.0, "free_balance": 50.0, "used_balance": 0.0, "positions": []}
        wait_calls = []
        messages = []

        def stop_wait(timeout_seconds: float) -> None:
            wait_calls.append(timeout_seconds)
            raise LoopStop()

        with patch("bots.live_bot.time.sleep", return_value=None), \
             patch.object(live_bot, "load_live_cooldowns"), \
             patch.object(live_bot, "_load_positions_from_disk"), \
             patch.object(live_bot, "_ensure_ws_started"), \
             patch.object(live_bot, "_load_live_runtime_config", side_effect=RuntimeError("boom")), \
             patch.object(live_bot, "fetch_live_account_state", return_value=account), \
             patch.object(live_bot, "_wait_for_engine_wake", side_effect=stop_wait), \
             patch.object(live_bot, "tui_log", side_effect=messages.append):
            with self.assertRaises(LoopStop):
                live_bot.bot_loop(Namespace())

        self.assertEqual(wait_calls[-1], live_bot.LOOP_ERROR_BACKOFF_SECONDS)
        self.assertTrue(any("BOT LOOP ERROR: RuntimeError: boom" in message for message in messages))

class TestLiveExecution(unittest.TestCase):
    def setUp(self):
        self._orig_positions = dict(live_bot._client_managed_positions)
        self._orig_last_exit = dict(live_bot.LAST_EXIT_TIME)
        self._orig_live_prices = dict(live_bot._live_prices)
        self._orig_no_tui = live_bot._no_tui
        self._orig_position_mode = live_bot.POSITION_MODE
        self._orig_use_native = live_bot.USE_NATIVE_EXIT_ORDERS
        self._orig_instrument_cache = dict(live_bot._instrument_cache)
        self._orig_instrument_loaded = live_bot._instrument_loaded
        self._orig_entry_pause_until = live_bot._entry_pause_until
        self._orig_entry_pause_reason = live_bot._entry_pause_reason
        self._orig_low_margin_scan_log_message = live_bot._low_margin_scan_log_message
        self._orig_low_margin_scan_logged_at = live_bot._low_margin_scan_logged_at
        self._orig_fast_track_cooldown = dict(live_bot.FAST_TRACK_COOLDOWN)
        self._orig_fast_track_opened = set(live_bot._fast_track_opened)
        self._orig_min_live_entry_score = live_bot.MIN_LIVE_ENTRY_SCORE
        live_bot._client_managed_positions.clear()
        live_bot.LAST_EXIT_TIME.clear()
        live_bot._live_prices.clear()
        live_bot.FAST_TRACK_COOLDOWN.clear()
        live_bot._fast_track_opened.clear()
        live_bot._no_tui = True
        live_bot.POSITION_MODE = "AUTO"
        live_bot.USE_NATIVE_EXIT_ORDERS = True
        live_bot.MIN_LIVE_ENTRY_SCORE = self._orig_min_live_entry_score
        live_bot._instrument_cache.clear()
        live_bot._instrument_loaded = True
        live_bot._entry_pause_until = 0.0
        live_bot._entry_pause_reason = ""
        live_bot._reset_low_margin_scan_log_state()

    def tearDown(self):
        live_bot._client_managed_positions.clear()
        live_bot._client_managed_positions.update(self._orig_positions)
        live_bot.LAST_EXIT_TIME.clear()
        live_bot.LAST_EXIT_TIME.update(self._orig_last_exit)
        live_bot._live_prices.clear()
        live_bot._live_prices.update(self._orig_live_prices)
        live_bot.FAST_TRACK_COOLDOWN.clear()
        live_bot.FAST_TRACK_COOLDOWN.update(self._orig_fast_track_cooldown)
        live_bot._fast_track_opened.clear()
        live_bot._fast_track_opened.update(self._orig_fast_track_opened)
        live_bot._no_tui = self._orig_no_tui
        live_bot.POSITION_MODE = self._orig_position_mode
        live_bot.USE_NATIVE_EXIT_ORDERS = self._orig_use_native
        live_bot.MIN_LIVE_ENTRY_SCORE = self._orig_min_live_entry_score
        live_bot._instrument_cache.clear()
        live_bot._instrument_cache.update(self._orig_instrument_cache)
        live_bot._instrument_loaded = self._orig_instrument_loaded
        live_bot._entry_pause_until = self._orig_entry_pause_until
        live_bot._entry_pause_reason = self._orig_entry_pause_reason
        live_bot._low_margin_scan_log_message = self._orig_low_margin_scan_log_message
        live_bot._low_margin_scan_logged_at = self._orig_low_margin_scan_logged_at

    @patch.object(live_bot, "_put")
    def test_place_market_order_retries_on_inconsistent_pos_mode(self, mock_put):
        mock_put.side_effect = [
            {"code": 20004, "msg": "TE_ERR_INCONSISTENT_POS_MODE", "data": None},
            {"code": 0, "msg": "OK", "data": {"orderID": "order-1"}},
        ]

        resp = live_bot.place_market_order("ZECUSDT", "Buy", "1.000", position_side="Buy")

        self.assertEqual(resp["code"], 0)
        self.assertEqual(mock_put.call_count, 2)
        first_params = mock_put.call_args_list[0].kwargs["params"]
        second_params = mock_put.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["posSide"], "Merged")
        self.assertEqual(second_params["posSide"], "Long")

    def test_effective_entry_leverage_clamps_to_exchange_max(self):
        live_bot._instrument_cache["BTRUSDT"] = {"max_leverage": 20.0}
        live_bot._instrument_cache["ADAUSDT"] = {"max_leverage": 50.0}

        self.assertEqual(live_bot._effective_entry_leverage("BTRUSDT", 40), 20.0)
        self.assertEqual(live_bot._effective_entry_leverage("ADAUSDT", 40), 40.0)

    @patch.object(live_bot, "_get_exchange_position")
    @patch.object(live_bot, "_put")
    def test_sync_symbol_leverage_uses_mode_aware_params(self, mock_put, mock_get_exchange_position):
        mock_put.return_value = {"code": 0, "msg": "OK", "data": None}

        mock_get_exchange_position.return_value = {"posMode": "OneWay", "crossMargin": False, "leverageRr": "10"}
        self.assertTrue(live_bot._sync_symbol_leverage("ADAUSDT", "Buy", 20))
        self.assertEqual(
            mock_put.call_args_list[0].kwargs["params"],
            {"symbol": "ADAUSDT", "leverageRr": "20"},
        )

        mock_put.reset_mock()
        mock_get_exchange_position.return_value = {"posMode": "Hedged", "crossMargin": True, "leverageRr": "-10"}
        self.assertTrue(live_bot._sync_symbol_leverage("ZECUSDT", "Sell", 10))
        self.assertEqual(
            mock_put.call_args_list[0].kwargs["params"],
            {"symbol": "ZECUSDT", "longLeverageRr": "-10", "shortLeverageRr": "-10"},
        )

    @patch.object(live_bot, "_get_exchange_position")
    def test_current_exchange_leverage_uses_conservative_exchange_ratio(self, mock_get_exchange_position):
        mock_get_exchange_position.return_value = {
            "leverageRr": "-10",
            "buyValueToCostRr": "0.10114",
            "sellValueToCostRr": "0.10126",
        }

        self.assertAlmostEqual(
            live_bot._current_exchange_leverage("ZECUSDT", "Buy", 50),
            min(50.0, 1.0 / 0.10114),
        )

    @patch.object(live_bot, "_get")
    def test_get_exchange_position_prefers_requested_side(self, mock_get):
        mock_get.return_value = {
            "code": 0,
            "data": {
                "positions": [
                    {"symbol": "ZECUSDT", "posSide": "Short", "size": "0"},
                    {"symbol": "ZECUSDT", "posSide": "Long", "size": "2.28"},
                ]
            },
        }

        pos = live_bot._get_exchange_position("ZECUSDT", "Buy")

        self.assertIsNotNone(pos)
        self.assertEqual(pos["posSide"], "Long")

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage")
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_builds_and_persists_trade_protection(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
    ):
        mock_effective_entry_leverage.return_value = live_bot.bot_core.get_score_leverage(150)
        mock_fetch_live_account_state.side_effect = [
            {"balance": 100.0, "free_balance": 100.0, "used_balance": 0.0, "positions": []},
            {"balance": 90.0, "free_balance": 90.0, "used_balance": 10.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)
        result = {"inst_id": "ADAUSDT", "price": 100.0, "score": 150}

        opened = live_bot.execute_setup(result, "LONG")

        self.assertTrue(opened)
        self.assertIn("ADAUSDT", live_bot._client_managed_positions)
        pos = live_bot._client_managed_positions["ADAUSDT"]
        self.assertEqual(pos["side"], "Buy")
        self.assertAlmostEqual(pos["entry"], 101.5)
        self.assertAlmostEqual(pos["stop_price"], 101.5 * (1.0 - live_bot.TRAIL_PCT))
        self.assertEqual(len(pos["tp_stages"]), 3)
        expected_qty = (live_bot.MARGIN_USDT * live_bot.bot_core.get_score_leverage(150)) / 100.0
        self.assertEqual(
            [stage["qty"] for stage in pos["tp_stages"]],
            [expected_qty * 0.5, expected_qty * 0.25, expected_qty * 0.25],
        )
        self.assertAlmostEqual(pos["tp_stages"][0]["price"], 101.5 * (1.0 + live_bot.TAKE_PROFIT_PCT * 0.5))
        mock_sync_symbol_leverage.assert_called_once_with("ADAUSDT", "Buy", live_bot.bot_core.get_score_leverage(150))
        mock_place_market_order.assert_called_once_with("ADAUSDT", "Buy", f"{expected_qty:.3f}", position_side="Buy")
        mock_arm_native_exit_orders.assert_called_once_with("ADAUSDT", strict=True)
        mock_send_telegram_message.assert_called_once()
        mock_log_trade.assert_called_once()
        mock_subscribe_symbol.assert_called_once_with("ADAUSDT")
        mock_ensure_ws_started.assert_called_once()
        mock_persist_live_positions.assert_called_once()

    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=False)
    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage", return_value=20.0)
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_uses_confirmed_exchange_size_for_trade_protection(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
    ):
        mock_fetch_live_account_state.side_effect = [
            {"balance": 100.0, "free_balance": 100.0, "used_balance": 0.0, "positions": []},
            {"balance": 90.0, "free_balance": 90.0, "used_balance": 10.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.return_value = (3.0, 101.25)

        opened = live_bot.execute_setup({"inst_id": "ADAUSDT", "price": 100.0, "score": 150}, "LONG")

        self.assertTrue(opened)
        pos = live_bot._client_managed_positions["ADAUSDT"]
        self.assertAlmostEqual(pos["size"], 3.0)
        self.assertAlmostEqual(pos["entry"], 101.25)
        self.assertEqual([stage["qty"] for stage in pos["tp_stages"]], [1.5, 0.75, 0.75])
        mock_confirmed_entry_snapshot.assert_called_once()

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage")
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_uses_available_free_margin(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
        mock_is_symbol_blacklisted,
    ):
        mock_effective_entry_leverage.return_value = live_bot.bot_core.get_score_leverage(150)
        mock_fetch_live_account_state.side_effect = [
            {"balance": 31.04, "free_balance": 10.79, "used_balance": 20.25, "positions": []},
            {"balance": 30.0, "free_balance": 1.0, "used_balance": 29.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)

        opened = live_bot.execute_setup({"inst_id": "ADAUSDT", "price": 100.0, "score": 150}, "LONG")

        self.assertTrue(opened)
        usable_margin = min(live_bot.MARGIN_USDT, 10.79 - live_bot.ENTRY_MARGIN_BUFFER_USDT)
        expected_qty = (usable_margin * live_bot.bot_core.get_score_leverage(150)) / 100.0
        mock_sync_symbol_leverage.assert_called_once_with("ADAUSDT", "Buy", live_bot.bot_core.get_score_leverage(150))
        mock_place_market_order.assert_called_once_with("ADAUSDT", "Buy", f"{expected_qty:.3f}", position_side="Buy")
        self.assertAlmostEqual(live_bot._client_managed_positions["ADAUSDT"]["margin"], usable_margin)
        mock_send_telegram_message.assert_called_once()
        mock_log_trade.assert_called_once()
        mock_subscribe_symbol.assert_called_once_with("ADAUSDT")
        mock_ensure_ws_started.assert_called_once()
        mock_arm_native_exit_orders.assert_called_once_with("ADAUSDT", strict=True)
        mock_persist_live_positions.assert_called_once()

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage")
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_retries_smaller_after_no_balance_error(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
        mock_is_symbol_blacklisted,
    ):
        mock_effective_entry_leverage.return_value = live_bot.bot_core.get_score_leverage(150)
        mock_fetch_live_account_state.side_effect = [
            {"balance": 31.04, "free_balance": 10.79, "used_balance": 20.25, "positions": []},
            {"balance": 30.0, "free_balance": 1.0, "used_balance": 29.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.side_effect = [
            {"code": 11001, "msg": "TE_NO_ENOUGH_AVAILABLE_BALANCE", "data": None},
            {"code": 0, "data": {"avgPriceRp": "101.5"}},
        ]
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)

        opened = live_bot.execute_setup({"inst_id": "ADAUSDT", "price": 100.0, "score": 150}, "LONG")

        self.assertTrue(opened)
        self.assertEqual(mock_place_market_order.call_count, 2)
        first_qty = float(mock_place_market_order.call_args_list[0].args[2])
        second_qty = float(mock_place_market_order.call_args_list[1].args[2])
        self.assertLess(second_qty, first_qty)
        mock_sync_symbol_leverage.assert_called_once_with("ADAUSDT", "Buy", live_bot.bot_core.get_score_leverage(150))
        expected_margin = min(min(live_bot.MARGIN_USDT, 10.79 - live_bot.ENTRY_MARGIN_BUFFER_USDT) - 0.5,
                              min(live_bot.MARGIN_USDT, 10.79 - live_bot.ENTRY_MARGIN_BUFFER_USDT) * 0.85)
        self.assertAlmostEqual(live_bot._client_managed_positions["ADAUSDT"]["margin"], expected_margin)
        mock_send_telegram_message.assert_called_once()
        mock_log_trade.assert_called_once()
        mock_subscribe_symbol.assert_called_once_with("ADAUSDT")
        mock_ensure_ws_started.assert_called_once()
        mock_arm_native_exit_orders.assert_called_once_with("ADAUSDT", strict=True)
        mock_persist_live_positions.assert_called_once()

    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "place_market_order")
    def test_execute_setup_skips_when_free_balance_is_too_low(
        self,
        mock_place_market_order,
        mock_fetch_live_account_state,
    ):
        mock_fetch_live_account_state.return_value = {
            "balance": 50.0,
            "free_balance": 5.0,
            "used_balance": 45.0,
            "positions": [],
        }

        opened = live_bot.execute_setup({"inst_id": "ADAUSDT", "price": 1.0, "score": 150}, "LONG")

        self.assertFalse(opened)
        mock_place_market_order.assert_not_called()

    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=False)
    @patch.object(live_bot, "save_live_cooldowns")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_cools_down_symbol_after_exchange_blocks_entry(
        self,
        mock_round_qty,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_fetch_live_account_state,
        mock_save_live_cooldowns,
        mock_is_symbol_blacklisted,
    ):
        mock_effective_entry_leverage.return_value = live_bot.bot_core.get_score_leverage(150)
        mock_fetch_live_account_state.return_value = {
            "balance": 31.04,
            "free_balance": 10.79,
            "used_balance": 20.25,
            "positions": [],
        }
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 11150, "msg": "TE_OI_LIMIT_REDUCE_ONLY", "data": None}

        opened = live_bot.execute_setup({"inst_id": "NIGHTUSDT", "price": 1.0, "score": 150}, "SHORT")

        self.assertFalse(opened)
        self.assertIn("NIGHTUSDT", live_bot.LAST_EXIT_TIME)
        self.assertTrue(live_bot._symbol_entry_cooldown_active("NIGHTUSDT"))
        mock_save_live_cooldowns.assert_called_once()

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=False)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage", return_value=20.0)
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_keeps_position_and_schedules_arm_retry_on_initial_arm_failure(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
    ):
        mock_fetch_live_account_state.side_effect = [
            {"balance": 31.04, "free_balance": 10.79, "used_balance": 20.25, "positions": []},
            {"balance": 30.0, "free_balance": 1.0, "used_balance": 29.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)

        opened = live_bot.execute_setup({"inst_id": "ADAUSDT", "price": 100.0, "score": 150}, "LONG")

        self.assertTrue(opened)
        pos = live_bot._client_managed_positions["ADAUSDT"]
        self.assertFalse(pos["native_orders_armed"])
        self.assertGreater(pos["native_arm_deadline"], time.time())
        mock_place_market_order.assert_called_once()
        mock_arm_native_exit_orders.assert_called_once_with("ADAUSDT", strict=True)
        self.assertGreaterEqual(mock_persist_live_positions.call_count, 2)

    @patch.object(live_bot, "_pause_new_entries")
    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "save_live_cooldowns")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "cancel_all_orders")
    @patch.object(live_bot, "send_telegram_message")
    def test_close_unprotected_position_pauses_new_entries(
        self,
        mock_send_telegram_message,
        mock_cancel_all_orders,
        mock_place_market_order,
        mock_save_live_cooldowns,
        mock_persist_live_positions,
        mock_pause_new_entries,
    ):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 100.0,
            "entry": 1.0,
            "entry_score": 150,
        }
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "0.97"}}

        closed = live_bot._close_unprotected_position("ADAUSDT", "native exit orders could not be armed for ADAUSDT")

        self.assertTrue(closed)
        self.assertNotIn("ADAUSDT", live_bot._client_managed_positions)
        mock_cancel_all_orders.assert_called_once_with("ADAUSDT")
        mock_pause_new_entries.assert_called_once()
        mock_send_telegram_message.assert_called_once()

    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=False)
    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=False)
    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_current_exchange_leverage", return_value=10.0)
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=False)
    @patch.object(live_bot, "_effective_entry_leverage", return_value=50.0)
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_continues_when_leverage_sync_fails(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_current_exchange_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
    ):
        mock_fetch_live_account_state.side_effect = [
            {"balance": 31.04, "free_balance": 10.79, "used_balance": 20.25, "positions": []},
            {"balance": 30.0, "free_balance": 1.0, "used_balance": 29.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)

        opened = live_bot.execute_setup({"inst_id": "ZECUSDT", "price": 100.0, "score": 170}, "LONG")

        self.assertTrue(opened)
        usable_margin = min(live_bot.MARGIN_USDT, 10.79 - live_bot.ENTRY_MARGIN_BUFFER_USDT)
        expected_qty = (usable_margin * 10.0) / 100.0
        mock_sync_symbol_leverage.assert_called_once_with("ZECUSDT", "Buy", 50.0)
        mock_current_exchange_leverage.assert_called_once_with("ZECUSDT", "Buy", 50.0)
        mock_place_market_order.assert_called_once_with("ZECUSDT", "Buy", f"{expected_qty:.3f}", position_side="Buy")
        self.assertAlmostEqual(live_bot._client_managed_positions["ZECUSDT"]["leverage"], 10.0)

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_ensure_ws_started")
    @patch.object(live_bot, "_subscribe_symbol")
    @patch.object(live_bot.bot_core, "log_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "place_market_order")
    @patch.object(live_bot, "_sync_symbol_leverage", return_value=True)
    @patch.object(live_bot, "_effective_entry_leverage", return_value=20.0)
    @patch.object(live_bot, "_confirmed_entry_snapshot")
    @patch.object(live_bot, "_round_qty")
    def test_execute_setup_uses_clamped_leverage_for_qty_and_sync(
        self,
        mock_round_qty,
        mock_confirmed_entry_snapshot,
        mock_effective_entry_leverage,
        mock_sync_symbol_leverage,
        mock_place_market_order,
        mock_send_telegram_message,
        mock_log_trade,
        mock_subscribe_symbol,
        mock_ensure_ws_started,
        mock_arm_native_exit_orders,
        mock_fetch_live_account_state,
        mock_persist_live_positions,
    ):
        mock_fetch_live_account_state.side_effect = [
            {"balance": 31.04, "free_balance": 10.79, "used_balance": 20.25, "positions": []},
            {"balance": 30.0, "free_balance": 1.0, "used_balance": 29.0, "positions": []},
        ]
        mock_round_qty.side_effect = lambda symbol, qty: f"{qty:.3f}"
        mock_place_market_order.return_value = {"code": 0, "data": {"avgPriceRp": "101.5"}}
        mock_confirmed_entry_snapshot.side_effect = lambda symbol, side, price, size: (size, price)

        opened = live_bot.execute_setup({"inst_id": "BTRUSDT", "price": 100.0, "score": 150}, "LONG")

        self.assertTrue(opened)
        usable_margin = min(live_bot.MARGIN_USDT, 10.79 - live_bot.ENTRY_MARGIN_BUFFER_USDT)
        expected_qty = (usable_margin * 20.0) / 100.0
        mock_effective_entry_leverage.assert_called_once_with("BTRUSDT", live_bot.bot_core.get_score_leverage(150))
        mock_sync_symbol_leverage.assert_called_once_with("BTRUSDT", "Buy", 20.0)
        mock_place_market_order.assert_called_once_with("BTRUSDT", "Buy", f"{expected_qty:.3f}", position_side="Buy")
        self.assertAlmostEqual(live_bot._client_managed_positions["BTRUSDT"]["leverage"], 20.0)

    @patch.object(live_bot, "_refresh_stop_order")
    def test_check_stops_live_native_refreshes_improved_stop(self, mock_refresh_stop_order):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 100.0,
            "entry": 1.0,
            "stop_price": 0.97,
            "high_water": 1.0,
            "low_water": None,
            "mark_price": 1.0,
            "stop_order_id": "stop-1",
            "last_submitted_stop_price": 0.97,
            "last_stop_refresh_ts": time.time() - 10.0,
            "native_orders_armed": True,
            "native_arm_deadline": 0.0,
            "native_arm_last_attempt_at": 0.0,
            "tp_stages": [],
        }
        live_bot._live_prices["ADAUSDT"] = 1.05

        live_bot._check_stops_live("ADAUSDT")

        pos = live_bot._client_managed_positions["ADAUSDT"]
        expected_stop = 1.05 * (1.0 - live_bot.TRAIL_PCT)
        self.assertAlmostEqual(pos["high_water"], 1.05)
        self.assertAlmostEqual(pos["stop_price"], expected_stop)
        mock_refresh_stop_order.assert_called_once_with("ADAUSDT", expected_stop, "Buy")

    @patch.object(live_bot, "_get_exchange_position")
    def test_effective_native_stop_price_clamps_above_liquidation(self, mock_get_exchange_position):
        mock_get_exchange_position.return_value = {
            "symbol": "ENAUSDT",
            "liquidationPriceRp": "0.0958",
            "markPriceRp": "0.0966",
        }
        live_bot._instrument_cache["ENAUSDT"] = {"tick": 0.0001, "step": 1.0, "qty_precision": 0, "price_precision": 4}

        stop_price = live_bot._effective_native_stop_price("ENAUSDT", "Buy", 0.0950)

        self.assertAlmostEqual(stop_price, 0.0959)

    @patch.object(live_bot.bot_core, "MIN_SCORE", 120)
    @patch.object(live_bot, "verify_live_candidate")
    @patch.object(live_bot, "load_live_account")
    def test_on_scan_result_respects_effective_live_entry_floor(
        self,
        mock_load_live_account,
        mock_verify_live_candidate,
    ):
        live_bot.MIN_LIVE_ENTRY_SCORE = 130
        mock_load_live_account.return_value = {
            "balance": 50.0,
            "free_balance": 50.0,
            "used_balance": 0.0,
            "positions": [],
        }

        live_bot.on_scan_result({"inst_id": "KAITOUSDT", "score": 127}, "SHORT")

        mock_verify_live_candidate.assert_not_called()
        self.assertNotIn("KAITOUSDT", live_bot._fast_track_opened)

    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=True)
    @patch.object(live_bot, "verify_live_candidate")
    @patch.object(live_bot, "load_live_account")
    def test_on_scan_result_skips_blacklisted_symbol(
        self,
        mock_load_live_account,
        mock_verify_live_candidate,
        mock_is_symbol_blacklisted,
    ):
        mock_load_live_account.return_value = {
            "balance": 50.0,
            "free_balance": 50.0,
            "used_balance": 0.0,
            "positions": [],
        }

        live_bot.on_scan_result({"inst_id": "NIGHTUSDT", "score": 150}, "SHORT")

        mock_verify_live_candidate.assert_not_called()
        self.assertNotIn("NIGHTUSDT", live_bot._fast_track_opened)

    @patch.object(live_bot, "_get_single_ticker")
    @patch.object(live_bot, "load_live_account")
    @patch("bots.live_bot.time.sleep", return_value=None)
    def test_verify_live_candidate_stops_when_entry_capacity_disappears(
        self,
        mock_sleep,
        mock_load_live_account,
        mock_get_single_ticker,
    ):
        mock_load_live_account.side_effect = [
            {"balance": 50.0, "free_balance": 50.0, "used_balance": 0.0, "positions": []},
            {"balance": 50.0, "free_balance": 0.0, "used_balance": 50.0, "positions": []},
        ]

        verified = live_bot.verify_live_candidate("TONUSDT", "SHORT", 140, wait_seconds=1)

        self.assertIsNone(verified)
        mock_get_single_ticker.assert_not_called()

    @patch.object(live_bot, "_is_symbol_blacklisted", return_value=True)
    @patch.object(live_bot, "fetch_live_account_state")
    @patch.object(live_bot, "place_market_order")
    def test_execute_setup_skips_blacklisted_symbol(
        self,
        mock_place_market_order,
        mock_fetch_live_account_state,
        mock_is_symbol_blacklisted,
    ):
        mock_fetch_live_account_state.return_value = {
            "balance": 50.0,
            "free_balance": 50.0,
            "used_balance": 0.0,
            "positions": [],
        }

        opened = live_bot.execute_setup({"inst_id": "NIGHTUSDT", "price": 1.0, "score": 150}, "SHORT")

        self.assertFalse(opened)
        mock_place_market_order.assert_not_called()

    @patch.object(live_bot, "_persist_live_positions")
    @patch.object(live_bot, "_place_with_retries")
    @patch.object(live_bot, "get_active_orders", return_value=[])
    @patch.object(live_bot, "_effective_native_stop_price", return_value=0.97)
    @patch.object(live_bot, "_wait_for_exchange_position", return_value=True)
    @patch.object(live_bot, "_get_exchange_position")
    def test_arm_native_exit_orders_runs_for_new_position_with_preclaimed_pending_slot(
        self,
        mock_get_exchange_position,
        mock_wait_for_exchange_position,
        mock_effective_native_stop_price,
        mock_get_active_orders,
        mock_place_with_retries,
        mock_persist_live_positions,
    ):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 100.0,
            "entry": 1.0,
            "stop_price": 0.97,
            "native_orders_armed": False,
            "native_arm_pending": True,
            "native_arm_started_at": time.time(),
            "native_arm_last_attempt_at": 0.0,
            "tp_stages": [
                {"price": 1.05, "qty": 50.0, "hit": False},
                {"price": 1.10, "qty": 25.0, "hit": False},
                {"price": 1.15, "qty": 25.0, "hit": False},
            ],
        }
        mock_get_exchange_position.return_value = {"symbol": "ADAUSDT", "size": "100"}
        mock_place_with_retries.side_effect = [
            {"code": 0, "data": {"orderID": "stop-1"}},
            {"code": 0, "data": {"orderID": "tp-1"}},
            {"code": 0, "data": {"orderID": "tp-2"}},
            {"code": 0, "data": {"orderID": "tp-3"}},
        ]

        armed = live_bot._arm_native_exit_orders("ADAUSDT", strict=True)

        self.assertTrue(armed)
        self.assertEqual(mock_place_with_retries.call_count, 4)
        pos = live_bot._client_managed_positions["ADAUSDT"]
        self.assertTrue(pos["native_orders_armed"])
        self.assertFalse(pos["native_arm_pending"])
        self.assertEqual(pos["stop_order_id"], "stop-1")
        self.assertEqual([stage["order_id"] for stage in pos["tp_stages"]], ["tp-1", "tp-2", "tp-3"])
        mock_wait_for_exchange_position.assert_called_once_with("ADAUSDT", "Buy", 100.0)
        mock_effective_native_stop_price.assert_called_once_with("ADAUSDT", "Buy", 0.97)
        mock_get_active_orders.assert_called_once_with("ADAUSDT")
        mock_persist_live_positions.assert_called_once()

    @patch.object(live_bot, "tui_log")
    def test_log_low_margin_scan_skip_throttles_duplicate_messages(self, mock_tui_log):
        first = live_bot._log_low_margin_scan_skip(1.24, now=100.0)
        second = live_bot._log_low_margin_scan_skip(1.24, now=110.0)
        third = live_bot._log_low_margin_scan_skip(
            1.24,
            now=100.0 + live_bot.LOW_MARGIN_SCAN_LOG_INTERVAL_SECONDS + 1.0,
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(third)
        self.assertEqual(mock_tui_log.call_count, 2)

    @patch.object(live_bot.bot_core, "pick_candidates", return_value=[])
    @patch.object(live_bot.bot_core, "run_scanner_both", return_value=([], []))
    @patch.object(live_bot, "tui_log")
    def test_run_live_scan_cycle_uses_effective_entry_floor_for_candidates(
        self,
        mock_tui_log,
        mock_run_scanner_both,
        mock_pick_candidates,
    ):
        live_bot.MIN_LIVE_ENTRY_SCORE = 130
        runtime = live_bot.LiveRuntimeConfig(
            enabled=True,
            direction="BOTH",
            min_score=120,
            min_score_gap=30,
            timeframe="4H",
            min_volume=1_000_000,
            workers=10,
            rate_limit_rps=5.0,
            interval=300,
        )
        args = Namespace(dry_run=False)
        acc = {"balance": 50.0, "free_balance": 50.0, "used_balance": 0.0, "positions": []}

        live_bot._run_live_scan_cycle(args, runtime, acc)

        self.assertEqual(mock_pick_candidates.call_args.kwargs["min_score"], 130)

    @patch.object(live_bot, "get_active_orders")
    def test_reconcile_symbol_skips_repair_while_arm_pending(self, mock_get_active_orders):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 100.0,
            "entry": 1.0,
            "entry_time": "2026-03-22T01:00:00",
            "mark_price": 1.0,
            "stop_price": 0.97,
            "native_arm_pending": True,
            "native_arm_started_at": time.time(),
            "tp_stages": [],
        }

        changed = live_bot._reconcile_symbol_with_exchange("ADAUSDT", {"symbol": "ADAUSDT", "size": "100", "markPriceRp": "1.01"})

        self.assertTrue(changed)
        self.assertAlmostEqual(live_bot._client_managed_positions["ADAUSDT"]["mark_price"], 1.01)
        mock_get_active_orders.assert_not_called()

    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "_track_partial_tp_fill")
    @patch.object(live_bot, "get_closed_orders")
    @patch.object(live_bot, "get_active_orders")
    def test_reconcile_symbol_with_exchange_tracks_partial_tp_fill(
        self,
        mock_get_active_orders,
        mock_get_closed_orders,
        mock_track_partial_tp_fill,
        mock_arm_native_exit_orders,
    ):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 100.0,
            "entry": 1.0,
            "entry_score": 150,
            "entry_time": "2026-03-22T01:00:00",
            "stop_price": 0.97,
            "mark_price": 1.0,
            "stop_order_id": "stop-1",
            "native_orders_armed": True,
            "tp_stages": [
                {"price": 1.05, "qty": 50.0, "hit": False, "order_id": "tp-1"},
                {"price": 1.10, "qty": 25.0, "hit": False, "order_id": "tp-2"},
                {"price": 1.15, "qty": 25.0, "hit": False, "order_id": "tp-3"},
            ],
        }
        mock_get_active_orders.return_value = [
            {"orderID": "stop-1", "ordType": "Stop", "ordStatus": "Untriggered", "leavesQtyRq": "0", "cumQtyRq": "0"},
            {"orderID": "tp-2", "ordType": "Limit", "ordStatus": "New", "leavesQtyRq": "25", "cumQtyRq": "0"},
            {"orderID": "tp-3", "ordType": "Limit", "ordStatus": "New", "leavesQtyRq": "25", "cumQtyRq": "0"},
        ]
        mock_get_closed_orders.return_value = [
            {"orderId": "tp-1", "ordType": 2, "ordStatus": 7, "execQtyRq": "50", "execPriceRp": "1.05"},
        ]

        changed = live_bot._reconcile_symbol_with_exchange("ADAUSDT", {"symbol": "ADAUSDT", "size": "50", "markPriceRp": "1.06"})

        self.assertTrue(changed)
        pos = live_bot._client_managed_positions["ADAUSDT"]
        self.assertAlmostEqual(pos["size"], 50.0)
        self.assertTrue(pos["tp_stages"][0]["hit"])
        self.assertAlmostEqual(pos["tp_stages"][0]["filled_qty"], 50.0)
        self.assertAlmostEqual(pos["tp_stages"][0]["logged_qty"], 50.0)
        mock_track_partial_tp_fill.assert_called_once()
        mock_arm_native_exit_orders.assert_not_called()

    @patch.object(live_bot, "_arm_native_exit_orders", return_value=True)
    @patch.object(live_bot, "get_closed_orders", return_value=[])
    @patch.object(live_bot, "get_active_orders", return_value=[])
    def test_reconcile_symbol_rebalances_unfilled_tp_stages_after_exchange_size_change(
        self,
        mock_get_active_orders,
        mock_get_closed_orders,
        mock_arm_native_exit_orders,
    ):
        live_bot._instrument_cache["TURBOUSDT"] = {
            "step": 1.0,
            "tick": 0.000001,
            "qty_precision": 0,
            "price_precision": 6,
        }
        live_bot._client_managed_positions["TURBOUSDT"] = {
            "symbol": "TURBOUSDT",
            "side": "Sell",
            "size": 290644.0,
            "entry": 0.001109,
            "entry_score": 159,
            "entry_time": "2026-03-22T11:48:07.030853",
            "stop_price": 0.00111652,
            "mark_price": 0.001087,
            "stop_order_id": "stop-1",
            "native_orders_armed": False,
            "tp_stages": [
                {"price": 0.00105355, "qty": 145322.0, "hit": False, "order_id": "tp-1"},
                {"price": 0.001025825, "qty": 72661.0, "hit": False, "order_id": "tp-2"},
                {"price": 0.0009981, "qty": 72661.0, "hit": False, "order_id": "tp-3"},
            ],
        }

        changed = live_bot._reconcile_symbol_with_exchange(
            "TURBOUSDT",
            {"symbol": "TURBOUSDT", "size": "49389", "markPriceRp": "0.001087"},
        )

        self.assertTrue(changed)
        pos = live_bot._client_managed_positions["TURBOUSDT"]
        self.assertAlmostEqual(pos["size"], 49389.0)
        self.assertEqual([stage["qty"] for stage in pos["tp_stages"]], [24694.0, 12347.0, 12348.0])
        self.assertEqual([stage["order_id"] for stage in pos["tp_stages"]], [None, None, None])
        mock_arm_native_exit_orders.assert_called_once_with("TURBOUSDT", strict=True)

    @patch.object(live_bot, "cancel_all_orders")
    @patch.object(live_bot, "_log_closed_trade")
    @patch.object(live_bot, "send_telegram_message")
    @patch.object(live_bot, "save_live_cooldowns")
    @patch.object(live_bot, "get_closed_orders")
    @patch.object(live_bot, "get_active_orders")
    def test_reconcile_symbol_with_exchange_removes_position_after_stop_fill(
        self,
        mock_get_active_orders,
        mock_get_closed_orders,
        mock_save_live_cooldowns,
        mock_send_telegram_message,
        mock_log_closed_trade,
        mock_cancel_all_orders,
    ):
        live_bot._client_managed_positions["ADAUSDT"] = {
            "symbol": "ADAUSDT",
            "side": "Buy",
            "size": 50.0,
            "entry": 1.0,
            "entry_score": 150,
            "entry_time": "2026-03-22T01:00:00",
            "stop_price": 0.97,
            "mark_price": 1.0,
            "stop_order_id": "stop-1",
            "native_orders_armed": True,
            "tp_stages": [
                {"price": 1.05, "qty": 50.0, "hit": True, "filled_qty": 50.0, "logged_qty": 50.0, "order_id": "tp-1"},
                {"price": 1.10, "qty": 25.0, "hit": False, "order_id": "tp-2"},
                {"price": 1.15, "qty": 25.0, "hit": False, "order_id": "tp-3"},
            ],
        }
        mock_get_active_orders.return_value = []
        mock_get_closed_orders.return_value = [
            {"orderId": "stop-1", "ordType": 3, "ordStatus": 7, "execQtyRq": "50", "execPriceRp": "0.97"},
            {"orderId": "tp-2", "ordType": 2, "ordStatus": 8, "execQtyRq": "0", "execPriceRp": "0"},
            {"orderId": "tp-3", "ordType": 2, "ordStatus": 8, "execQtyRq": "0", "execPriceRp": "0"},
        ]

        changed = live_bot._reconcile_symbol_with_exchange("ADAUSDT", {"symbol": "ADAUSDT", "size": "0", "markPriceRp": "0.96"})

        self.assertTrue(changed)
        self.assertNotIn("ADAUSDT", live_bot._client_managed_positions)
        self.assertIn("ADAUSDT", live_bot.LAST_EXIT_TIME)
        mock_cancel_all_orders.assert_called_once_with("ADAUSDT")
        mock_save_live_cooldowns.assert_called_once()
        mock_send_telegram_message.assert_called_once()
        mock_log_closed_trade.assert_called_once()


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
