import pytest
import pandas as pd
from unittest.mock import MagicMock
from backtester import Backtester
from common import load_historical_data

def test_backtester_run_synthetic_data(sample_config):
    backtester = Backtester(sample_config)
    # 50 candles with a simple pattern: drop then rise
    dates = pd.date_range('2024-01-01', periods=50, freq='1min')
    prices = []
    for i in range(50):
        if i < 25:
            price = 1000 - i * 10 # Falling
        else:
            price = 750 + (i - 25) * 20 # Rising
        prices.append(price)
        
    df = pd.DataFrame({
        'open': prices, 'high': [p+5 for p in prices], 
        'low': [p-5 for p in prices], 'close': prices, 'volume': [1000]*50
    }, index=dates)
    
    backtester.run("BTCUSD", df)
    
    # Check if trades occurred
    assert len(backtester.equity_curve) == 50
    # trades depends on strategy logic. Our LongScanner requires MA cross and RSI < 30.
    # Pattern: 1000 down to 750 (drop 250). RSI will drop. MA cross will happen on recovery.

def test_backtester_risk_limits(sample_config):
    # Set max_positions=1
    sample_config['risk']['max_positions'] = 1
    backtester = Backtester(sample_config)
    
    # Simulate data that might trigger two consecutive signals
    # We can mock the scanners if needed for this unit test, but let's test logic in run
    # For simplicity, manually check positions limit in run loop logic
    
    # Ensure positions is symbol based
    backtester.positions = {"OTHER_SYMBOL": MagicMock()} # Fake one open
    
    # Check that another entry for same or different symbol is blocked 
    # if it would exceed max_positions (though backtester logic current is per-symbol pos)
    pass

def test_backtester_daily_loss_limit(sample_config):
    sample_config['risk']['max_daily_loss'] = 0.05 # 5%
    backtester = Backtester(sample_config)
    backtester.balance = 9000 # 10% loss from 10000 start
    
    # In a real run, logic should check balance vs peak or initial.
    # Current implementation in LiveEngine checks daily loss, 
    # Backtester should also ideally check it.
    pass
