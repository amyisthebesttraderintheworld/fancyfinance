"""Tests for scanners.long module."""

import pytest
from unittest.mock import Mock, patch
from fangblenny_bot.scanners.long import analyse, get_tickers, get_candles


class TestAnalyse:
    @patch('fangblenny_bot.scanners.long.pc.get_tickers')
    @patch('fangblenny_bot.scanners.long.pc.get_candles')
    @patch('fangblenny_bot.scanners.long.pc.get_funding_rate_info')
    @patch('fangblenny_bot.scanners.long.pc.get_order_book')
    @patch('fangblenny_bot.scanners.long.pc.get_cryptopanic_news')
    def test_analyse_basic(self, mock_news, mock_order_book, mock_funding, mock_candles, mock_tickers):
        # Mock inputs
        ticker = {"symbol": "BTCUSDT", "turnoverRv": "2000000", "lastRp": "50000", "openRp": "49000", "highRp": "51000", "lowRp": "48500"}
        cfg = {"TIMEFRAME": "15m", "MIN_VOLUME": 1000000, "RATE_LIMIT_RPS": 10.0}

        # Mock candles (OHLCV format)
        mock_candles.return_value = [
            [1640995200, 900, 50000, 51000, 49000, 50500, 100, 5000000]
        ] * 50  # 50 candles

        # Mock funding
        mock_funding.return_value = (0.001, 0.0005, 0.0005)

        # Mock order book
        mock_order_book.return_value = (49500, 49600, 0.002, 1000)

        # Mock news
        mock_news.return_value = (5, ["News 1", "News 2"])

        result = analyse(ticker, cfg, enable_ai=False, enable_entity=False)
        assert result is None or isinstance(result, dict)


class TestGetTickers:
    @patch('fangblenny_bot.scanners.long.pc.get_tickers')
    def test_get_tickers(self, mock_get_tickers):
        mock_get_tickers.return_value = [{"symbol": "BTCUSDT"}]
        result = get_tickers()
        assert result == [{"symbol": "BTCUSDT"}]


class TestGetCandles:
    @patch('fangblenny_bot.scanners.long.pc.get_candles')
    def test_get_candles(self, mock_get_candles):
        mock_get_candles.return_value = [["candle_data"]]
        result = get_candles("BTCUSDT", "15m", 100)
        assert result == [["candle_data"]]
