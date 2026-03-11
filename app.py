from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from portfolio import engine, parser, pricing, storage

st.set_page_config(page_title="Kids Portfolio Chat", layout="wide")


def init_session_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {
                "role": "assistant",
                "content": (
                    "Hi! I can track trades in plain English.\n\n"
                    "Try: `I bought 2 AAPL at 185` or `show my portfolio`."
                ),
            }
        ]
    if "pending_trade" not in st.session_state:
        st.session_state.pending_trade = None
    if "kid_options" not in st.session_state:
        st.session_state.kid_options = ["Kid 1"]
    if "active_kid" not in st.session_state:
        st.session_state.active_kid = st.session_state.kid_options[0]
    if "auto_refresh_done" not in st.session_state:
        st.session_state.auto_refresh_done = False


def add_chat_message(role: str, content: str) -> None:
    st.session_state.chat_history.append({"role": role, "content": content})


def sync_kid_options(trades_df: pd.DataFrame) -> None:
    merged = set(st.session_state.kid_options)
    merged.update(storage.known_kids(trades_df))
    if not merged:
        merged.add("Kid 1")
    st.session_state.kid_options = sorted(merged)
    if st.session_state.active_kid not in st.session_state.kid_options:
        st.session_state.active_kid = st.session_state.kid_options[0]


def recompute_and_persist_derived_data(
    trades_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    latest_prices_df = storage.latest_prices(prices_df)
    positions_df = engine.build_positions(trades_df, latest_prices_df, datetime.now(timezone.utc))
    storage.save_positions(positions_df)

    snapshots_df = storage.load_snapshots()
    new_snapshot_rows = engine.build_daily_snapshots(
        positions_df=positions_df,
        existing_snapshots_df=snapshots_df,
        as_of_date=date.today().isoformat(),
    )
    storage.upsert_daily_snapshots(new_snapshot_rows)
    snapshots_df = storage.load_snapshots()
    return positions_df, snapshots_df


def refresh_prices(tickers: list[str]) -> str:
    if not tickers:
        return "No trades yet, so there are no tickers to refresh."

    try:
        records, missing = pricing.fetch_latest_prices(tickers)
    except RuntimeError as exc:
        return f"I could not fetch prices right now: {exc}"

    if records:
        storage.append_prices(records)

    parts = [f"Updated {len(records)} ticker(s)."]
    if missing:
        parts.append(f"Missing data for: {', '.join(missing)}.")
    return " ".join(parts)


def commit_pending_trade() -> str:
    pending = st.session_state.pending_trade
    if not pending:
        return "There is no pending trade to confirm."

    trades_df = storage.load_trades()
    if pending["action"] == "SELL":
        available = engine.get_current_shares(trades_df, pending["kid"], pending["ticker"])
        if pending["shares"] > available + 1e-9:
            return (
                f"I could not record that sell. {pending['kid']} only has "
                f"{available:.4f} shares of {pending['ticker']}."
            )

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kid": pending["kid"],
        "action": pending["action"],
        "ticker": pending["ticker"],
        "shares": pending["shares"],
        "price": pending["price"],
        "fees": pending["fees"],
        "note": pending["note"],
        "source_text": pending["source_text"],
    }
    storage.append_trade(row)
    st.session_state.pending_trade = None
    return (
        f"Recorded {row['action']} {row['shares']:.4f} {row['ticker']} @ "
        f"${row['price']:.2f} for {row['kid']}."
    )


