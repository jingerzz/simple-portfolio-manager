#!/usr/bin/env python3
"""Daily portfolio refresh job.

Fetches prices for all traded tickers, then recomputes positions and snapshots.
Designed for cron/launchd execution.
"""

import argparse
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portfolio import engine, pricing, storage  # noqa: E402


def traded_tickers(trades_df) -> List[str]:
    if trades_df.empty:
        return []
    return sorted(
        set(
            trades_df["ticker"]
            .dropna()
            .astype(str)
            .str.upper()
            .str.strip()
            .tolist()
        )
    )


def run_daily_refresh(force_refresh: bool = False) -> int:
    storage.ensure_data_files()
    trades_df = storage.load_trades()
    prices_df = storage.load_prices()

    tickers = traded_tickers(trades_df)
    records = []
    missing = []
    refresh_error = None
    refresh_attempted = False

    if tickers and (force_refresh or pricing.should_refresh_prices(prices_df, tickers)):
        refresh_attempted = True
        try:
            records, missing = pricing.fetch_latest_prices(tickers)
        except RuntimeError as exc:
            refresh_error = str(exc)
            records = []
            missing = tickers

        if records:
            storage.append_prices(records)

    prices_df = storage.load_prices()
    latest_prices_df = storage.latest_prices(prices_df)
    now_utc = datetime.now(timezone.utc)
    positions_df = engine.build_positions(trades_df, latest_prices_df, now_utc)
    storage.save_positions(positions_df)

    snapshots_df = storage.load_snapshots()
    today = date.today().isoformat()
    new_snapshot_rows = engine.build_daily_snapshots(
        positions_df=positions_df,
        existing_snapshots_df=snapshots_df,
        as_of_date=today,
    )
    storage.upsert_daily_snapshots(new_snapshot_rows)

    source_counts = Counter(row.get("source", "unknown") for row in records)
    source_summary = ", ".join(f"{name}:{count}" for name, count in sorted(source_counts.items()))
    if not source_summary:
        source_summary = "none"

    print(f"[daily-refresh] as_of_utc={now_utc.isoformat()}")
    print(f"[daily-refresh] trades={len(trades_df)} tracked_tickers={len(tickers)}")
    print(
        "[daily-refresh] refresh_attempted="
        f"{refresh_attempted} updated={len(records)} missing={len(missing)} sources={source_summary}"
    )
    print(
        "[daily-refresh] positions_rows="
        f"{len(positions_df)} snapshots_written={len(new_snapshot_rows)} snapshot_date={today}"
    )
    if missing:
        print(f"[daily-refresh] missing_tickers={','.join(missing)}")
    if refresh_error:
        print(f"[daily-refresh] error={refresh_error}")

    if refresh_attempted and refresh_error and not records:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily portfolio refresh job.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Fetch prices even if current prices are not stale.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_daily_refresh(force_refresh=args.force_refresh)


if __name__ == "__main__":
    raise SystemExit(main())
