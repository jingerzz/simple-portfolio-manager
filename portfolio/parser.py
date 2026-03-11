import re
from dataclasses import dataclass
from typing import Optional

BUY_WORDS = {"buy", "bought", "purchase", "purchased"}
SELL_WORDS = {"sell", "sold"}

TRADE_PATTERNS = [
    re.compile(
        r"(?P<action>buy|bought|purchase|purchased|sell|sold)\s+"
        r"(?P<shares>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?:shares?\s+of\s+|shares?\s+)?"
        r"(?P<ticker>[A-Za-z][A-Za-z.\-]{0,9})"
        r"(?:\s+at\s+\$?(?P<price>\d[\d,]*(?:\.\d+)?))?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<action>buy|bought|purchase|purchased|sell|sold)\s+"
        r"(?P<ticker>[A-Za-z][A-Za-z.\-]{0,9})\s+"
        r"(?P<shares>\d[\d,]*(?:\.\d+)?)"
        r"(?:\s+at\s+\$?(?P<price>\d[\d,]*(?:\.\d+)?))?",
        flags=re.IGNORECASE,
    ),
]

PNL_TICKER_PATTERNS = [
    re.compile(
        r"(?:p&l|pnl).{0,32}?(?:on|for)\s+\$?(?P<ticker>[A-Za-z][A-Za-z.\-]{0,9})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\$?(?P<ticker>[A-Za-z][A-Za-z.\-]{0,9})\s+(?:p&l|pnl)",
        flags=re.IGNORECASE,
    ),
]

HISTORY_PATTERN = re.compile(
    r"(?:last|recent)\s+(?P<count>\d+)\s+trades?",
    flags=re.IGNORECASE,
)

CONFIRM_WORDS = {"confirm", "yes", "y", "ok", "okay", "submit"}
CANCEL_WORDS = {"cancel", "no", "n", "stop", "never mind", "nevermind"}


@dataclass
class TradeDraft:
    action: str
    ticker: str
    shares: float
    price: Optional[float]
    fees: float = 0.0


def parse_trade_message(text: str) -> Optional[TradeDraft]:
    message = text.strip()
    if not message:
        return None

    for pattern in TRADE_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue

        action_raw = match.group("action").lower()
        if action_raw in BUY_WORDS:
            action = "BUY"
        elif action_raw in SELL_WORDS:
            action = "SELL"
        else:
            return None

        shares = _parse_number(match.group("shares"))
        price_text = match.groupdict().get("price")
        price = _parse_number(price_text) if price_text else None
        ticker = match.group("ticker").upper().strip().lstrip("$")

        if shares is None or shares <= 0:
            return None
        return TradeDraft(action=action, ticker=ticker, shares=shares, price=price)
    return None


def is_confirm_message(text: str) -> bool:
    return text.strip().lower() in CONFIRM_WORDS


def is_cancel_message(text: str) -> bool:
    return text.strip().lower() in CANCEL_WORDS


def is_portfolio_query(text: str) -> bool:
    lowered = text.lower()
    keywords = (
        "show my portfolio",
        "my portfolio",
        "how am i doing",
        "how's my portfolio",
        "positions",
        "overall pnl",
        "overall p&l",
        "total value",
    )
    return any(keyword in lowered for keyword in keywords)


def extract_pnl_ticker(text: str) -> Optional[str]:
    for pattern in PNL_TICKER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("ticker").upper().strip().lstrip("$")
    return None


def extract_trade_history_limit(text: str) -> Optional[int]:
    lowered = text.lower()
    if not any(token in lowered for token in ("trade history", "recent trades", "last trades", "last trade")):
        return None

    match = HISTORY_PATTERN.search(text)
    if not match:
        return 5

    try:
        count = int(match.group("count"))
    except (TypeError, ValueError):
        return 5
    return max(1, min(count, 25))


def _parse_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None
