"""Paper-only Alpaca SDK adapter for the isolated stock sell coordinator.

Never imported or started by live TradeBot. The factory ALWAYS creates
TradingClient(paper=True) from dedicated PAPER credentials. The optional
injected client is for mock tests only, not for production wiring.
"""
from decimal import Decimal
from backend.stock_exit_state_store import _identity
from backend.stock_sell_recovery_postgres import _qty


def _field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _enum_string(value):
    return str(getattr(value, "value", value) or "").strip().lower()


def _order_record(order):
    oid = str(_field(order, "id") or "")
    cid = str(_field(order, "client_order_id") or "")
    side = _enum_string(_field(order, "side"))
    status = _enum_string(_field(order, "status"))
    if not oid or side not in ("buy", "sell") or not status:
        raise ValueError("unverified Alpaca order")
    return {
        "id": oid, "client_order_id": cid,
        "symbol": str(_field(order, "symbol") or "").upper(),
        "side": side, "status": status,
        "filled_qty": str(_field(order, "filled_qty", "0") or "0"),
    }


class AlpacaPaperStockBroker:
    def __init__(self, client, *, paper_verified=False):
        # Caller must ONLY use make_paper_broker() for non-mock usage.
        if paper_verified is not True:
            raise ValueError("paper client not verified")
        self.client = client

    def fresh_position_qty(self, symbol):
        symbol, _ = _identity(symbol, "_")
        try:
            position = self.client.get_open_position(symbol)
        except Exception as exc:
            # Only a verified 404 signifies no position. All other errors
            # must fail closed, particularly network and auth errors.
            if getattr(exc, "status_code", None) == 404:
                return Decimal("0")
            raise
        if str(_field(position, "symbol") or "").upper() != symbol:
            raise ValueError("Alpaca position symbol mismatch")
        qty = _qty(_field(position, "qty"), allow_zero=True)
        side = _enum_string(_field(position, "side"))
        if side not in ("long", ""):
            raise ValueError("short stock positions not supported")
        return qty

    def list_open_orders(self, symbol):
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        symbol, _ = _identity(symbol, "_")
        orders = self.client.get_orders(
            filter=GetOrdersRequest(
                status=QueryOrderStatus.OPEN, symbols=[symbol], limit=500))
        if not isinstance(orders, list):
            raise ValueError("unverified Alpaca open orders response")
        if len(orders) >= 500:
            raise ValueError("order list may be truncated; refuse trading")
        records = [_order_record(x) for x in orders]
        if any(x["symbol"] != symbol for x in records):
            raise ValueError("order symbol mismatch")
        return records

    def get_order_by_client_id(self, client_id):
        if not isinstance(client_id, str) or not client_id.startswith("tb-stock-sell-"):
            raise ValueError("unknown client ID namespace")
        try:
            order = self.client.get_order_by_client_id(client_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return None
            raise
        record = _order_record(order)
        if record["client_order_id"] != client_id or record["side"] != "sell":
            raise ValueError("broker client order identity mismatch")
        return record

    def submit_sell(self, symbol, qty, *, client_order_id):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        symbol, _ = _identity(symbol, "_")
        if not isinstance(client_order_id, str) or not client_order_id.startswith("tb-stock-sell-"):
            raise ValueError("unverified client order ID")
        requested = _qty(qty)
        # This call is the ONLY write in this adapter, and always targets
        # an SDK client created with paper=True by the factory below.
        order = MarketOrderRequest(
            symbol=symbol, qty=float(requested),
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id)
        result = _order_record(self.client.submit_order(order))
        if (result["client_order_id"] != client_order_id
                or result["symbol"] != symbol or result["side"] != "sell"):
            raise ValueError("broker returned unexpected sell order identity")
        return result


def make_paper_broker(paper_api_key, paper_secret):
    if not isinstance(paper_api_key, str) or not paper_api_key.strip():
        raise ValueError("dedicated paper key required")
    if not isinstance(paper_secret, str) or not paper_secret.strip():
        raise ValueError("dedicated paper secret required")
    from alpaca.trading.client import TradingClient
    return AlpacaPaperStockBroker(
        TradingClient(paper_api_key, paper_secret, paper=True),
        paper_verified=True)
