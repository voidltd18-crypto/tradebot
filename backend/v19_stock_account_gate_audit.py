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


def account_block_detail(blocks, *, max_symbols=24):
    """Safe diagnostics: bounded tickers and category, never raw broker messages."""
    import re
    output = []
    seen = set()
    for symbol, reason in blocks:
        sym = str(symbol or "").upper().strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", sym):
            continue
        category = account_block_category(reason)
        key = (sym, category)
        if key not in seen:
            seen.add(key)
            output.append(f"{sym}:{category}")
        if len(output) >= max_symbols:
            break
    return ",".join(output) or "none"
