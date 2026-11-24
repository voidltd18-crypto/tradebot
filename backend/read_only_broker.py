"""Broker transport for the original TradeBot dashboard in display-only mode."""

from alpaca.trading.client import TradingClient


class ReadOnlyTradingClient(TradingClient):
    def _request(self, method, *args, **kwargs):
        if method.upper() != "GET":
            raise RuntimeError("TradeBot is read-only. Broker orders are disabled.")
        return super()._request(method, *args, **kwargs)
