from pathlib import Path
from typing import Iterable, List

import pandas as pd

from .config import (
    DATA_DIR,
    POSITION_COLUMNS,
    POSITIONS_CSV,
    PRICE_COLUMNS,
    PRICES_CSV,
    SNAPSHOT_COLUMNS,
    SNAPSHOT_CSV,
    TRADE_COLUMNS,
    TRADES_CSV,
)


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_csv(TRADES_CSV, TRADE_COLUMNS)
    _ensure_csv(PRICES_CSV, PRICE_COLUMNS)
    _ensure_csv(POSITIONS_CSV, POSITION_COLUMNS)
    _ensure_csv(SNAPSHOT_CSV, SNAPSHOT_COLUMNS)


def load_trades() -> pd.DataFrame:
    frame = _load_csv(TRADES_CSV, TRADE_COLUMNS)
    if frame.empty:
        return frame

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["kid"] = frame["kid"].astype(str).str.strip()
    frame["action"] = frame["action"].astype(str).str.upper().str.strip()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    for column in ("shares", "price", "fees"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def load_prices() -> pd.DataFrame:
    frame = _load_csv(PRICES_CSV, PRICE_COLUMNS)
    if frame.empty:
        return frame

    frame["as_of"] = pd.to_datetime(frame["as_of"], utc=True, errors="coerce")
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["source"] = frame["source"].astype(str).str.strip()
    return frame


def load_positions() -> pd.DataFrame:
    frame = _load_csv(POSITIONS_CSV, POSITION_COLUMNS)
    if frame.empty:
        return frame

    frame["as_of"] = pd.to_datetime(frame["as_of"], utc=True, errors="coerce")
    frame["kid"] = frame["kid"].astype(str).str.strip()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    for column in ("shares", "avg_cost", "market_price", "market_value", "unrealized_pnl", "pnl_pct"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_snapshots() -> pd.DataFrame:
    frame = _load_csv(SNAPSHOT_CSV, SNAPSHOT_COLUMNS)
    if frame.empty:
        return frame

    frame["date"] = frame["date"].astype(str).str.strip()
    frame["kid"] = frame["kid"].astype(str).str.strip()
    for column in ("total_cost", "total_value", "unrealized_pnl", "day_change"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def append_trade(trade: dict) -> None:
    ensure_data_files()
    row = pd.DataFrame([trade], columns=TRADE_COLUMNS)
    _append_rows(TRADES_CSV, row)


def append_prices(price_rows: Iterable[dict]) -> None:
    rows = list(price_rows)
    if not rows:
        return
    ensure_data_files()
    frame = pd.DataFrame(rows, columns=PRICE_COLUMNS)
    _append_rows(PRICES_CSV, frame)


def save_positions(positions_df: pd.DataFrame) -> None:
    ensure_data_files()
    output = positions_df.copy()
    for column in POSITION_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[POSITION_COLUMNS]
    output.to_csv(POSITIONS_CSV, index=False)


def upsert_daily_snapshots(new_rows: pd.DataFrame) -> None:
    ensure_data_files()
    if new_rows.empty:
        return

    existing = load_snapshots()
    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined["date"] = combined["date"].astype(str).str.strip()
    combined["kid"] = combined["kid"].astype(str).str.strip()
    combined = combined.sort_values(["date", "kid"])
    combined = combined.drop_duplicates(subset=["date", "kid"], keep="last")
    for column in SNAPSHOT_COLUMNS:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined = combined[SNAPSHOT_COLUMNS]
    combined.to_csv(SNAPSHOT_CSV, index=False)


def latest_prices(prices_df: pd.DataFrame) -> pd.DataFrame:
    if prices_df.empty:
        return pd.DataFrame(columns=["ticker", "price", "as_of"])

    ordered = prices_df.sort_values("as_of")
    latest = ordered.drop_duplicates(subset=["ticker"], keep="last")
    return latest[["ticker", "price", "as_of"]].reset_index(drop=True)


def known_kids(trades_df: pd.DataFrame) -> List[str]:
    if trades_df.empty:
        return []
    kids = (
        trades_df["kid"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(kids)


def _ensure_csv(path: Path, columns: List[str]) -> None:
    if path.exists():
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def _load_csv(path: Path, columns: List[str]) -> pd.DataFrame:
    ensure_data_files()
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)

    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns]


def _append_rows(path: Path, rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    header = not path.exists() or path.stat().st_size == 0
    rows.to_csv(path, mode="a", header=header, index=False)
