from datetime import date, datetime, timezone

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


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
            div.stButton > button {
                width: 100%;
                min-height: 2.95rem;
                font-size: 1.02rem;
                font-weight: 700;
                border-radius: 10px;
            }
            div[data-testid="stChatInput"] textarea {
                font-size: 1.02rem;
            }
            .pending-trade-card {
                border: 1px solid #d1d5db;
                border-radius: 12px;
                padding: 0.8rem 0.9rem;
                margin: 0.25rem 0 0.75rem 0;
                background: #f8fafc;
            }
            .quick-hint {
                font-size: 0.95rem;
                color: #374151;
                margin-bottom: 0.35rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


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

    if not records and missing:
        return f"I could not fetch prices for: {', '.join(missing)}."

    sources = {}
    for row in records:
        source = str(row.get("source", "unknown"))
        sources[source] = sources.get(source, 0) + 1

    parts = [f"Updated {len(records)} ticker(s)."]
    if sources:
        source_text = ", ".join(f"{name}: {count}" for name, count in sorted(sources.items()))
        parts.append(f"Sources used: {source_text}.")
    if missing:
        parts.append(f"Missing data for: {', '.join(missing)}.")
    return " ".join(parts)


def commit_pending_trade() -> str:
    pending = st.session_state.pending_trade
    if not pending:
        return "There is no pending trade to confirm."

    trades_df = storage.load_trades()
    sell_realized = None
    if pending["action"] == "SELL":
        state = engine.get_position_state(trades_df, pending["kid"], pending["ticker"])
        available = state.shares
        if pending["shares"] > available + 1e-9:
            return (
                f"I could not record that sell. {pending['kid']} only has "
                f"{available:.4f} shares of {pending['ticker']}."
            )
        average_cost = state.total_cost / state.shares if state.shares > 1e-9 else 0.0
        cost_removed = average_cost * pending["shares"]
        proceeds = (pending["shares"] * pending["price"]) - pending["fees"]
        sell_realized = proceeds - cost_removed

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
    message = (
        f"Recorded {row['action']} {row['shares']:.4f} {row['ticker']} @ "
        f"${row['price']:.2f} for {row['kid']}."
    )
    if sell_realized is not None:
        message += f" Realized P&L on this sell: {money(sell_realized)}."
    return message


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
        summary = engine.portfolio_summary_for_kid(positions_df, active_kid, trades_df)
        return (
            f"{active_kid} portfolio:\n"
            f"- Total Cost: {money(summary['total_cost'])}\n"
            f"- Current Value: {money(summary['total_value'])}\n"
            f"- Unrealized P&L: {money(summary['unrealized_pnl'])} ({summary['pnl_pct']:+.2f}%)\n"
            f"- Realized P&L: {money(summary['realized_pnl'])}\n"
            f"- Total P&L: {money(summary['total_pnl'])}"
        )

    pnl_ticker = parser.extract_pnl_ticker(message)
    if pnl_ticker:
        detail = engine.ticker_performance_for_kid(trades_df, positions_df, active_kid, pnl_ticker)
        if detail is None:
            return f"{active_kid} has no trade history for {pnl_ticker}."

        if not detail["has_open_position"]:
            return (
                f"{active_kid} {pnl_ticker}:\n"
                "- No open position right now.\n"
                f"- Realized P&L: {money(detail['realized_pnl'])}\n"
                f"- Total P&L: {money(detail['total_pnl'])}"
            )

        market_price = "N/A" if pd.isna(detail["market_price"]) else money(detail["market_price"])
        return (
            f"{active_kid} {pnl_ticker}:\n"
            f"- Shares: {detail['shares']:.4f}\n"
            f"- Avg Cost: {money(detail['avg_cost'])}\n"
            f"- Market Price: {market_price}\n"
            f"- Unrealized P&L: {money(detail['unrealized_pnl'])} ({detail['pnl_pct']:+.2f}%)\n"
            f"- Realized P&L: {money(detail['realized_pnl'])}\n"
            f"- Total P&L: {money(detail['total_pnl'])}"
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
            "Pending trade ready for review:\n"
            f"- Kid: {pending['kid']}\n"
            f"- Action: {pending['action']}\n"
            f"- Ticker: {pending['ticker']}\n"
            f"- Shares: {pending['shares']:.4f}\n"
            f"- Price: ${pending['price']:.2f}\n"
            "Tap Confirm Trade below or type `confirm`."
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
        summary = engine.portfolio_summary_for_kid(
            positions_df,
            st.session_state.active_kid,
            trades_df,
        )
        day_change = engine.latest_day_change_for_kid(snapshots_df, st.session_state.active_kid)

        st.metric("Total Cost", money(summary["total_cost"]))
        st.metric("Current Value", money(summary["total_value"]))
        st.metric(
            "Unrealized P&L",
            money(summary["unrealized_pnl"]),
            f"{summary['pnl_pct']:+.2f}%",
        )
        st.metric("Realized P&L", money(summary["realized_pnl"]))
        st.metric("Total P&L", money(summary["total_pnl"]))
        st.metric("Today Change", money(day_change))

        kid_positions = positions_df.loc[
            positions_df["kid"] == st.session_state.active_kid,
            ["ticker", "shares", "market_value", "unrealized_pnl", "realized_pnl"],
        ]
        st.caption("Open Positions")
        if kid_positions.empty:
            st.caption("No open positions yet.")
        else:
            display = kid_positions.copy()
            display["shares"] = pd.to_numeric(display["shares"], errors="coerce").round(4)
            display["market_value"] = pd.to_numeric(display["market_value"], errors="coerce").round(2)
            display["unrealized_pnl"] = pd.to_numeric(display["unrealized_pnl"], errors="coerce").round(2)
            display["realized_pnl"] = pd.to_numeric(display["realized_pnl"], errors="coerce").round(2)
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

    st.markdown(
        (
            "<div class='pending-trade-card'>"
            "<strong>Pending Trade Confirmation</strong><br>"
            f"Kid: <strong>{pending['kid']}</strong><br>"
            f"Action: <strong>{pending['action']}</strong><br>"
            f"Ticker: <strong>{pending['ticker']}</strong><br>"
            f"Shares: <strong>{pending['shares']:.4f}</strong><br>"
            f"Price: <strong>${pending['price']:.2f}</strong>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    if left.button("Confirm Trade", type="primary", use_container_width=True, key="confirm_trade_button"):
        result = commit_pending_trade()
        add_chat_message("assistant", result)
        st.rerun()
    if right.button("Cancel Trade", use_container_width=True, key="cancel_trade_button"):
        st.session_state.pending_trade = None
        add_chat_message("assistant", "Cancelled. I did not save that trade.")
        st.rerun()


def render_quick_actions() -> str:
    st.markdown("<div class='quick-hint'>Quick prompts:</div>", unsafe_allow_html=True)
    first, second, third = st.columns(3)

    if first.button("Show Portfolio", key="quick_show_portfolio", use_container_width=True):
        return "show my portfolio"
    if second.button("Last 5 Trades", key="quick_last_trades", use_container_width=True):
        return "show my last 5 trades"
    if third.button("Refresh Prices", key="quick_refresh_prices", use_container_width=True):
        return "refresh prices"
    return ""


def handle_prompt_submission(prompt: str) -> None:
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


def main() -> None:
    storage.ensure_data_files()
    init_session_state()
    inject_global_styles()

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
    quick_prompt = render_quick_actions()
    if quick_prompt:
        handle_prompt_submission(quick_prompt)
        st.rerun()

    prompt = st.chat_input("Type a trade or ask about your portfolio")
    if prompt:
        handle_prompt_submission(prompt)
        st.rerun()


if __name__ == "__main__":
    main()
