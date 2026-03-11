from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

TRADES_CSV = DATA_DIR / "trades.csv"
PRICES_CSV = DATA_DIR / "prices.csv"
POSITIONS_CSV = DATA_DIR / "positions.csv"
SNAPSHOT_CSV = DATA_DIR / "daily_snapshot.csv"

TRADE_COLUMNS = [
    "timestamp",
    "kid",
    "action",
    "ticker",
    "shares",
    "price",
    "fees",
    "note",
    "source_text",
]

PRICE_COLUMNS = [
    "as_of",
    "ticker",
    "price",
    "source",
]

POSITION_COLUMNS = [
    "as_of",
    "kid",
    "ticker",
    "shares",
    "avg_cost",
    "market_price",
    "market_value",
    "unrealized_pnl",
    "realized_pnl",
    "pnl_pct",
]

SNAPSHOT_COLUMNS = [
    "date",
    "kid",
    "total_cost",
    "total_value",
    "unrealized_pnl",
    "day_change",
]
