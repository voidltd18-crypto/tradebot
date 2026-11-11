"""Static guard checks; importing live backend would start broker workers."""
import ast
from pathlib import Path

SRC = Path("backend/legacy/monolith.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)

def test_watch_mode_on_with_buy_pause_by_default():
    assert 'TRADEBOT_TWO_STOCK_MODE", "true"' in SRC
    assert '("TSLA", "SPCX")' in SRC
    assert 'TRADEBOT_STOCK_BUYS_PAUSED", "true"' in SRC

def test_stock_order_and_scan_restricted_when_enabled():
    assert "def two_stock_buy_allowed(symbol: str)" in SRC
    assert "if not two_stock_buy_allowed(sym):" in SRC
    assert "if not two_stock_buy_allowed(symbol):" in SRC
    assert "if TRADEBOT_TWO_STOCK_MODE" in SRC
    # The current stock policy uses a tech-giants allowlist, not the retired September selector.\n    # Verify both eligibility and the actual order-submission path enforce it.\n    assert "def two_stock_buy_allowed(symbol: str)" in SRC\n    assert "if sym not in TECH_GIANT_STOCK_ALLOWED:" in SRC\n    assert "if str(symbol or \"\").upper().strip() not in TECH_GIANT_STOCK_ALLOWED:" in SRC\n    assert "BUY BLOCKED | stock outside tech-giants-only allowlist" in SRC

def test_sell_management_and_daily_loss_controls_remain():
    assert "manage_money_mode_positions()" in SRC
    assert "MARA_DAILY_ENTRY_LIMIT = 1" in SRC
    assert "Max daily loss hit" in SRC
