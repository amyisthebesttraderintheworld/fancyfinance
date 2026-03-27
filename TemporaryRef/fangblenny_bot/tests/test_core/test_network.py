"""Tests for network module."""

import pytest
from unittest.mock import Mock, patch
from fangblenny_bot.core.network import (
    build_session,
    get_thread_session,
    throttle,
    safe_request,
)


class TestBuildSession:
    def test_build_session(self):
        session = build_session()
        assert session is not None
        assert hasattr(session, 'get')
        assert hasattr(session, 'post')


class TestGetThreadSession:
    def test_get_thread_session(self):
        session1 = get_thread_session()
        session2 = get_thread_session()
        # Should return the same session in the same thread
        assert session1 is session2


class TestThrottle:
    @patch('time.sleep')
    @patch('time.time')
    def test_throttle_no_sleep(self, mock_time, mock_sleep):
        mock_time.return_value = 0
        throttle(0)  # No RPS limit
        mock_sleep.assert_not_called()

    @patch('time.sleep')
    @patch('time.time')
    def test_throttle_with_sleep(self, mock_time, mock_sleep):
        mock_time.side_effect = [0, 0.05]  # 0.05 seconds elapsed
        throttle(10)  # 10 RPS = 0.1s interval
        mock_sleep.assert_called_once()
        args = mock_sleep.call_args[0]
        assert args[0] > 0  # Should sleep for remaining time


class TestSafeRequest:
    @patch('fangblenny_bot.core.network.get_thread_session')
    def test_safe_request_success(self, mock_get_session):
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_session.request.return_value = mock_response
        mock_get_session.return_value = mock_session

        result = safe_request('GET', 'http://example.com')
        assert result == mock_response

    @patch('fangblenny_bot.core.network.get_thread_session')
    def test_safe_request_429_retry(self, mock_get_session):
        mock_session = Mock()
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {'Retry-After': '1'}
        mock_response_429.raise_for_status.side_effect = Exception("429")

        mock_response_ok = Mock()
        mock_response_ok.status_code = 200
        mock_response_ok.raise_for_status.return_value = None

        mock_session.request.side_effect = [mock_response_429, mock_response_ok]
        mock_get_session.return_value = mock_session

        with patch('time.sleep'):
            result = safe_request('GET', 'http://example.com')
        assert result == mock_response_ok

    @patch('fangblenny_bot.core.network.get_thread_session')
    def test_safe_request_failure(self, mock_get_session):
        mock_session = Mock()
        mock_session.request.side_effect = Exception("Network error")
        mock_get_session.return_value = mock_session

        result = safe_request('GET', 'http://example.com')
        assert result is None