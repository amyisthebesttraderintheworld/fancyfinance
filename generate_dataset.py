import os
import argparse
import pandas as pd
import numpy as np
import yaml
import json
from datetime import datetime
from common import load_config, get_logger, load_historical_data, Candle
from scanner_long import LongScanner
from scanner_short import ShortScanner

# --- Feature Engineering Functions ---

def compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_bollinger_bands(prices, period=20, std_dev=2):
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, lower

def generate_features(df, config):
    logger = get_logger("FeatureEngineering")
    logger.info("Computing features...")
    
    # Returns
    for window in [1, 5, 10, 20]:
        df[f'return_{window}'] = np.log(df['close'] / df['close'].shift(window))
        
    # Moving Averages
    for window in [5, 10, 20, 50, 200]:
        df[f'ma_{window}'] = df['close'].rolling(window=window).mean()
        df[f'ma_{window}_rel'] = df['close'] / df[f'ma_{window}']
        
    # MA Crossovers
    df['ma_5_10_cross'] = np.where(df['ma_5'] > df['ma_10'], 1, -1)
    
    # RSI
    df['rsi'] = compute_rsi(df['close'], period=config['strategy']['rsi_period'])
    
    # Volume Ratio
    df['vol_sma_20'] = df['volume'].rolling(window=20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma_20']
    
    # Volatility (Simple Std Dev of returns)
    df['volatility_20'] = df['return_1'].rolling(window=20).std()
    
    # Bollinger Bands
    upper, lower = compute_bollinger_bands(df['close'])
    df['bb_upper_rel'] = df['close'] / upper
    df['bb_lower_rel'] = df['close'] / lower
    
    # Scanner Signals
    logger.info("Computing strategy signals as features...")
    long_scanner = LongScanner(config)
    short_scanner = ShortScanner(config)
    
    long_signals = []
    short_signals = []
    
    for idx, row in df.iterrows():
        # In this dataset generator, we process each candle
        # Note: scanner needs a history. We can reuse its update but for all history.
        # This is simplified here to avoid excessive overhead, but should use scanners.
        candle = Candle(int(idx.timestamp()*1000), row['open'], row['high'], row['low'], row['close'], row['volume'])
        
        ls = long_scanner.update(candle)
        ss = short_scanner.update(candle)
        
        long_signals.append(1 if ls and ls.direction == 'long' else 0)
        short_signals.append(1 if ss and ss.direction == 'short' else 0)
        
    df['signal_long'] = long_signals
    df['signal_short'] = short_signals
    
    return df

def generate_labels(df, lookahead=5, threshold=0.005):
    logger = get_logger("LabelGeneration")
    logger.info(f"Generating labels with lookahead={lookahead} and threshold={threshold}...")
    
    # Regression: Forward returns
    df['label_reg'] = (df['close'].shift(-lookahead) / df['close']) - 1
    
    # Classification: Price goes up by > threshold within next 'lookahead' steps
    # Note: Using max price in next 'lookahead' windows for a 'target hit' label
    future_max = df['close'].shift(-lookahead).rolling(window=lookahead).max() # Simplified approximation
    # Better: use a loop or proper shift for classification
    
    # For simplicity, just use forward return relative to threshold
    df['label_class'] = np.where(df['label_reg'] > threshold, 1, 0)
    
    return df

def main():
    parser = argparse.ArgumentParser(description="Trading Dataset Generator")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--symbols", type=str, help="Comma separated symbols (e.g. BTCUSD,ETHUSD)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="trading_dataset.csv", help="Output path (can be Google Drive path)")
    parser.add_argument("--lookahead", type=int, default=5, help="Lookahead periods for labels")
    parser.add_argument("--threshold", type=float, default=0.005, help="Threshold for classification label (e.g. 0.005 for 0.5%)")
    
    args = parser.parse_args()
    
    config = load_config(args.config)
    logger = get_logger("DatasetGenerator")
    
    symbols = args.symbols.split(',') if args.symbols else config['phemex']['symbols']
    start_date = args.start if args.start else config['backtest']['start_date']
    end_date = args.end if args.end else config['backtest']['end_date']
    
    all_data = []
    
    for symbol in symbols:
        logger.info(f"Processing {symbol}...")
        df = load_historical_data(symbol, config['strategy']['timeframe'], 
                                  start_date, end_date, 
                                  config['backtest']['data_dir'])
        
        if df.empty:
            logger.warning(f"No data found for {symbol}")
            continue
            
        df = generate_features(df, config)
        df = generate_labels(df, lookahead=args.lookahead, threshold=args.threshold)
        
        df['symbol'] = symbol
        # Drop rows with NaN from rolling calculations and forward labels
        df.dropna(inplace=True)
        
        all_data.append(df)
        
    if not all_data:
        logger.error("No data processed. Exiting.")
        return
        
    dataset = pd.concat(all_data)
    
    # Output to CSV or Parquet based on extension
    ext = os.path.splitext(args.output)[1].lower()
    logger.info(f"Saving dataset to {args.output}...")
    
    if ext == '.parquet':
        dataset.to_parquet(args.output)
    else:
        dataset.to_csv(args.output)
        
    # Metadata
    metadata = {
        "features": list(dataset.columns),
        "lookahead": args.lookahead,
        "threshold": args.threshold,
        "symbols": symbols,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    meta_path = os.path.splitext(args.output)[0] + "_metadata.json"
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=4)
        
    logger.info(f"Dataset generation complete. {len(dataset)} samples saved.")

if __name__ == "__main__":
    main()
