import pytest
from scanner_short import ShortScanner
from common import Candle, Signal

def test_short_scanner_initial_state(mock_config):
    scanner = ShortScanner(mock_config)
    assert not scanner.has_position
    assert len(scanner.candles) == 0

def test_short_scanner_entry_logic(mock_config):
    scanner = ShortScanner(mock_config)
    
    for i in range(25):
        if i < 15:
            price = 100 + i # Increasing price, RSI will rise
        else:
            price = 115 - (i - 15) * 2 # Drop, trigger MA cross down
            
        candle = Candle(1000 + i*60000, price, price+1, price-1, price, 100)
        signal = scanner.update(candle)
        
        if signal and signal.direction == 'short':
            assert scanner.has_position
            assert signal.entry_price == price
            assert signal.stop_loss > price
            assert signal.take_profit < price
            return

def test_short_scanner_exit_logic(mock_config):
    scanner = ShortScanner(mock_config)
    scanner.has_position = True
    
    for i in range(20):
        if i < 10:
            price = 100 - i # Falling price
        else:
            price = 90 + (i - 10) * 2 # Rise, trigger MA cross up
            
        candle = Candle(1000 + i*60000, price, price+1, price-1, price, 100)
        signal = scanner.update(candle)
        
        if signal and signal.direction is None:
            assert not scanner.has_position
            assert signal.exit_reason == "MA Cross Up"
            return
