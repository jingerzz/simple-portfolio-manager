# Kids Portfolio Chat (Streamlit + CSV)

Simple investing tracker for kids with chat-style trade entry and local CSV storage.

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
