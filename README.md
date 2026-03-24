# FancyFinance

> ⚠️ **IMPORTANT: FINANCIAL & LEGAL DISCLAIMER**  
> This software is for **educational and informational purposes only**. The developers are NOT financial advisors. Trading cryptocurrencies, especially derivatives, involves significant risk of loss. By using this software, you agree that the developers and contributors are NOT responsible for any financial losses or damages. **Read the full [LEGAL DISCLOSURES](./LEGAL.md) before use.**

A modular Python trading system supporting multiple exchanges (via CCXT), backtesting, paper trading, live trading, Telegram controls, and a FastAPI control plane.

## Modules

- **common.py**: Shared utilities, Phemex API client, Telegram wrapper, data structures.
- **scanner_long.py / scanner_short.py**: Strategy logic (MA crossover + RSI + MACD + Bollinger squeeze).
- **backtester.py**: Historical data testing engine.
- **simulator.py**: Real-time paper trading using WebSockets.
- **live_engine.py**: Real money trading engine.
- **telegram_bot.py**: Remote control interface.
- **api.py**: FastAPI health, stats, and control server.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration**:
   Copy `.env.example` to `.env`, then fill in your secrets. `config.yaml` now reads secrets from environment variables instead of storing them in plaintext.

3. **Data (For Backtesting)**:
   Place CSV files in a `data/` folder named format `{symbol}_{timeframe}.csv` (e.g., `BTCUSD_1m.csv`).
   Columns required: `timestamp,open,high,low,close,volume`.

## Usage

**Backtest**:
Set `mode: backtest` in `config.yaml` and run:
```bash
python main.py
```

**Simulation**:
Set `mode: simulation` and run:
```bash
python main.py
```
Interact via Telegram: `/status`, `/pause`, `/resume`.
API health/stats/control are exposed on port `8000` by default.

**Live Trading**:
Set `mode: live` and run:
```bash
python main.py
```
**WARNING**: Use at your own risk. Start with small amounts on Testnet first.

## Strategy

- **Long**: Fast MA crosses above Slow MA, RSI is oversold, with optional MACD and Bollinger squeeze confirmation.
- **Short**: Fast MA crosses below Slow MA, RSI is overbought, with optional MACD and Bollinger squeeze confirmation.
- **Exit**: MA cross back or Stop Loss / Take Profit (ATR based).

## API

- `GET /health` returns runtime health and version metadata.
- `GET /stats` returns balances, trade counts, and open positions.
- `POST /control/pause`, `/control/resume`, `/control/shutdown` manage the running engine.

## Testing

A comprehensive test suite is provided in the `tests/` directory.

### Running Tests

1.  **Install test dependencies**:
    ```bash
    pip install pytest pytest-mock pytest-cov pytest-asyncio
    ```

2.  **Run all tests**:
    ```bash
    PYTHONPATH=. pytest --cov=.
    ```

3.  **Run with integration tests (Requires API keys)**:
    ```bash
    # Set credentials for integration testing (Testnet)
    export PHEMEX_TESTNET_KEY="your_key"
    export PHEMEX_TESTNET_SECRET="your_secret"
    PYTHONPATH=. pytest tests/test_phemex_client_integration.py -v
    ```

### Test Structure

- **`tests/test_common.py`**: Unit tests for utilities (config, calculation, retries).
- **`tests/test_scanner_long.py` & `tests/test_scanner_short.py`**: Unit tests for strategy scanners with simulated candle sequences.
- **`tests/test_backtester.py`**: Unit tests for the backtest engine with synthetic data.
- **`tests/test_telegram_bot.py`**: Unit tests for bot commands and authentication.
- **`tests/test_phemex_client.py`**: Mocked tests for API interaction.
- **`tests/test_simulator.py`**: Tests for paper trading with mock WebSocket data.
- **`tests/test_live_engine.py`**: Tests for the real trading engine with mock safety and execution checks.

## Machine Learning Dataset Generation

You can generate a technical indicator dataset from historical data for machine learning.

1.  **Generate Dataset**:
    ```bash
    python generate_dataset.py \
      --symbols BTCUSD,ETHUSD \
      --start 2023-01-01 \
      --end 2024-01-01 \
      --output data/ml_dataset.parquet \
      --lookahead 10 \
      --threshold 0.01
    ```

2.  **Using with Google Drive (in Colab/Mount)**:
    ```bash
    # Assuming Drive is mounted at /content/drive
    python generate_dataset.py --output /content/drive/MyDrive/trading_dataset.parquet
    ```

The script will save both the dataset and a metadata JSON file with feature descriptions.
