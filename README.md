# Kids Portfolio Chat (Streamlit + CSV)

Simple investing tracker for kids with chat-style trade entry and local CSV storage.

## Release: MVP v0.1

### What ships in this release

- Chat-first Streamlit interface for entering trades in plain English
- Confirm/cancel trade workflow before any write to disk
- Local CSV portfolio ledger (no Google Sheets dependency)
- Price refresh using free market data via `yfinance`
- Per-kid portfolio summary with unrealized P&L and daily change

### Current scope

- Supports long-only buy/sell equity and ETF trades
- Uses local CSV files as source of truth
- Designed for educational use on a trusted local machine

## Features

- Chat input for trades: `I bought 2 AAPL at 185`
- Confirmation required before writing a trade
- Local CSV files for trades, prices, positions, and daily snapshots
- Price refresh from `yfinance`
- Per-kid portfolio view with daily P&L summary

## Quick start

1. Create a virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the app:
   ```bash
   streamlit run app.py
   ```
3. Open the local Streamlit URL shown in the terminal.

## Data files

CSV files are created automatically in `data/`:

- `trades.csv`
- `prices.csv`
- `positions.csv`
- `daily_snapshot.csv`

## Notes

- Educational tool only; not investment advice.
- `yfinance` is free and convenient but has no uptime/data SLA.