def process_user_message(
    text: str,
    active_kid: str,
    trades_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    positions_df: pd.DataFrame,
) -> str:
    message = text.strip()
    lowered = message.lower()

    if parser.is_confirm_message(message):
        return commit_pending_trade()
    if parser.is_cancel_message(message):
        if st.session_state.pending_trade:
            st.session_state.pending_trade = None
            return "Cancelled. I did not save that trade."
        return "There is no pending trade to cancel."

    if st.session_state.pending_trade:
        pending = st.session_state.pending_trade
        return (
            "You already have a pending trade: "
            f"{pending['action']} {pending['shares']:.4f} {pending['ticker']} @ ${pending['price']:.2f}. "
            "Please confirm or cancel it first."
        )

    if "refresh prices" in lowered or "update prices" in lowered:
        tickers = sorted(
            set(trades_df["ticker"].dropna().astype(str).str.upper().str.strip().tolist())
        )
        return refresh_prices(tickers)

    history_limit = parser.extract_trade_history_limit(message)
    if history_limit is not None:
        history = engine.recent_trades_for_kid(trades_df, active_kid, history_limit)
        if history.empty:
            return f"No trades yet for {active_kid}."
        lines = [f"Last {len(history)} trade(s) for {active_kid}:"]
        for row in history.itertuples(index=False):
            timestamp = _format_timestamp(row.timestamp)
            lines.append(
                f"- {timestamp}: {row.action} {float(row.shares):.4f} {row.ticker} @ ${float(row.price):.2f}"
            )
        return "\n".join(lines)

    if parser.is_portfolio_query(message):
        summary = engine.portfolio_summary_for_kid(positions_df, active_kid)
        return (
            f"{active_kid} portfolio:\n"
            f"- Total Cost: {money(summary['total_cost'])}\n"
            f"- Current Value: {money(summary['total_value'])}\n"
            f"- Unrealized P&L: {money(summary['unrealized_pnl'])} ({summary['pnl_pct']:+.2f}%)"
        )

    pnl_ticker = parser.extract_pnl_ticker(message)
    if pnl_ticker:
        detail = engine.ticker_position_for_kid(positions_df, active_kid, pnl_ticker)
        if detail is None:
            return f"{active_kid} has no open position in {pnl_ticker}."
        market_price = "N/A" if pd.isna(detail["market_price"]) else money(detail["market_price"])
        return (
            f"{active_kid} {pnl_ticker}:\n"
            f"- Shares: {detail['shares']:.4f}\n"
            f"- Avg Cost: {money(detail['avg_cost'])}\n"
            f"- Market Price: {market_price}\n"
            f"- Unrealized P&L: {money(detail['unrealized_pnl'])} ({detail['pnl_pct']:+.2f}%)"
        )

    trade = parser.parse_trade_message(message)
    if trade:
        if trade.price is None:
            return "I parsed the trade, but I need a price. Example: `I bought 2 AAPL at 185`."
        if trade.price <= 0:
            return "Price must be greater than 0."

        known_tickers = set(trades_df["ticker"].dropna().astype(str).str.upper().str.strip())
        known_tickers.update(prices_df["ticker"].dropna().astype(str).str.upper().str.strip())
        if trade.ticker not in known_tickers:
            status = pricing.validate_ticker(trade.ticker)
            if status == pricing.VALIDATION_INVALID:
                return f"I could not validate ticker `{trade.ticker}`. Please check the symbol."
            if status == pricing.VALIDATION_UNKNOWN:
                return "I could not validate the ticker right now. Please try again in a minute."

        if trade.action == "SELL":
            available = engine.get_current_shares(trades_df, active_kid, trade.ticker)
            if trade.shares > available + 1e-9:
                return (
                    f"{active_kid} only has {available:.4f} shares of {trade.ticker}. "
                    f"I cannot sell {trade.shares:.4f}."
                )

        st.session_state.pending_trade = {
            "kid": active_kid,
            "action": trade.action,
            "ticker": trade.ticker,
            "shares": float(trade.shares),
            "price": float(trade.price),
            "fees": float(trade.fees),
            "note": "",
            "source_text": message,
        }
        pending = st.session_state.pending_trade
        return (
            "Please confirm this trade:\n"
            f"- Kid: {pending['kid']}\n"
            f"- Action: {pending['action']}\n"
            f"- Ticker: {pending['ticker']}\n"
            f"- Shares: {pending['shares']:.4f}\n"
            f"- Price: ${pending['price']:.2f}\n"
            "Click the confirm button below or type `confirm`."
        )

    return (
        "I can help with trades and portfolio questions.\n\n"
        "Examples:\n"
        "- `I bought 2 AAPL at 185`\n"
        "- `I sold 1 TSLA at 210`\n"
        "- `show my portfolio`\n"
        "- `show my last 5 trades`"
    )


