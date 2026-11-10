"""Optional SMS transport and alert formatting for crypto exits.

No credentials in source, no automatic sending, no trading side effects.
A future monitored worker must pass verified events into this module.
"""
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


ALERT_EVENTS = frozenset({"PROFIT_ELIGIBLE", "PROFIT_EXIT_TRIGGER", "SELL_CONFIRMED", "LOSS_MANUAL_ONLY"})


def format_crypto_alert(event, symbol, pnl_pct=None, price=None):
    event = str(event or "").upper().strip()
    symbol = str(symbol or "").upper().strip()
    if event not in ALERT_EVENTS or not symbol or not symbol.replace("/", "").isalnum():
        raise ValueError("unsupported crypto alert")
    info = {
        "PROFIT_ELIGIBLE": "is in profit. Monitoring for an exit reason.",
        "PROFIT_EXIT_TRIGGER": "has a profit-taking exit condition. No confirmed sale yet.",
        "SELL_CONFIRMED": "sale has been confirmed by the broker.",
        "LOSS_MANUAL_ONLY": "is below entry. No automatic sell; manual control only.",
    }[event]
    extras = []
    if pnl_pct is not None:
        extras.append(f"PnL {float(pnl_pct):+.2f}%")
    if price is not None:
        extras.append(f"price ${float(price):.4f}")
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return f"TradeBot {symbol}: {info}" + (f" ({', '.join(extras)})" if extras else "") + f" [{stamp}]"


def sms_configured():
    return all(os.environ.get(x) for x in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TRADEBOT_SMS_TO_NUMBER"))


def send_crypto_sms(message, *, enabled=False):
    """Transport only; caller opts in and deduplicates confirmed events.

    Returns a status dict, never affects a trade or submits broker orders.
    """
    if not enabled:
        return {"sent": False, "reason": "disabled"}
    if not sms_configured():
        return {"sent": False, "reason": "missing_sms_configuration"}
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    sender = os.environ["TWILIO_FROM_NUMBER"]
    recipient = os.environ["TRADEBOT_SMS_TO_NUMBER"]
    import base64
    encoded = urllib.parse.urlencode({"To": recipient, "From": sender, "Body": str(message)}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=encoded, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return {"sent": response.status in (200, 201), "status": response.status}
    except Exception:
        # Do not log credentials/phone numbers or propagate into trading.
        return {"sent": False, "reason": "sms_transport_failed"}
