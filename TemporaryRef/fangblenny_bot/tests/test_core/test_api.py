"""Tests for api module."""

import pytest
from unittest.mock import Mock, patch
from fangblenny_bot.core import api


class TestResolveResolution:
    def test_known_timeframe(self):
        assert api._resolve_resolution("1m") == 60
        assert api._resolve_resolution("1H") == 3600

    def test_unknown_timeframe(self):
        assert api._resolve_resolution("unknown") == 900  # default 15m


class TestGetTickers:
    @patch('fangblenny_bot.core.network.safe_request')
    def test_get_tickers_success(self, mock_safe_request):
        mock_response = Mock()
        mock_response.json.return_value = {
            "result": [
                {"symbol": "BTCUSDT", "turnoverRv": "1000000"},
                {"symbol": "ETHUSDT", "turnoverRv": "500000"},
                {"symbol": "SOLUSDT", "turnoverRv": "100000"},
            ]
        }
        mock_safe_request.return_value = mock_response

        tickers = api.get_tickers()
        assert len(tickers) == 3
        assert tickers[0]["symbol"] == "BTCUSDT"

    @patch('fangblenny_bot.core.network.safe_request')
    def test_get_tickers_failure(self, mock_safe_request):
        mock_safe_request.return_value = None
        tickers = api.get_tickers()
        assert tickers == []


class TestGetCandles:
    @patch('fangblenny_bot.core.network.safe_request')
    @patch('fangblenny_bot.core.cache.CACHE')
    def test_get_candles_cached(self, mock_cache, mock_safe_request):
        mock_cache.get.return_value = [["data"]]
        candles = api.get_candles("BTCUSDT", "15m", 100)
        assert candles == [["data"]]
        mock_safe_request.assert_not_called()

    @patch('fangblenny_bot.core.network.safe_request')
    @patch('fangblenny_bot.core.cache.CACHE')
    def test_get_candles_api_call(self, mock_cache, mock_safe_request):
        mock_cache.get.return_value = None
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"rows": [["ts", "interval", "last_close", "open", "high", "low", "close", "volume", "turnover"]]}
        }
        mock_safe_request.return_value = mock_response

        candles = api.get_candles("BTCUSDT", "15m", 1)
        assert len(candles) == 1
        mock_cache.set.assert_called_once()


class TestGetFundingRateInfo:
    @patch('fangblenny_bot.core.network.safe_request')
    @patch('fangblenny_bot.core.cache.CACHE')
    def test_get_funding_cached(self, mock_cache, mock_safe_request):
        mock_cache.get.return_value = (0.01, 0.005, 0.005)
        result = api.get_funding_rate_info("BTCUSDT")
        assert result == (0.01, 0.005, 0.005)
        mock_safe_request.assert_not_called()

    @patch('fangblenny_bot.core.network.safe_request')
    @patch('fangblenny_bot.core.cache.CACHE')
    def test_get_funding_api_call(self, mock_cache, mock_safe_request):
        mock_cache.get.return_value = None
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"symbol": "BTCUSDT", "fundingRate": "0.01"}]
        }
        mock_safe_request.return_value = mock_response

        result = api.get_funding_rate_info("BTCUSDT")
        assert result[0] == 0.01
        mock_cache.set.assert_called_once()


class TestGetOrderBook:
    @patch('fangblenny_bot.core.network.safe_request')
    def test_get_order_book_success(self, mock_safe_request):
        mock_response = Mock()
        mock_response.json.return_value = {
            "result": {
                "orderbook_p": {
                    "bids": [["50000", "1.0"]],
                    "asks": [["50001", "1.0"]]
                }
            }
        }
        mock_safe_request.return_value = mock_response

        bid, ask, spread, depth = api.get_order_book("BTCUSDT")
        assert bid == 50000.0
        assert ask == 50001.0
        assert spread is not None
        assert depth > 0

    @patch('fangblenny_bot.core.network.safe_request')
    def test_get_order_book_failure(self, mock_safe_request):
        mock_safe_request.return_value = None
        result = api.get_order_book("BTCUSDT")
        assert result == (None, None, None, 0.0)


class TestMakeEntityRequest:
    @patch('fangblenny_bot.core.network.safe_request')
    def test_make_entity_request_get(self, mock_safe_request):
        mock_response = Mock()
        mock_response.json.return_value = {"data": "test"}
        mock_safe_request.return_value = mock_response

        result = api.make_entity_request("test_entity", method="GET")
        assert result == {"data": "test"}

    @patch('fangblenny_bot.core.network.safe_request')
    def test_make_entity_request_no_key(self, mock_safe_request):
        with patch('fangblenny_bot.core.config.ENTITY_API_KEY', None):
            result = api.make_entity_request("test_entity")
            assert result is None
            mock_safe_request.assert_not_called()


class TestCallDeepseek:
    @patch('fangblenny_bot.core.network.safe_request')
    def test_call_deepseek_success(self, mock_safe_request):
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            b'data: [DONE]'
        ]
        mock_safe_request.return_value = mock_response

        result = api.call_deepseek("Test prompt")
        assert "Hello" in result

    @patch('fangblenny_bot.core.network.safe_request')
    def test_call_deepseek_no_key(self, mock_safe_request):
        with patch('fangblenny_bot.core.config.DEEPSEEK_API_KEY', None):
            result = api.call_deepseek("Test prompt")
            assert result is None
            mock_safe_request.assert_not_called()