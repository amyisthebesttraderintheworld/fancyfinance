"""Tests for bots.backtester module."""

import pytest
from unittest.mock import Mock, patch
from fangblenny_bot.bots.backtester import get_spread_pct, get_funding, get_htf_rsi


class TestGetSpreadPct:
    @patch('fangblenny_bot.bots.backtester._get')
    def test_get_spread_pct_success(self, mock_get):
        mock_get.return_value = {
            "result": {
                "orderbook_p": {
                    "bids": [["100.0", "1.0"]],
                    "asks": [["101.0", "1.0"]]
                }
            }
        }
        spread = get_spread_pct("BTCUSDT")
        assert spread == 1.0  # (101-100)/100 * 100 = 1.0

    @patch('fangblenny_bot.bots.backtester._get')
    def test_get_spread_pct_failure(self, mock_get):
        mock_get.return_value = None
        spread = get_spread_pct("BTCUSDT")
        assert spread is None


class TestGetFunding:
    @patch('fangblenny_bot.bots.backtester._get')
    def test_get_funding_success(self, mock_get):
        mock_get.return_value = {
            "data": [{"symbol": "BTCUSDT", "fundingRate": "0.01"}]
        }
        funding = get_funding("BTCUSDT")
        assert funding == 0.01

    @patch('fangblenny_bot.bots.backtester._get')
    def test_get_funding_failure(self, mock_get):
        mock_get.return_value = None
        funding = get_funding("BTCUSDT")
        assert funding is None


class TestGetHtfRsi:
    @patch('fangblenny_bot.bots.backtester.get_candles')
    def test_get_htf_rsi_success(self, mock_get_candles):
        # Mock candles with closing prices
        mock_get_candles.return_value = [
            [1640995200, "1H", 50000, 49000, 51000, 48500, 49500, 100, 5000000],
            [1640998800, "1H", 49500, 48500, 50500, 48000, 49000, 100, 5000000],
        ] * 25  # Enough for RSI

        rsi = get_htf_rsi("BTCUSDT", "1H")
        assert rsi is not None
        assert 0 <= rsi <= 100

    @patch('fangblenny_bot.bots.backtester.get_candles')
    def test_get_htf_rsi_insufficient_data(self, mock_get_candles):
        mock_get_candles.return_value = []
        rsi = get_htf_rsi("BTCUSUSDT", "1H")
        assert rsi is None