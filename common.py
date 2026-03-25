from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ENV_PATTERN = re.compile(r"^\$\{([^}:]+)(?::-([^}]*))?\}$")

# --- Configuration ---

def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = ENV_PATTERN.match(value.strip())
        if match:
            env_key, default_value = match.groups()
            return os.getenv(env_key, default_value or "")
    return value


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    exchange_id = config.get("exchange", "phemex")
    if exchange_id in config:
        exchange_cfg = config[exchange_id]
        if os.getenv("PHEMEX_API_KEY"):
            exchange_cfg["api_key"] = os.getenv("PHEMEX_API_KEY")
        if os.getenv("PHEMEX_API_SECRET"):
            exchange_cfg["api_secret"] = os.getenv("PHEMEX_API_SECRET")

    if "telegram" in config and os.getenv("TELEGRAM_BOT_TOKEN") is not None:
        config["telegram"]["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", config["telegram"].get("bot_token", ""))

    if "supabase" in config:
        if os.getenv("SUPABASE_URL") is not None:
            config["supabase"]["url"] = os.getenv("SUPABASE_URL", config["supabase"].get("url", ""))
        if os.getenv("SUPABASE_SERVICE_ROLE_KEY") is not None:
            config["supabase"]["service_role_key"] = os.getenv(
                "SUPABASE_SERVICE_ROLE_KEY",
                config["supabase"].get("service_role_key", ""),
            )

    if "api" in config and os.getenv("FANCYFINANCE_API_TOKEN") is not None:
        config["api"]["auth_token"] = os.getenv("FANCYFINANCE_API_TOKEN", config["api"].get("auth_token", ""))
    return config


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            config = yaml.safe_load(f) or {}
        config = _resolve_env_placeholders(config)
        return _apply_env_overrides(config)
    except Exception as e:
        logger.error(f"Failed to load config from {path}: {e}")
        sys.exit(1)

# --- Logging ---

def setup_logging(log_file: str = "trading_bot.log"):
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(log_file, rotation="10 MB", level="DEBUG")

def get_logger(name: str):
    return logger.bind(name=name)

# --- Data Structures ---

@dataclass
class Candle:
    timestamp: int  # Unix timestamp in milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str = ""

@dataclass
class Signal:
    timestamp: int
    symbol: str
    direction: str  # 'long', 'short', or None (for exit only/neutral)
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    exit_reason: Optional[str] = None
    score: Optional[Any] = None   # AssetScorer.ScoreResult attached at signal time

@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    open_time: int

@dataclass
class Trade:
    entry_time: int
    exit_time: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    fee: float

# --- Utilities ---

def retry(times=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == times - 1:
                        raise e
                    time.sleep(delay)
        return wrapper
    return decorator

def timestamp_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

def str_to_timestamp(date_str: str) -> int:
    dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def calculate_position_size(balance: float, risk_percent: float, stop_loss_distance: float, price: float) -> float:
    if stop_loss_distance <= 0:
        return 0.0
    risk_amount = balance * risk_percent
    # Risk amount = quantity * stop_loss_distance
    quantity = risk_amount / stop_loss_distance
    return quantity

def apply_slippage(price: float, slippage_percent: float, direction: str) -> float:
    if direction == 'long':
        return price * (1 + slippage_percent)
    else:
        return price * (1 - slippage_percent)

def calculate_fee(quantity: float, price: float, fee_rate: float) -> float:
    return quantity * price * fee_rate

def load_historical_data(symbol: str, timeframe: str, start: str, end: str, data_dir: str) -> pd.DataFrame:
    # This is a placeholder. In a real scenario, you'd load from CSVs downloaded from Phemex or another provider.
    # Expected CSV format: timestamp,open,high,low,close,volume
    import os
    file_path = os.path.join(data_dir, f"{symbol}_{timeframe}.csv")
    if not os.path.exists(file_path):
        logger.warning(f"Data file not found: {file_path}")
        return pd.DataFrame()
    
    df = pd.read_csv(file_path)
    # Ensure timestamp is datetime if needed, or keep as int. 
    # For this system, we mostly use int timestamps for Candle objects, but pandas likes DatetimeIndex.
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter by date
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    
    return df

# --- Phemex Client ---

class PhemexClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = "https://testnet-api.phemex.com" if testnet else "https://api.phemex.com"
        self.logger = get_logger("PhemexClient")

    def _generate_signature(self, endpoint: str, query_string: str, expiry: int) -> str:
        message = f"{endpoint}{query_string}{expiry}"
        return hmac.new(self.api_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

    @retry(times=3)
    def _request(self, method: str, endpoint: str, params: dict = None):
        expiry = int(time.time() + 60)
        query_string = ""
        if params:
            # Sort params usually required, but simple approach here
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items()) if v is not None])
        
        signature = self._generate_signature(endpoint, query_string, expiry)
        
        headers = {
            "x-phemex-access-token": self.api_key,
            "x-phemex-request-expiry": str(expiry),
            "x-phemex-request-signature": signature,
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}{endpoint}"
        if query_string:
            url += f"?{query_string}"
            
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=15)
            elif method == "POST":
                # For POST, params might need to be body. Adjust based on specific Phemex endpoint docs.
                # Simplification: Phemex often uses query params even for POST or JSON body.
                # Assuming JSON body for POST in this simplified client if not query.
                response = requests.post(url, headers=headers, json=params, timeout=15)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=15)
            else:
                raise ValueError(f"Unsupported method {method}")

            response.raise_for_status()
            data = response.json()
            if data.get('code') != 0:
                raise Exception(f"Phemex API Error: {data}")
            return data['data']
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            raise

    def get_account(self) -> float:
        # Simplified: fetching BTC balance for contract account
        data = self._request("GET", "/accounts/accountPositions", {"currency": "BTC"})
        # Parse data to find balance. Structure varies by account type.
        # This is a placeholder logic for the structure
        try:
            return float(data['account']['accountBalanceEv']) / 100000000 # Satoshi to BTC
        except:
            return 0.0

    def place_order(self, symbol: str, side: str, qty: int, price: float = None, post_only: bool = False):
        # side: Buy or Sell
        params = {
            "symbol": symbol,
            "side": side,
            "orderQty": int(qty),
            "ordType": "Limit" if price else "Market",
        }
        if price:
            params["priceEp"] = int(price * 10000) # Assuming scale
            if post_only:
                params["postOnly"] = True
        
        return self._request("POST", "/orders", params)

    def cancel_order(self, symbol: str, order_id: str):
        return self._request("DELETE", "/orders/cancel", {"symbol": symbol, "orderID": order_id})

    def get_open_orders(self, symbol: str):
        return self._request("GET", "/orders/activeList", {"symbol": symbol})

    def get_all_symbols(self, type: str = "Perpetual") -> List[str]:
        """
        Fetches all available symbols from Phemex.
        type: Perpetual, Spot
        """
        try:
            response = requests.get(f"{self.base_url}/public/products", timeout=15)
            response.raise_for_status()
            data = response.json()
            
            symbols = []
            
            # Traditional products list (Inverse/Spot)
            if 'products' in data['data']:
                for item in data['data']['products']:
                    if item['type'] == type and item['status'] == 'Listed':
                        # For USDT perps, we prefer the v2 node, but we'll include any found here
                        symbols.append(item['symbol'])
            
            # v2 products list (USDT Linear/Hedged)
            if 'perpProductsV2' in data['data'] and type == 'Perpetual':
                for item in data['data']['perpProductsV2']:
                    if item['status'] == 'Listed' and item['symbol'] not in symbols:
                        symbols.append(item['symbol'])
                        
            return symbols
        except Exception as e:
            self.logger.error(f"Failed to fetch symbols: {e}")
            return []

