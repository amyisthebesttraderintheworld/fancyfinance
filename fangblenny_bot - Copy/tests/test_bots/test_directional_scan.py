import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent and project root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../../bots'))

from core.bot_core import run_scanner_both

class TestDirectionalScan(unittest.TestCase):
    def setUp(self):
        self.mock_args = MagicMock()
        self.mock_cfg = {
            "MIN_VOLUME": 1000000,
            "MAX_WORKERS": 10,
            "RATE_LIMIT_RPS": 10.0
        }
        
    @patch("core.bot_core.scanner_long")
    @patch("core.bot_core.scanner_short")
    def test_run_scanner_both_long_only(self, mock_short, mock_long):
        """Verify that only the LONG scanner is called when direction is LONG."""
        self.mock_args.direction = "LONG"
        self.mock_args.no_ai = True
        self.mock_args.no_entity = True
        
        # Mock get_tickers to return something
        mock_long.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        mock_short.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        
        # Mock analyse to return a dummy result
        mock_long.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        mock_short.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        
        long_res, short_res = run_scanner_both(self.mock_cfg, self.mock_args, show_progress=False)
        
        # Verify LONG was called
        mock_long.get_tickers.assert_called()
        # Verify SHORT was NOT called
        mock_short.get_tickers.assert_not_called()
        
        self.assertTrue(len(long_res) > 0)
        self.assertEqual(len(short_res), 0)

    @patch("core.bot_core.scanner_long")
    @patch("core.bot_core.scanner_short")
    def test_run_scanner_both_short_only(self, mock_short, mock_long):
        """Verify that only the SHORT scanner is called when direction is SHORT."""
        self.mock_args.direction = "SHORT"
        self.mock_args.no_ai = True
        self.mock_args.no_entity = True
        
        mock_long.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        mock_short.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        
        mock_long.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        mock_short.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        
        long_res, short_res = run_scanner_both(self.mock_cfg, self.mock_args, show_progress=False)
        
        # Verify SHORT was called
        mock_short.get_tickers.assert_called()
        # Verify LONG was NOT called
        mock_long.get_tickers.assert_not_called()
        
        self.assertEqual(len(long_res), 0)
        self.assertTrue(len(short_res) > 0)

    @patch("core.bot_core.scanner_long")
    @patch("core.bot_core.scanner_short")
    def test_run_scanner_both_both(self, mock_short, mock_long):
        """Verify that BOTH scanners are called when direction is BOTH."""
        self.mock_args.direction = "BOTH"
        self.mock_args.no_ai = True
        self.mock_args.no_entity = True
        
        mock_long.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        mock_short.get_tickers.return_value = [{"symbol": "BTCUSDT", "turnoverRv": 2000000}]
        
        mock_long.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        mock_short.analyse.return_value = {"inst_id": "BTCUSDT", "score": 150}
        
        long_res, short_res = run_scanner_both(self.mock_cfg, self.mock_args, show_progress=False)
        
        # Verify BOTH were called
        mock_long.get_tickers.assert_called()
        mock_short.get_tickers.assert_called()
        
        self.assertTrue(len(long_res) > 0)
        self.assertTrue(len(short_res) > 0)

if __name__ == "__main__":
    unittest.main()
