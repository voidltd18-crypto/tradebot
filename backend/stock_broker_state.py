"""Strict broker reads for stock order decisions."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from requests.exceptions import Timeout


class BrokerStateUnverified(ValueError):
    pass


def broker_failure_category(exc):
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "permission denied"
    if status == 429:
        return "rate limited"
    if isinstance(exc, (Timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, (AttributeError, KeyError, TypeError, ValueError, InvalidOperation)):
        return "malformed response"
    return "broker request failed"


def _read(operation, fetch):
    try:
        return fetch()
    except BrokerStateUnverified:
        raise
    except Exception as exc:
        category = broker_failure_category(exc)
        raise BrokerStateUnverified(f"Broker state unverified: {operation} ({category})") from exc


def _number(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("non-finite broker quantity")
    return number


def open_stock_orders(broker, symbol):
    def fetch():
        orders = broker.get("/orders", data={"status": "open", "symbols": symbol, "limit": 1})
        if not isinstance(orders, list) or any(
            not isinstance(order, dict) or order.get("symbol") != symbol or not order.get("id")
            for order in orders
        ):
            raise ValueError("invalid open order response")
        return orders
    return _read("open orders", fetch)


def verify_entry_slot(broker):
    # A pending buy on another symbol can consume the single stock slot or its cash.
    def fetch():
        orders = broker.get("/orders", data={"status": "open", "side": "buy", "limit": 1})
        if not isinstance(orders, list):
            raise ValueError("invalid open orders")
        return not orders
    return _read("account open buy orders", fetch)


def stock_position(broker, symbol):
    def fetch():
        positions = broker.get_all_positions()
        if not isinstance(positions, list) or any(not position.symbol for position in positions):
            raise ValueError("invalid positions response")
        matching = [position for position in positions if position.symbol == symbol]
        if len(matching) > 1:
            raise ValueError("duplicate position")
        if not matching:
            return None
        position = matching[0]
        _number(position.qty)
        _number(position.avg_entry_price)
        return position
    return _read("positions", fetch)


def stock_account(broker):
    def fetch():
        account = broker.get_account()
        status = getattr(account.status, "value", account.status)
        if not status or not account.id or not all(
            isinstance(flag, bool) for flag in (account.trading_blocked, account.account_blocked, account.trade_suspended_by_user)
        ):
            raise ValueError("invalid account response")
        for value in (account.equity, account.cash, account.buying_power):
            _number(value)
        if status != "ACTIVE" or account.trading_blocked or account.account_blocked or account.trade_suspended_by_user:
            raise BrokerStateUnverified("Trade blocked: Alpaca account restricted")
        return account
    return _read("account", fetch)


def sellable_stock_quantity(broker, symbol):
    position = stock_position(broker, symbol)
    if position is None:
        return Decimal(0)
    def quantity():
        held = _number(position.qty)
        available = _number(position.qty_available)
        if not 0 <= available <= held:
            raise ValueError("inconsistent sellable quantity")
        return available
    return _read("sellable quantity", quantity)

def require_fresh_stock_quote(quote, now=None):
    def check():
        timestamp = quote.timestamp
        if timestamp is None or timestamp.utcoffset() is None:
            raise ValueError("missing quote timestamp")
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        if not 0 <= age <= 300:
            raise BrokerStateUnverified("Broker state unverified: stale stock quote")
        bid, ask = _number(quote.bid_price), _number(quote.ask_price)
        if not 0 < bid <= ask:
            raise ValueError("invalid quote prices")
    _read("stock quote", check)

def fresh_stock_quote(client, request, symbol):
    def fetch():
        quote = client.get_stock_latest_quote(request)[symbol]
        require_fresh_stock_quote(quote)
        return quote
    return _read("stock quote", fetch)
