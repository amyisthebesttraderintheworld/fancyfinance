import pytest
import yaml
import requests
from unittest.mock import patch, MagicMock
from common import (
    load_config, calculate_position_size, apply_slippage,
    calculate_fee, retry, PhemexClient, TelegramNotifier
)

def test_load_config_valid(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    p = d / "test_config.yaml"
    config_data = {'test': 'data'}
    p.write_text(yaml.dump(config_data))
    
    loaded = load_config(str(p))
    assert loaded == config_data

def test_load_config_missing():
    with pytest.raises(SystemExit):
        load_config("nonexistent_file.yaml")

def test_calculate_position_size():
    # balance=10000, risk=2% (200), stop_loss_dist=100
    qty = calculate_position_size(10000, 0.02, 100, 40000)
    assert qty == 2.0
    assert calculate_position_size(10000, 0.02, 0, 40000) == 0.0

def test_apply_slippage():
    # Long: 100 * (1 + 0.01) = 101
    assert apply_slippage(100.0, 0.01, 'long') == 101.0
    # Short: 100 * (1 - 0.01) = 99
    assert apply_slippage(100.0, 0.01, 'short') == 99.0

def test_calculate_fee():
    # 1 * 1000 * 0.0006 = 0.6
    assert calculate_fee(1, 1000, 0.0006) == 0.6

def test_retry_decorator():
    call_count = 0
    @retry(times=3, delay=0.01)
    def failing_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Fail")
        return "Success"

    result = failing_func()
    assert result == "Success"
    assert call_count == 3

# --- PhemexClient Mock Tests ---

@patch('requests.get')
def test_phemex_get_account(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 0,
        'data': {
            'account': {'accountBalanceEv': 100000000} # 1 BTC
        }
    }
    mock_get.return_value = mock_response
    
    client = PhemexClient("key", "secret", testnet=True)
    balance = client.get_account()
    assert balance == 1.0

@patch('requests.post')
def test_phemex_place_order(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'code': 0,
        'data': {'orderID': '123'}
    }
    mock_post.return_value = mock_response
    
    client = PhemexClient("key", "secret", testnet=True)
    order = client.place_order("BTCUSD", "Buy", 100, 40000)
    assert order['orderID'] == '123'
    # Check signature and payload presence (request was made)
    assert mock_post.called

# --- TelegramNotifier Tests ---

@patch('requests.post')
def test_telegram_personal_mode(mock_post, sample_config):
    sample_config['telegram']['personal_mode'] = True
    sample_config['telegram']['admin_chat_ids'] = [12345]
    sample_config['telegram']['enable_notifications'] = True
    
    notifier = TelegramNotifier(sample_config)
    notifier.send_message("Hello")
    
    assert mock_post.called
    args, kwargs = mock_post.call_args
    assert kwargs['json']['chat_id'] == 12345

@patch('requests.post')
def test_telegram_customer_mode(mock_post, sample_config):
    sample_config['telegram']['personal_mode'] = False
    sample_config['telegram']['enable_notifications'] = True
    
    notifier = TelegramNotifier(sample_config)
    notifier.user_chat_map = {'user_1': 9999}
    notifier.send_message("Hello", user_id='user_1')
    
    assert mock_post.called
    args, kwargs = mock_post.call_args
    assert kwargs['json']['chat_id'] == 9999