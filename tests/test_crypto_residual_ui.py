"""Dashboard must never show a nonzero Alpaca crypto holding as Qty 0.0000."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAT = (ROOT / "frontend/src/lib/format.ts").read_text(encoding="utf-8")
OVERVIEW = (ROOT / "frontend/src/pages/OverviewPage.tsx").read_text(encoding="utf-8")
POSITIONS = (ROOT / "frontend/src/pages/PositionsPage.tsx").read_text(encoding="utf-8")


def test_crypto_quantity_has_eight_decimal_places():
    assert 'return qty.toFixed(crypto ? 8 : 4);' in FORMAT
    assert 'quantity > 0 && Number.isFinite(value) && value > 0 && value < 5' in FORMAT


def test_both_positions_views_show_actual_small_holding():
    for source in (OVERVIEW, POSITIONS):
        assert "positionQuantity(" in source
        assert "isSmallCryptoResidual(" in source
        assert "Small residual holding" in source
    assert "Number(p.qty || 0).toFixed(4)" not in OVERVIEW
    assert "Number(position.qty || 0).toFixed(4)" not in POSITIONS


def test_position_capacity_is_not_hidden_or_silently_changed():
    assert "{positions.length}" in OVERVIEW
    assert "{positions.length}/{maxPositions}" in OVERVIEW
