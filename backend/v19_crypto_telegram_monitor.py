"""Read-only Alpaca crypto position/event watcher. Never submits broker orders."""
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend.v19_telegram_crypto import send_telegram_crypto_alert
from backend.v19_crypto_exit_diagnostics import crypto_exit_diagnostic

INTERVAL = 900
_ENABLED = "TRADEBOT_TELEGRAM_CRYPTO_MONITOR_ENABLED"


def _positive(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _storage(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS v19_telegram_seen (event_key TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS v19_telegram_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    return conn


def _notify_once(conn, key, message, *, sender=send_telegram_crypto_alert):
    if conn.execute("SELECT 1 FROM v19_telegram_seen WHERE event_key=?", (key,)).fetchone():
        return False
    if sender(message, enabled=True).get("sent") is not True:
        return False
    conn.execute("INSERT OR IGNORE INTO v19_telegram_seen VALUES (?, ?)",
                 (key, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return True


def poll_crypto_alerts(client, state, db_path, *, sender=send_telegram_crypto_alert, now=None):
    """One read-only polling cycle. Broker failures never imply a sale."""
    now = now or datetime.now(timezone.utc)
    conn = _storage(db_path)
    try:
        started = conn.execute("SELECT value FROM v19_telegram_meta WHERE key='started'").fetchone()
        if started is None:
            conn.execute("INSERT INTO v19_telegram_meta VALUES ('started', ?)", (now.isoformat(),))
            conn.commit()
        positions = client.get_all_positions()  # raises on failure: do not acknowledge missing positions
        for pos in positions:
            if "crypto" not in str(getattr(pos, "asset_class", "")).lower():
                continue
            symbol = str(getattr(pos, "symbol", "")).upper()
            qty = _positive(getattr(pos, "qty", None))
            entry = _positive(getattr(pos, "avg_entry_price", None))
            current = _positive(getattr(pos, "current_price", None))
            if not symbol or qty is None or entry is None or current is None:
                continue
            # Position identity is deliberately based on broker entry+quantity.
            identity = f"{symbol}:{entry}:{qty}"
            if current > entry:
                pct = ((current / entry) - 1) * 100
                _notify_once(conn, "profit:" + identity,
                             f"TradeBot CRYPTO PROFIT: {symbol} is +{pct:.2f}% gross at ${current}. No sale executed.",
                             sender=sender)
            peak = (state.get(symbol) or {}).get("highest_since_entry")
            if peak is None:
                continue  # fail closed: an unverified trailing peak cannot generate an exit alert
            diagnostic = crypto_exit_diagnostic(symbol, qty, entry, current, peak,
                                                externally_purchased=True, manage_external=False)
            if diagnostic.get("condition") == "TRAIL_CONDITION":
                _notify_once(conn, "trail:" + identity + ":" + str(diagnostic.get("peak")),
                             f"TradeBot PROFIT EXIT SIGNAL: {symbol} price ${current} (entry ${entry}). Advisory only; no sale submitted.",
                             sender=sender)
        # Only broker-confirmed filled sell orders. Scan recent broker history, not holdings disappearing.
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100,
                                    after=now - timedelta(days=2)))
        started_at = datetime.fromisoformat(conn.execute(
            "SELECT value FROM v19_telegram_meta WHERE key='started'").fetchone()[0])
        for order in orders:
            if str(getattr(order, "side", "")).lower().split(".")[-1] != "sell":
                continue
            if str(getattr(order, "status", "")).lower().split(".")[-1] != "filled":
                continue
            filled_at = getattr(order, "filled_at", None)
            if filled_at is None or filled_at < started_at:
                continue
            symbol = str(getattr(order, "symbol", "")).upper()
            # Require broker asset class proof, not merely suffix naming.
            if "crypto" not in str(getattr(order, "asset_class", "")).lower():
                continue
            oid = str(getattr(order, "id", ""))
            if not oid:
                continue
            _notify_once(conn, "filled:" + oid,
                         f"TradeBot CONFIRMED CRYPTO SELL: {symbol}, qty {getattr(order, 'filled_qty', '?')}, "
                         f"filled price ${getattr(order, 'filled_avg_price', '?')}. Broker order {oid}.",
                         sender=sender)
    finally:
        conn.close()


def install_crypto_telegram_worker(app, client, state, db_path):
    """Explicit opt-in only. Runs in API process, independent of stock market hours."""
    @app.on_event("startup")
    def _start_crypto_telegram_worker():
        if os.getenv(_ENABLED, "").strip().lower() not in ("1", "true", "yes"):
            return

        def _work():
            while True:
                try:
                    poll_crypto_alerts(client, state, db_path)
                except Exception as exc:
                    # No sensitive broker response, secrets or account data in logs.
                    print("V19 TELEGRAM MONITOR | poll failed:", type(exc).__name__)
                time.sleep(INTERVAL)

        threading.Thread(target=_work, name="v19-crypto-telegram", daemon=True).start()
