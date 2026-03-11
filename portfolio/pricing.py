import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import StringIO
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"
VALIDATION_UNKNOWN = "unknown"

SOURCE_YFINANCE = "yfinance"
SOURCE_STOOQ = "stooq"

US_EASTERN = ZoneInfo("America/New_York")


def fetch_latest_prices(tickers: Iterable[str]) -> Tuple[List[dict], List[str]]:
    normalized = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not normalized:
        return [], []

    records: List[dict] = []
    unresolved = normalized

    try:
        yf_records, unresolved = _fetch_from_yfinance(unresolved)
        records.extend(yf_records)
    except RuntimeError:
        unresolved = normalized

    if unresolved:
        stooq_records, unresolved = _fetch_from_stooq(unresolved)
        records.extend(stooq_records)

    return records, unresolved


def _fetch_from_yfinance(tickers: List[str]) -> Tuple[List[dict], List[str]]:
    if not tickers:
        return [], []

    download_target = tickers[0] if len(tickers) == 1 else tickers
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
    records = []
    missing = []
    for ticker in tickers:
        series = _extract_close_series(raw, ticker)
        price = _last_valid_price(series)
        if price is None:
            missing.append(ticker)
            continue
        records.append(_price_record(as_of, ticker, price, SOURCE_YFINANCE))
    return records, missing


def _fetch_from_stooq(tickers: List[str]) -> Tuple[List[dict], List[str]]:
    if not tickers:
        return [], []

    as_of = datetime.now(timezone.utc).isoformat()
    records = []
    missing = []
    for ticker in tickers:
        price = _fetch_stooq_price(ticker)
        if price is None:
            missing.append(ticker)
            continue
        records.append(_price_record(as_of, ticker, price, SOURCE_STOOQ))
    return records, missing


def _fetch_stooq_price(ticker: str) -> Optional[float]:
    for symbol in _stooq_symbol_candidates(ticker):
        url = f"https://stooq.com/q/l/?s={symbol}&i=d"
        try:
            response = requests.get(url, timeout=6)
            if response.status_code >= 400:
                continue
            reader = csv.DictReader(StringIO(response.text))
            row = next(reader, None)
            if not row:
                continue
            raw_close = (row.get("Close") or row.get("close") or "").strip()
            if not raw_close or raw_close.upper() == "N/D":
                continue
            price = float(raw_close)
            if price > 0:
                return price
        except (requests.RequestException, ValueError, TypeError):
            continue
    return None


def _stooq_symbol_candidates(ticker: str) -> List[str]:
    base = ticker.lower().strip()
    if not base:
        return []

    variants = [base, base.replace("-", "."), base.replace(".", "-")]
    symbols: List[str] = []
    for variant in variants:
        if variant not in symbols:
            symbols.append(variant)
        us_variant = f"{variant}.us"
        if us_variant not in symbols:
            symbols.append(us_variant)
    return symbols


def _price_record(as_of: str, ticker: str, price: float, source: str) -> dict:
    return {
        "as_of": as_of,
        "ticker": ticker,
        "price": round(price, 4),
        "source": source,
    }


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