import json
import os

class SettingsManager:
    def __init__(self, file_path: str = "bot_settings.json"):
        self.file_path = file_path
        self.logger = get_logger("SettingsManager")
        self.defaults = {
            "trading_enabled": {"type": "Boolean", "value": True, "desc": "Global master switch for trading."},
            "risk_multiplier": {"type": "Number", "value": 1.0, "desc": "Multiplier for calculated position sizes."},
            "max_daily_trades": {"type": "Number", "value": 10, "desc": "Max trades allowed per 24h window."},
            "notification_level": {"type": "Text", "value": "All", "desc": "Filtering: All, Trades, or Errors only."}
        }
        self.settings = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    return json.load(f)
            except Exception as exc:
                self.logger.warning(f"Failed to load settings from {self.file_path}: {exc}")
        return json.loads(json.dumps(self.defaults))

    def save(self):
        try:
            with open(self.file_path, "w") as f:
                json.dump(self.settings, f, indent=4)
            return True
        except Exception as exc:
            self.logger.warning(f"Failed to save settings to {self.file_path}: {exc}")
            return False

    def get(self, key):
        return self.settings.get(key, {}).get("value")

    def set(self, key, value, data_type="Text", desc="Custom field"):
        if key not in self.settings:
            self.settings[key] = {"type": data_type, "value": value, "desc": desc}
            self.save()
            return True
            
        target_type = self.settings[key]["type"]
        try:
            if target_type == "Number":
                value = float(value)
            elif target_type == "Boolean":
                value = str(value).lower() in ['true', '1', 'yes']
            self.settings[key]["value"] = value
            return True
        except:
            return False
        finally:
            self.save()

    def list_all(self):
        return self.settings

# --- Telegram Notifier ---

class TelegramNotifier:
    def __init__(self, config: Dict[str, Any]):
        self.token = config['telegram']['bot_token']
        self.personal_mode = config['telegram']['personal_mode']
        self.admin_chat_ids = config['telegram']['admin_chat_ids']
        self.enable_notifications = config['telegram']['enable_notifications']
        self.user_chat_map = {} # user_id -> chat_id for customer mode
        self.logger = get_logger("TelegramNotifier")

    def send_message(self, text: str, user_id: str = None):
        if not self.enable_notifications or not self.token:
            return

        # Simple emoji mapping for better UX
        formatted_text = text
        if "ENTRY" in text:
            try:
                symbol = text.split(":")[1].split()[1]
                tv_link = f"https://www.tradingview.com/chart/?symbol=PHEMEX:{symbol}"
                formatted_text = f"🔵 *NEW TRADE ENTRY* 🚀\n\n{text}\n\n[📈 View on TradingView]({tv_link})"
            except (IndexError, ValueError):
                formatted_text = text
        elif "EXIT" in text:
            formatted_text = f"🔴 *TRADE CLOSED* 🏁\n\n{text}"
        elif "PAUSED" in text:
            formatted_text = f"⏸ *SYSTEM PAUSED* \n\n{text}"

        chat_ids = []
        if self.personal_mode:
            chat_ids = self.admin_chat_ids
        elif user_id and user_id in self.user_chat_map:
            chat_ids = [self.user_chat_map[user_id]]
        elif not user_id: # Broadcast to admins if no specific user
            chat_ids = self.admin_chat_ids

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        for chat_id in chat_ids:
            try:
                requests.post(
                    url,
                    json={"chat_id": chat_id, "text": formatted_text, "parse_mode": "Markdown"},
                    timeout=15,
                )
            except Exception as e:
                self.logger.error(f"Failed to send telegram message: {e}")

    def send_photo(self, photo_path: str, caption: str = "", user_id: str = None):
        # Implementation similar to send_message but using sendPhoto endpoint
        pass
