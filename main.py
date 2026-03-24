import argparse
import queue
import threading

from api import start_api_server
from backtester import Backtester
from common import TelegramNotifier, get_logger, load_config, load_historical_data, setup_logging
from exchange_manager import ExchangeManager
from fancyfinance import APP_NAME, __version__
from live_engine import LiveEngine
from simulator import Simulator
from supabase_client import SupabaseManager
from telegram_bot import run_bot

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
    
    # Handle Dynamic Symbols
    ex_config = config[exchange_id]
    
    if args.symbol:
        symbols = [args.symbol]
        logger.info(f"Using symbol from command line: {args.symbol}")
    elif ex_config.get('scan_all_symbols', True):
        client = ExchangeManager(exchange_id, config['api_key'], config['api_secret'])
        fetched_symbols = client.fetch_all_symbols(market_type=ex_config.get('market_type', 'swap'))
        if fetched_symbols:
            symbols = fetched_symbols
            logger.info(f"Scanning all {len(symbols)} {exchange_id} {ex_config.get('market_type', 'swap')} symbols.")
        else:
            symbols = ex_config.get('symbols', ['BTCUSDT'])
            logger.warning(f"Could not fetch symbols, using default symbols from config: {symbols}")
    else:
        symbols = ex_config['symbols']
        logger.info(f"Using symbols from config: {symbols}")
            
    # Update config with fetched symbols for engine
    config[exchange_id]['symbols'] = symbols
    config['symbols'] = symbols # Also set top-level for engine ease

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
            
        # Start Telegram Bot in separate thread
        if config['telegram']['bot_token']:
            bot_thread = threading.Thread(target=run_bot, args=(engine, command_queue))
            bot_thread.daemon = True
            bot_thread.start()

        start_api_server(engine, config)
        
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
