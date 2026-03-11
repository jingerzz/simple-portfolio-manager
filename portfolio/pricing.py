from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"
VALIDATION_UNKNOWN = "unknown"

US_EASTERN = ZoneInfo("America/New_York")


def fetch_latest_prices(tickers: Iterable[str]) -> Tuple[List[dict], List[str]]:
    normalized = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not normalized:
        return [], []

    download_target = normalized[0] if len(normalized) == 1 else normalized
    try:
        raw = yf.download(
            tickers=download_target,
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception as exc:
        raise RuntimeError(f"Unable to fetch prices from yfinance: {exc}") from exc

    as_of = datetime.now(timezone.utc).isoformat()
    records: List[dict] = []
    missing: List[str] = []

    for ticker in normalized:
        series = _extract_close_series(raw, ticker)
        price = _last_valid_price(series)
        if price is None:
            missing.append(ticker)
            continue
        records.append(
            {
                "as_of": as_of,
                "ticker": ticker,
                "price": round(price, 4),
                "source": "yfinance",
            }
        )
    return records, missing


@lru_cache(maxsize=512)
def validate_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    if not normalized:
        return VALIDATION_INVALID

    try:
        records, _ = fetch_latest_prices([normalized])
    except RuntimeError:
        return VALIDATION_UNKNOWN

    return VALIDATION_VALID if records else VALIDATION_INVALID


def should_refresh_prices(
    prices_df: pd.DataFrame,
    tickers: Iterable[str],
    now_utc: Optional[datetime] = None,
) -> bool:
    normalized = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not normalized:
        return False
    if prices_df.empty:
        return True

    now = now_utc or datetime.now(timezone.utc)
    threshold = timedelta(minutes=15) if is_us_market_hours(now) else timedelta(hours=24)

    latest = prices_df.sort_values("as_of").drop_duplicates(subset=["ticker"], keep="last")
    for ticker in normalized:
        row = latest.loc[latest["ticker"] == ticker]
        if row.empty:
            return True

        last_as_of = pd.to_datetime(row.iloc[0]["as_of"], utc=True, errors="coerce")
        if pd.isna(last_as_of):
            return True

        if now - last_as_of.to_pydatetime() > threshold:
            return True
    return False


def is_us_market_hours(now_utc: Optional[datetime] = None) -> bool:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(US_EASTERN)
    if now.weekday() >= 5:
        return False

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def _extract_close_series(data: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        if "Close" not in data.columns.get_level_values(0):
            return None
        close_data = data["Close"]
        if isinstance(close_data, pd.Series):
            return close_data
        if ticker not in close_data.columns:
            return None
        return close_data[ticker]

    if "Close" not in data.columns:
        return None
    return data["Close"]


def _last_valid_price(series: Optional[pd.Series]) -> Optional[float]:
    if series is None:
        return None

    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None

    value = float(clean.iloc[-1])
    if value <= 0:
        return None
    return value
