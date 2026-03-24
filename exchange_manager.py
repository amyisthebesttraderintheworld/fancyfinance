import ccxt
import time
from typing import List, Dict, Any, Optional
from common import get_logger

class ExchangeManager:
    def __init__(self, exchange_id: str, api_key: str = None, api_secret: str = None, options: Dict[str, Any] = None):
        self.logger = get_logger(f"Exchange:{exchange_id}")
        self.exchange_id = exchange_id.lower()
        
        # Initialize CCXT exchange
        if not hasattr(ccxt, self.exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' not supported by CCXT.")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        self.client = exchange_class({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': options or {'defaultType': 'swap'} # Default to USDT Perpetuals
        })
        self.logger.info(f"Initialized {exchange_id} client.")

    def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 100):
        try:
            return self.client.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            self.logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return []

    def fetch_all_symbols(self, market_type: str = 'swap') -> List[str]:
        try:
            markets = self.client.load_markets()
            symbols = []
            for symbol, market in markets.items():
                if market.get('type') == market_type and market.get('active'):
                    symbols.append(symbol)
            return symbols
        except Exception as e:
            self.logger.error(f"Error fetching symbols: {e}")
            return []

    def fetch_balance(self) -> float:
        try:
            balance = self.client.fetch_balance()
            # Return total USDT balance for swap/perpetual
            return balance.get('total', {}).get('USDT', 0.0)
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return 0.0

    def create_order(self, symbol: str, type: str, side: str, amount: float, price: float = None, params: Dict[str, Any] = None):
        try:
            return self.client.create_order(symbol, type, side, amount, price, params)
        except Exception as e:
            self.logger.error(f"Order failed on {self.exchange_id}: {e}")
            raise

    def fetch_open_positions(self) -> List[Dict[str, Any]]:
        try:
            if self.client.has['fetchPositions']:
                return self.client.fetch_positions()
            return []
        except Exception as e:
            self.logger.error(f"Error fetching positions: {e}")
            return []
