from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import pandas as pd

from .config import POSITION_COLUMNS, SNAPSHOT_COLUMNS

EPSILON = 1e-9


@dataclass
class PositionAccumulator:
    shares: float = 0.0
    total_cost: float = 0.0


def compute_position_states(trades_df: pd.DataFrame) -> Dict[Tuple[str, str], PositionAccumulator]:
    states: Dict[Tuple[str, str], PositionAccumulator] = {}
    if trades_df.empty:
        return states

    ordered = trades_df.sort_values("timestamp")
    for row in ordered.itertuples(index=False):
        kid = str(row.kid).strip()
        ticker = str(row.ticker).strip().upper()
        action = str(row.action).strip().upper()
        shares = max(float(row.shares), 0.0)
        price = max(float(row.price), 0.0)
        fees = max(float(getattr(row, "fees", 0.0)), 0.0)

        if not kid or not ticker:
            continue

        key = (kid, ticker)
        state = states.setdefault(key, PositionAccumulator())

        if action == "BUY":
            state.shares += shares
            state.total_cost += (shares * price) + fees
            continue

        if action == "SELL":
            if state.shares <= EPSILON:
                continue
            shares_to_sell = min(shares, state.shares)
            average_cost = state.total_cost / state.shares if state.shares > EPSILON else 0.0
            state.shares -= shares_to_sell
            state.total_cost -= average_cost * shares_to_sell
            if state.shares <= EPSILON:
                state.shares = 0.0
                state.total_cost = 0.0

    return states


def get_current_shares(trades_df: pd.DataFrame, kid: str, ticker: str) -> float:
    key = (kid.strip(), ticker.strip().upper())
    state = compute_position_states(trades_df).get(key)
    return state.shares if state else 0.0


def build_positions(
    trades_df: pd.DataFrame,
    latest_prices_df: pd.DataFrame,
    as_of: datetime,
) -> pd.DataFrame:
    states = compute_position_states(trades_df)
    price_map = _latest_price_map(latest_prices_df)
    as_of_str = as_of.astimezone(timezone.utc).isoformat()

    records = []
    for (kid, ticker), state in sorted(states.items()):
        if state.shares <= EPSILON:
            continue

        avg_cost = state.total_cost / state.shares if state.shares > EPSILON else 0.0
        market_price = price_map.get(ticker, float("nan"))
        market_value = state.shares * market_price if pd.notna(market_price) else float("nan")
        unrealized = market_value - state.total_cost if pd.notna(market_value) else float("nan")
        pnl_pct = (unrealized / state.total_cost * 100.0) if state.total_cost > EPSILON and pd.notna(unrealized) else float("nan")

        records.append(
            {
                "as_of": as_of_str,
                "kid": kid,
                "ticker": ticker,
                "shares": state.shares,
                "avg_cost": avg_cost,
                "market_price": market_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "pnl_pct": pnl_pct,
            }
        )

    return pd.DataFrame(records, columns=POSITION_COLUMNS)


def build_daily_snapshots(
    positions_df: pd.DataFrame,
    existing_snapshots_df: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    if positions_df.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    rows = []
    for kid, group in positions_df.groupby("kid"):
        shares = pd.to_numeric(group["shares"], errors="coerce").fillna(0.0)
        avg_cost = pd.to_numeric(group["avg_cost"], errors="coerce").fillna(0.0)
        market_value = pd.to_numeric(group["market_value"], errors="coerce").fillna(0.0)

        total_cost = float((shares * avg_cost).sum())
        total_value = float(market_value.sum())
        unrealized_pnl = total_value - total_cost

        previous_value = _previous_total_value(existing_snapshots_df, kid, as_of_date)
        day_change = total_value - previous_value if previous_value is not None else 0.0

        rows.append(
            {
                "date": as_of_date,
                "kid": kid,
                "total_cost": total_cost,
                "total_value": total_value,
                "unrealized_pnl": unrealized_pnl,
                "day_change": day_change,
            }
        )

    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)


def portfolio_summary_for_kid(positions_df: pd.DataFrame, kid: str) -> dict:
    if positions_df.empty:
        return _empty_summary()

    filtered = positions_df.loc[positions_df["kid"] == kid]
    if filtered.empty:
        return _empty_summary()

    shares = pd.to_numeric(filtered["shares"], errors="coerce").fillna(0.0)
    avg_cost = pd.to_numeric(filtered["avg_cost"], errors="coerce").fillna(0.0)
    market_value = pd.to_numeric(filtered["market_value"], errors="coerce").fillna(0.0)

    total_cost = float((shares * avg_cost).sum())
    total_value = float(market_value.sum())
    unrealized = total_value - total_cost
    pnl_pct = (unrealized / total_cost * 100.0) if total_cost > EPSILON else 0.0

    return {
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_pnl": unrealized,
        "pnl_pct": pnl_pct,
    }


def ticker_position_for_kid(positions_df: pd.DataFrame, kid: str, ticker: str) -> Optional[dict]:
    if positions_df.empty:
        return None

    filtered = positions_df.loc[
        (positions_df["kid"] == kid) & (positions_df["ticker"] == ticker.upper())
    ]
    if filtered.empty:
        return None

    row = filtered.iloc[0]
    return {
        "ticker": ticker.upper(),
        "shares": float(row["shares"]),
        "avg_cost": float(row["avg_cost"]),
        "market_price": float(row["market_price"]) if pd.notna(row["market_price"]) else float("nan"),
        "market_value": float(row["market_value"]) if pd.notna(row["market_value"]) else float("nan"),
        "unrealized_pnl": float(row["unrealized_pnl"]) if pd.notna(row["unrealized_pnl"]) else float("nan"),
        "pnl_pct": float(row["pnl_pct"]) if pd.notna(row["pnl_pct"]) else float("nan"),
    }


def latest_day_change_for_kid(snapshots_df: pd.DataFrame, kid: str) -> float:
    if snapshots_df.empty:
        return 0.0

    history = snapshots_df.loc[snapshots_df["kid"] == kid].sort_values("date")
    if history.empty:
        return 0.0

    value = pd.to_numeric(history.iloc[-1]["day_change"], errors="coerce")
    if pd.isna(value):
        return 0.0
    return float(value)


def recent_trades_for_kid(trades_df: pd.DataFrame, kid: str, limit: int) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame(columns=trades_df.columns)

    filtered = trades_df.loc[trades_df["kid"] == kid]
    if filtered.empty:
        return pd.DataFrame(columns=trades_df.columns)

    ordered = filtered.sort_values("timestamp", ascending=False)
    return ordered.head(limit).reset_index(drop=True)


def _latest_price_map(latest_prices_df: pd.DataFrame) -> Dict[str, float]:
    if latest_prices_df.empty:
        return {}

    frame = latest_prices_df.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame = frame.dropna(subset=["ticker", "price"])
    return frame.set_index("ticker")["price"].to_dict()


def _previous_total_value(snapshots_df: pd.DataFrame, kid: str, as_of_date: str) -> Optional[float]:
    if snapshots_df.empty:
        return None

    history = snapshots_df.loc[
        (snapshots_df["kid"] == kid) & (snapshots_df["date"] < as_of_date)
    ].sort_values("date")
    if history.empty:
        return None

    value = pd.to_numeric(history.iloc[-1]["total_value"], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _empty_summary() -> dict:
    return {
        "total_cost": 0.0,
        "total_value": 0.0,
        "unrealized_pnl": 0.0,
        "pnl_pct": 0.0,
    }
