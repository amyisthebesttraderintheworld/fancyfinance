import pytest
import yaml
import sys
import pandas as pd
from copy import deepcopy
from unittest.mock import MagicMock
from common import Candle, PhemexClient, TelegramNotifier

# Mock matplotlib to avoid ImportErrors during testing
sys.modules["matplotlib"] = MagicMock()
sys.modules["matplotlib.pyplot"] = MagicMock()

@pytest.fixture
def sample_config():
    return {
        'phemex': {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'testnet': True,
            'symbols': ['BTCUSD']
        },
        'strategy': {
            'timeframe': '1m',
            'fast_ma': 5,
            'slow_ma': 10,
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'volume_multiplier': 1.5,
            'atr_period': 14,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'bb_period': 20,
            'bb_std_dev': 2.0,
            'squeeze_threshold': 0.05,
            'use_macd_confirmation': False,
            'use_bollinger_squeeze': False,
        },
        'risk': {
            'max_positions': 3,
            'risk_per_trade': 0.02,
            'max_daily_loss': 0.10,
            'stop_loss_atr_mult': 2.0,
            'take_profit_atr_mult': 3.0
        },
        'backtest': {
            'start_date': '2024-01-01',
            'end_date': '2024-01-02',
            'initial_balance': 10000,
            'fee_rate': 0.0006,
            'slippage': 0.0005,
            'data_dir': 'tests/data'
        },
        'telegram': {
            'bot_token': '12345:token',
            'personal_mode': True,
            'admin_chat_ids': [12345],
            'enable_notifications': False
        },
        'scoring': {
            'trend_weight': 30,
            'rsi_weight': 25,
            'volume_weight': 25,
            'momentum_weight': 20,
            'min_score': 45,
        },
        'api': {
            'enabled': False,
            'host': '127.0.0.1',
            'port': 8000,
            'auth_token': '',
        },
        'safety': {
            'max_consecutive_losses': 3,
            'loss_window_minutes': 60,
            'timeout_duration_minutes': 30,
        },
        'exchange': 'phemex',
        'mode': 'simulation'
    }

@pytest.fixture
def mock_config(sample_config):
    return deepcopy(sample_config)

@pytest.fixture
def sample_candles():
    # 20 candles with a simple trend
    dates = pd.date_range('2024-01-01', periods=20, freq='1min')
    data = []
    for i in range(20):
        price = 40000 + i * 10
        data.append({
            'timestamp': int(dates[i].timestamp() * 1000),
            'open': float(price),
            'high': float(price + 5),
            'low': float(price - 5),
            'close': float(price + 2),
            'volume': 100.0
        })
    return data

@pytest.fixture
def mock_phemex_client():
    client = MagicMock(spec=PhemexClient)
    client.get_account.return_value = 1.0
    client.place_order.return_value = {'orderID': 'mock_123', 'code': 0}
    return client

@pytest.fixture
def mock_telegram(sample_config):
    notifier = MagicMock(spec=TelegramNotifier)
    notifier.config = sample_config
    return notifier
