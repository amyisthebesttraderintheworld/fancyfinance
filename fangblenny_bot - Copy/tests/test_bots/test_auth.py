
import unittest
from unittest.mock import patch, MagicMock
import hmac
import hashlib
import json
import time
import urllib.parse
from bots import live_bot

class TestPhemexAuth(unittest.TestCase):
    def setUp(self):
        # Set dummy credentials for testing
        self.api_key = "test-api-key"
        self.api_secret = "test-api-secret"
        
        # Patch the global variables in live_bot
        self.patcher_key = patch('bots.live_bot.API_KEY', self.api_key)
        self.patcher_secret = patch('bots.live_bot.API_SECRET', self.api_secret)
        self.patcher_key.start()
        self.patcher_secret.start()

    def tearDown(self):
        self.patcher_key.stop()
        self.patcher_secret.stop()

    def test_signature_generation(self):
        """Confirm that _sign produces a valid HMAC-SHA256 signature."""
        method = "GET"
        path = "/g-accounts/all-accounts"
        query = "currency=USDT"
        expiry = 1711058400  # Example timestamp
        body = ""
        
        expected_message = f"{method}{path}{query}{expiry}{body}"
        expected_sig = hmac.new(
            self.api_secret.encode("utf-8"),
            expected_message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        actual_sig = live_bot._sign(method, path, query, expiry, body)
        self.assertEqual(actual_sig, expected_sig)

    def test_auth_headers_structure(self):
        """Verify headers contain all required Phemex fields."""
        method = "GET"
        path = "/test"
        query = ""
        
        headers = live_bot._auth_headers(method, path, query)
        
        self.assertIn("x-phemex-access-token", headers)
        self.assertIn("x-phemex-request-expiry", headers)
        self.assertIn("x-phemex-request-signature", headers)
        self.assertEqual(headers["x-phemex-access-token"], self.api_key)
        
        # Check if signature matches the content
        sig = headers["x-phemex-request-signature"]
        expiry = headers["x-phemex-request-expiry"]
        
        expected_sig = live_bot._sign(method, path, query, int(expiry), "")
        self.assertEqual(sig, expected_sig)

    def test_get_params_sorting(self):
        """Confirm that query parameters are sorted alphabetically for the signature."""
        with patch('bots.live_bot._session') as mock_session:
            # Mock successful response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 0}
            mock_session.get.return_value = mock_resp
            
            params = {"z": 1, "a": 2, "m": 3}
            live_bot._get("/test", params=params)
            
            # Get the call arguments for mock_session.get
            args, kwargs = mock_session.get.call_args
            actual_url = args[0]
            actual_headers = kwargs['headers']
            
            # Verify URL contains sorted params
            # urllib.parse.urlencode(sorted(...)) -> a=2&m=3&z=1
            self.assertIn("a=2&m=3&z=1", actual_url)
            
            # Verify signature was generated with the SAME sorted string
            sig = actual_headers["x-phemex-request-signature"]
            expiry = actual_headers["x-phemex-request-expiry"]
            expected_sig = live_bot._sign("GET", "/test", "a=2&m=3&z=1", int(expiry), "")
            self.assertEqual(sig, expected_sig)

    def test_put_body_compact_json(self):
        """Confirm that the body is serialized without whitespace for the signature."""
        with patch('bots.live_bot._session') as mock_session:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 0}
            mock_session.put.return_value = mock_resp
            
            body = {"symbol": "BTCUSDT", "price": 50000}
            # Expected compact JSON: {"symbol":"BTCUSDT","price":50000}
            expected_body_str = json.dumps(body, separators=(',', ':'))
            
            live_bot._put("/test", body=body)
            
            args, kwargs = mock_session.put.call_args
            actual_body_str = kwargs['data']
            actual_headers = kwargs['headers']
            
            self.assertEqual(actual_body_str, expected_body_str)
            
            # Verify signature matches compact body
            sig = actual_headers["x-phemex-request-signature"]
            expiry = actual_headers["x-phemex-request-expiry"]
            expected_sig = live_bot._sign("PUT", "/test", "", int(expiry), expected_body_str)
            self.assertEqual(sig, expected_sig)

if __name__ == '__main__':
    unittest.main()
