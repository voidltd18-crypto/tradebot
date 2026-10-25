"""Telegram delivery for TradeBot crypto alerts; no broker or trading side effects."""
import json
import os
from urllib import request


def telegram_configured():
    return bool(os.getenv("TRADEBOT_TELEGRAM_BOT_TOKEN") and os.getenv("TRADEBOT_TELEGRAM_CHAT_ID"))


def send_telegram_crypto_alert(message, *, enabled=False, opener=None):
    """Fail closed. The monitoring caller owns event verification and deduplication."""
    if not enabled:
        return {"sent": False, "reason": "disabled"}
    token = os.getenv("TRADEBOT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TRADEBOT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"sent": False, "reason": "missing_configuration"}
    if not isinstance(message, str) or not message.strip():
        return {"sent": False, "reason": "empty_message"}
    payload = json.dumps({"chat_id": chat_id, "text": message[:4096],
                          "disable_web_page_preview": True}).encode("utf-8")
    req = request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        open_url = opener or request.urlopen
        with open_url(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or data.get("ok") is not True:
                return {"sent": False, "reason": "telegram_rejected"}
        return {"sent": True}
    except Exception:
        # Do not leak token, chat ID or payload in logs.
        return {"sent": False, "reason": "telegram_transport_failed"}
