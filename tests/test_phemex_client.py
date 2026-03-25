import pytest
import requests
from unittest.mock import MagicMock, patch
from common import PhemexClient

@pytest.fixture
def client():
    return PhemexClient("key", "secret", testnet=True)

@patch('requests.get')
def test_get_account_success(mock_get, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 0,
        'data': {
            'account': {'accountBalanceEv': 100000000} # 1.0 BTC
        }
    }
    mock_get.return_value = mock_response
    
    balance = client.get_account()
    assert balance == 1.0
    called_url = mock_get.call_args[0][0]
    assert "currency=USDT" in called_url

@patch('requests.get')
def test_get_account_error(mock_get, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 1000,
        'msg': 'Internal Error'
    }
    mock_get.return_value = mock_response
    
    # Retry decorator will call it 3 times
    with pytest.raises(Exception):
        client.get_account()

@patch('requests.post')
def test_place_order(mock_post, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 0,
        'data': {'orderID': '123'}
    }
    mock_post.return_value = mock_response
    
    order = client.place_order("BTCUSD", "Buy", 100, 40000)
    assert order['orderID'] == '123'
    # Verify post was called
    assert mock_post.called


@patch('requests.post')
def test_place_order_preserves_fractional_quantity(mock_post, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 0,
        'data': {'orderID': 'fractional-order'}
    }
    mock_post.return_value = mock_response

    order = client.place_order("BTCUSDT", "Buy", 0.0075)

    assert order["orderID"] == "fractional-order"
    assert mock_post.called
    assert mock_post.call_args.kwargs["json"]["orderQty"] == 0.0075
