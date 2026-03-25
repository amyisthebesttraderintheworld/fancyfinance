import argparse
import queue
import threading
from queue import Queue, Empty

from api import start_api_server
from backtester import Backtester
from common import TelegramNotifier, get_logger, load_config, load_historical_data, setup_logging
from exchange_manager import ExchangeManager
from fancyfinance import APP_NAME, __version__
from live_engine import LiveEngine
from simulator import Simulator
from supabase_client import SupabaseManager
from telegram_bot import run_bot

SYMBOL_FETCH_TIMEOUT_SECONDS = 15


def _set_symbols(config, exchange_id, symbols):
    config[exchange_id]['symbols'] = symbols
    config['symbols'] = symbols


def _resolve_market_type(exchange_config):
    raw_value = exchange_config.get('market_type') or exchange_config.get('symbol_type') or 'swap'
    normalized = str(raw_value).strip().lower()
    aliases = {
        'perpetual': 'swap',
        'perp': 'swap',
        'swap': 'swap',
        'spot': 'spot',
        'future': 'future',
        'futures': 'future',
        'all': 'all',
        '*': 'all',
    }
    return aliases.get(normalized, normalized)


def _describe_market_scope(market_type):
    return "all active" if market_type == "all" else f"all {market_type}"


def _fetch_symbols_with_timeout(exchange_id, api_key, api_secret, market_type, logger, timeout_seconds=SYMBOL_FETCH_TIMEOUT_SECONDS):
    result_queue: Queue = Queue(maxsize=1)

    def worker():
        try:
            client = ExchangeManager(exchange_id, api_key, api_secret)
            symbols = client.fetch_all_symbols(market_type=market_type)
            result_queue.put(("ok", symbols))
        except Exception as exc:  # pragma: no cover - defensive runtime path
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, name="symbol-fetch", daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        logger.warning(
            f"Symbol discovery exceeded {timeout_seconds}s. Continuing startup with configured symbols."
        )
        return None

    try:
        status, payload = result_queue.get_nowait()
    except Empty:
        return None

    if status == "error":
        logger.warning(f"Symbol discovery failed. Continuing startup with configured symbols: {payload}")
        return None

    return payload


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} algorithmic trading platform")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    parser.add_argument("--exchange", type=str, default="phemex", help="Exchange to trade on (e.g. binance, phemex, bybit)")
    parser.add_argument("--symbol", type=str, help="Specific symbol to trade (e.g. BTCUSDT).")
    parser.add_argument("--user_id", type=int, help="Optional user ID to fetch API keys from Supabase.")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging()
    logger = get_logger("Main")
    logger.info(f"Starting {APP_NAME} v{__version__}")
    
    # Merge CLI exchange into config
    config['exchange'] = args.exchange.lower()
    exchange_id = config['exchange']
    
    # Ensure exchange-specific config section exists
    if exchange_id not in config:
        config[exchange_id] = {"symbols": [], "api_key": None, "api_secret": None}

    # Dynamic API Key Loading
    if args.user_id:
        db = SupabaseManager()
        if config["mode"] in ["simulation", "live"] and not db.user_can_access_mode(args.user_id, config["mode"]):
            logger.error(
                f"User {args.user_id} does not have an active paid membership required for {config['mode']} mode."
            )
            return

        if config["mode"] == "live":
            user = db.get_or_create_user(args.user_id, "", "")
            if not user or not user.get("is_verified"):
                logger.error(f"User {args.user_id} must verify their email before live mode can start.")
                return

        user_keys = db.get_user_api_keys(args.user_id)
        if user_keys:
            config[exchange_id]['api_key'] = user_keys['api_key']
            config[exchange_id]['api_secret'] = user_keys['api_secret']
            logger.info(f"Loaded encrypted API keys for {exchange_id} from Supabase for User ID: {args.user_id}")
    
    # Standardize top-level keys for engine
    config['api_key'] = config[exchange_id].get('api_key')
    config['api_secret'] = config[exchange_id].get('api_secret')

    mode = config['mode']
    logger.info(f"Starting in {mode} mode on {exchange_id}")
    
    ex_config = config[exchange_id]
    market_type = _resolve_market_type(ex_config)
    market_scope = _describe_market_scope(market_type)
    default_symbols = ex_config.get('symbols', ['BTCUSDT'])

    if args.symbol:
        symbols = [args.symbol]
        logger.info(f"Using symbol from command line: {args.symbol}")
    else:
        symbols = default_symbols
        if ex_config.get('scan_all_symbols', True):
            logger.info(f"Using bootstrap symbols from config while discovering {market_scope} symbols: {symbols}")
        else:
            logger.info(f"Using symbols from config: {symbols}")

    _set_symbols(config, exchange_id, symbols)

    if mode == 'backtest':
        backtester = Backtester(config)
        # Load data for each symbol
        for symbol in config['symbols']:
            # Example data loading
            df = load_historical_data(
                symbol,
                config['strategy']['timeframe'],
                config['backtest']['start_date'],
                config['backtest']['end_date'],
                config['backtest']['data_dir'],
            )
            if not df.empty:
                backtester.run(symbol, df)
        
        backtester.generate_report()
        
    elif mode in ['simulation', 'live']:
        command_queue = queue.Queue()
        notifier = TelegramNotifier(config)
        
        if mode == 'simulation':
            engine = Simulator(config, notifier, command_queue)
        else:
            engine = LiveEngine(config, notifier, command_queue)

        start_api_server(engine, config)

        if not args.symbol and ex_config.get('scan_all_symbols', True):
            fetched_symbols = _fetch_symbols_with_timeout(
                exchange_id,
                config['api_key'],
                config['api_secret'],
                market_type,
                logger,
            )
            if fetched_symbols:
                _set_symbols(config, exchange_id, fetched_symbols)
                engine.symbols = fetched_symbols
                if hasattr(engine, "_ensure_symbol_state"):
                    for symbol in fetched_symbols:
                        engine._ensure_symbol_state(symbol)
                logger.info(f"Scanning all {len(fetched_symbols)} {exchange_id} {market_scope} symbols.")
            else:
                logger.warning(f"Using configured symbols for startup: {config['symbols']}")
            
        # Start Telegram Bot in separate thread
        if config['telegram']['bot_token']:
            bot_thread = threading.Thread(target=run_bot, args=(engine, command_queue))
            bot_thread.daemon = True
            bot_thread.start()
        
        # Check if API Keys were deferred for dynamic loading
        if not config[exchange_id].get('api_key') or config[exchange_id]['api_key'] == "YOUR_API_KEY":
            if mode == 'live':
                logger.warning(f"Live mode active but API keys missing from config for {exchange_id}. Waiting for /setup_api via Telegram.")
        
        # Start Engine (blocking)
        engine.start()        
    else:
        logger.error(f"Invalid mode: {mode}")

if __name__ == "__main__":
    main()
