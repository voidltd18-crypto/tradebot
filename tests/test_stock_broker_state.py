from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.stock_broker_state import (
    BrokerStateUnverified, open_stock_orders, require_fresh_stock_quote,
    sellable_stock_quantity, stock_account, stock_position,
)


def test_order_timeout_and_unauthorized_position_are_not_empty():
    broker = Mock()
    broker.get.side_effect = TimeoutError()
    with pytest.raises(BrokerStateUnverified, match="open orders.*timeout"):
        open_stock_orders(broker, "AAPL")

    class Forbidden(Exception):
        status_code = 403

    broker.get_all_positions.side_effect = Forbidden()
    with pytest.raises(BrokerStateUnverified, match="positions.*permission"):
        stock_position(broker, "AAPL")


def test_only_a_successful_empty_response_proves_no_open_orders():
    broker = Mock()
    broker.get.return_value = []
    assert open_stock_orders(broker, "AAPL") == []
    broker.get.return_value = [{"id": "order", "symbol": "AAPL"}]
    assert open_stock_orders(broker, "AAPL")
    broker.get.return_value = {}
    with pytest.raises(BrokerStateUnverified, match="malformed"):
        open_stock_orders(broker, "AAPL")


def test_sellable_shares_and_account_restrictions():
    broker = Mock()
    broker.get_all_positions.return_value = [
        SimpleNamespace(symbol="AAPL", qty="4", avg_entry_price="120", qty_available="2")
    ]
    assert sellable_stock_quantity(broker, "AAPL") == 2
    broker.get_all_positions.return_value[0].qty_available = None
    with pytest.raises(BrokerStateUnverified, match="sellable quantity"):
        sellable_stock_quantity(broker, "AAPL")

    broker.get_account.return_value = SimpleNamespace(
        id="account", status="ACTIVE", account_blocked=False, trading_blocked=False,
        equity="100", cash="80", buying_power="80",
    )
    assert stock_account(broker).cash == "80"
    broker.get_account.return_value.trading_blocked = True
    with pytest.raises(BrokerStateUnverified, match="account restricted"):
        stock_account(broker)


def test_stock_quote_requires_valid_prices_and_fresh_timestamp():
    now = datetime.now(timezone.utc)
    quote = SimpleNamespace(timestamp=now, bid_price=100, ask_price=101)
    require_fresh_stock_quote(quote, now)
    quote.timestamp = now - timedelta(minutes=6)
    with pytest.raises(BrokerStateUnverified, match="stale stock quote"):
        require_fresh_stock_quote(quote, now)
    quote.timestamp = now
    quote.ask_price = 99
    with pytest.raises(BrokerStateUnverified, match="malformed"):
        require_fresh_stock_quote(quote, now)


def test_trailing_peak_survives_restart_but_resets_for_new_buy(tmp_path):
    import ast
    import sqlite3
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
    fn = next(node for node in ast.parse(source.read_text()).body
              if isinstance(node, ast.FunctionDef) and node.name == "_persistent_position_peak")
    scope = {"SQLITE_ENABLED": True, "db_connect": lambda: sqlite3.connect(tmp_path / "peak.db")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"), scope)
    peak = scope[fn.name]
    assert peak("AAPL", "first-buy", 120) == 120
    assert peak("AAPL", "first-buy", 100) == 120
    assert peak("AAPL", "second-buy", 100) == 100


def test_fill_pagination_uses_last_activity_id_and_fails_on_stalled_page():
    from backend.stock_ownership import _fill_activities

    broker = Mock()
    full_page = [{"id": str(n)} for n in range(100)]
    broker.get.side_effect = [full_page, [{"id": "100"}]]
    assert len(_fill_activities(broker, "start")) == 101
    assert broker.get.call_args.kwargs["data"]["page_token"] == "99"

    broker.get.side_effect = [full_page, full_page]
    with pytest.raises(ValueError, match="pagination stalled"):
        _fill_activities(broker, "start")