def render_sidebar(
    positions_df: pd.DataFrame,
    snapshots_df: pd.DataFrame,
    trades_df: pd.DataFrame,
) -> None:
    with st.sidebar:
        st.header("Kid")
        new_kid_name = st.text_input("Add kid name", placeholder="e.g., Ava")
        if st.button("Add Kid"):
            candidate = new_kid_name.strip()
            if candidate:
                if candidate not in st.session_state.kid_options:
                    st.session_state.kid_options.append(candidate)
                    st.session_state.kid_options.sort()
                st.session_state.active_kid = candidate
                st.rerun()

        index = st.session_state.kid_options.index(st.session_state.active_kid)
        st.session_state.active_kid = st.selectbox(
            "Active kid",
            options=st.session_state.kid_options,
            index=index,
        )

        if st.button("Refresh Prices", type="primary"):
            tickers = sorted(
                set(trades_df["ticker"].dropna().astype(str).str.upper().str.strip().tolist())
            )
            update_message = refresh_prices(tickers)
            add_chat_message("assistant", update_message)
            st.rerun()

        st.divider()
        st.header("Portfolio Today")
        summary = engine.portfolio_summary_for_kid(positions_df, st.session_state.active_kid)
        day_change = engine.latest_day_change_for_kid(snapshots_df, st.session_state.active_kid)

        st.metric("Total Cost", money(summary["total_cost"]))
        st.metric("Current Value", money(summary["total_value"]))
        st.metric(
            "Unrealized P&L",
            money(summary["unrealized_pnl"]),
            f"{summary['pnl_pct']:+.2f}%",
        )
        st.metric("Today Change", money(day_change))

        kid_positions = positions_df.loc[
            positions_df["kid"] == st.session_state.active_kid,
            ["ticker", "shares", "market_value", "unrealized_pnl"],
        ]
        st.caption("Open Positions")
        if kid_positions.empty:
            st.caption("No open positions yet.")
        else:
            display = kid_positions.copy()
            display["shares"] = pd.to_numeric(display["shares"], errors="coerce").round(4)
            display["market_value"] = pd.to_numeric(display["market_value"], errors="coerce").round(2)
            display["unrealized_pnl"] = pd.to_numeric(display["unrealized_pnl"], errors="coerce").round(2)
            st.dataframe(display, hide_index=True, use_container_width=True)


def maybe_auto_refresh_prices(trades_df: pd.DataFrame, prices_df: pd.DataFrame) -> None:
    if st.session_state.auto_refresh_done:
        return

    tickers = sorted(
        set(trades_df["ticker"].dropna().astype(str).str.upper().str.strip().tolist())
    )
    if not tickers:
        st.session_state.auto_refresh_done = True
        return

    if not pricing.should_refresh_prices(prices_df, tickers):
        st.session_state.auto_refresh_done = True
        return

    with st.spinner("Refreshing latest prices..."):
        update_message = refresh_prices(tickers)
    add_chat_message("assistant", update_message)
    st.session_state.auto_refresh_done = True


def money(value: float) -> str:
    return f"${value:,.2f}"


def _format_timestamp(value: object) -> str:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return "unknown time"
    return timestamp.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p ET")


def render_pending_trade_controls() -> None:
    pending = st.session_state.pending_trade
    if not pending:
        return

    st.warning(
        "Pending trade awaiting confirmation: "
        f"{pending['action']} {pending['shares']:.4f} {pending['ticker']} @ ${pending['price']:.2f}"
    )
    left, right = st.columns(2)
    if left.button("Confirm Trade", type="primary"):
        result = commit_pending_trade()
        add_chat_message("assistant", result)
        st.rerun()
    if right.button("Cancel Trade"):
        st.session_state.pending_trade = None
        add_chat_message("assistant", "Cancelled. I did not save that trade.")
        st.rerun()


def main() -> None:
    storage.ensure_data_files()
    init_session_state()

    trades_df = storage.load_trades()
    prices_df = storage.load_prices()
    sync_kid_options(trades_df)
    maybe_auto_refresh_prices(trades_df, prices_df)

    trades_df = storage.load_trades()
    prices_df = storage.load_prices()
    positions_df, snapshots_df = recompute_and_persist_derived_data(trades_df, prices_df)
    render_sidebar(positions_df, snapshots_df, trades_df)

    st.title("Kids Investing Chat")
    st.caption("Educational use only. Not investment advice.")

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    render_pending_trade_controls()

    prompt = st.chat_input("Type a trade or ask about your portfolio")
    if prompt:
        add_chat_message("user", prompt)
        trades_df = storage.load_trades()
        prices_df = storage.load_prices()
        positions_df, _ = recompute_and_persist_derived_data(trades_df, prices_df)
        response = process_user_message(
            text=prompt,
            active_kid=st.session_state.active_kid,
            trades_df=trades_df,
            prices_df=prices_df,
            positions_df=positions_df,
        )
        add_chat_message("assistant", response)
        st.rerun()


if __name__ == "__main__":
    main()
