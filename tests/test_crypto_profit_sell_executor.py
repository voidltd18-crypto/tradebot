from datetime import datetime, timedelta, timezone
from decimal import Decimal
from backend.v19_crypto_profit_sell_executor import decide_limit_sell, _reserve


def _base():
    return dict(entry="100", qty="2", bid="102.5",
                quoted_at=datetime.now(timezone.utc), min_gain_pct="2",
                cost_buffer_pct="1")


def test_only_profitable_fresh_bid_may_trigger():
    d=decide_limit_sell(**_base())
    assert d["eligible"] is True
    assert Decimal(d["limit"]) >= Decimal("102")


def test_never_sells_flat_red_or_insufficient_gain():
    for value in ("95", "100", "101.99"):
        assert not decide_limit_sell(**{**_base(), "bid":value})["eligible"]


def test_stale_bad_and_future_quotes_fail_closed():
    for stamp in (None, datetime.now(timezone.utc)-timedelta(minutes=2),
                  datetime.now(timezone.utc)+timedelta(minutes=2),
                  datetime.now()):
        assert not decide_limit_sell(**{**_base(),"quoted_at":stamp})["eligible"]


def test_invalid_fee_or_missing_prices_fail_closed():
    for changed in (dict(cost_buffer_pct="0"), dict(cost_buffer_pct="3"),
                    dict(min_gain_pct="nan"), dict(bid="nan"),
                    dict(qty="0"), dict(entry="0")):
        assert not decide_limit_sell(**{**_base(),**changed})["eligible"]


def test_durable_duplicate_sell_attempts(tmp_path):
    path=str(tmp_path/"trades.sqlite")
    key="BTCUSD:100:2"
    first=_reserve(path,key)
    assert first.startswith("tbprofit-")
    assert _reserve(path,key) is None


def test_source_does_not_have_market_sell_or_buy():
    from pathlib import Path
    s=Path("backend/v19_crypto_profit_sell_executor.py").read_text()
    assert "LimitOrderRequest" in s
    assert "MarketOrderRequest" not in s
    assert "OrderSide.BUY" not in s
    assert "TRADEBOT_CRYPTO_PROFIT_SELL_LIVE_APPROVED" in s
