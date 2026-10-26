"""Read-only classification of stock-account rejection reasons.

Never changes eligibility, broker state, cash, or decision ordering.
"""

def account_block_category(reason):
    r = str(reason or "").lower()
    if "mara daily entries" in r:
        return "mara_daily_limit"
    if "locked until tomorrow" in r:
        return "daily_lock"
    if "existing open order" in r:
        return "open_order"
    if "already holding" in r:
        return "already_holding"
    if any(term in r for term in ("low-profit", "low profit", "weak profit", "repeat-low-profit")):
        return "low_profit_guard"
    return "other_account_block"


def account_block_summary(blocks):
    """Summarize symbol/reason pairs without exposing raw broker error strings."""
    from collections import Counter
    counts = Counter(account_block_category(reason) for _, reason in blocks)
    parts = [f"{name}:{counts[name]}" for name in sorted(counts)]
    return {"total": len(blocks), "reasons": dict(counts), "summary": ",".join(parts) or "none"}


def locked_symbol_names(blocks):
    """Read-only list of tickers rejected by the existing daily lock."""
    return sorted({str(symbol).upper() for symbol, reason in blocks if account_block_category(reason) == 'daily_lock' and str(symbol).isascii() and str(symbol).replace('.', '').isalnum() and len(str(symbol)) <= 12})


def account_block_details(blocks):
    """Safe, read-only per-symbol view for diagnostics (no broker message leakage).

    Rows contain only ticker symbols and known reason categories. Do not use
    this display-only data to make trading or eligibility decisions.
    """
    rows = []
    for symbol, reason in blocks:
        ticker = str(symbol or "").strip().upper()
        if not (ticker.isascii() and 1 <= len(ticker) <= 12
                and ticker.replace(".", "").isalnum()):
            ticker = "UNKNOWN"
        rows.append({"symbol": ticker, "category": account_block_category(reason)})
    return rows
