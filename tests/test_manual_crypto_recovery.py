from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from backend.v19_manual_crypto_recovery import confirmed_recovery

NOW = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)

def bars(closes, lows, highs):
    return [SimpleNamespace(timestamp=NOW-timedelta(minutes=15-i*5),close=closes[i],low=lows[i],high=highs[i]) for i in range(3)]

def test_rising_bars_confirm():
    assert confirmed_recovery(bars([10,11,13],[9,10,11],[11,12,14]),NOW)

def test_falling_bars_block():
    assert not confirmed_recovery(bars([13,12,11],[11,10,9],[14,13,12]),NOW)

def test_no_breakout_blocks():
    assert not confirmed_recovery(bars([10,11,12],[9,10,11],[11,13,14]),NOW)

def test_incomplete_bars_block():
    assert not confirmed_recovery(bars([10,11,13],[9,10,11],[11,12,14]),NOW-timedelta(minutes=10))

def test_missing_bars_block():
    assert not confirmed_recovery([],NOW)
