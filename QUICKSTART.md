# Quick Start Guide (Parents + Kids)

This guide gets the app running in about 5 minutes.

## 1. One-time setup

Open Terminal in this folder:

```bash
cd "/Users/jxie/Simple Portfolio Manager"
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Start the app

Run:

```bash
streamlit run app.py
```

Streamlit will print a local URL (usually `http://localhost:8501`).
Open that URL in your browser.

## 3. First-time kid flow

1. Add a kid name in the sidebar (`Add kid name` -> `Add Kid`).
2. In chat, type a trade, for example:
   - `I bought 2 AAPL at 185`
3. Review the pending trade card.
4. Click `Confirm Trade`.
5. Ask:
   - `show my portfolio`
   - `show my last 5 trades`
   - `pnl on AAPL`

## 4. Quick buttons kids can use

Just above chat input:

- `Show Portfolio`
- `Last 5 Trades`
- `Refresh Prices`

## 5. Where data is stored

The app writes CSV files to:

- `data/trades.csv` (all buys/sells)
- `data/prices.csv` (latest fetched prices)
- `data/positions.csv` (open positions + unrealized/realized P&L)
- `data/daily_snapshot.csv` (daily portfolio summary per kid)

## 6. Price source behavior

When refreshing prices:

1. Tries `yfinance` first
2. Falls back to `stooq` for missing/unavailable tickers

The chat message tells you which source was used.

## 7. Common commands kids can type

- `I bought 3 MSFT at 410`
- `I sold 1 MSFT at 420`
- `show my portfolio`
- `pnl on MSFT`
- `show my last 5 trades`
- `refresh prices`

## 8. Troubleshooting

- If a ticker fails:
  - Check symbol spelling (example: `BRK-B`).
- If price refresh fails:
  - Check internet connection and try again.
- If a sell is rejected:
  - The kid is trying to sell more shares than currently owned.

## 9. Stop the app

In the terminal window running Streamlit, press `Ctrl + C`.

## 10. Backup tip

Back up the `data/` folder regularly so trade history is never lost.

## 11. Optional: auto refresh every weekday

If you want daily updates without opening the app, follow:

- [SCHEDULER.md](SCHEDULER.md)
