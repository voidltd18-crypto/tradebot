from decimal import Decimal
import unittest

from backend.strategies.exit_safeguards_review import (
    Fill, realised_pnl_usd, loss_cooldown_active, quote_requires_review
)


class ExitSafeguardsTests(unittest.TestCase):
    def test_actual_fill_loss_overrides_positive_quote(self):
        entry = Fill("buy", Decimal("3.119846"), Decimal("337.47"))
        exit = Fill("sell", Decimal("3.119846"), Decimal("337.35"))
        self.assertEqual(realised_pnl_usd(entry, exit), Decimal("-0.37438152"))

    def test_profitable_actual_fill(self):
        entry = Fill("buy", Decimal("1"), Decimal("100"))
        exit = Fill("sell", Decimal("1"), Decimal("101"))
        self.assertEqual(realised_pnl_usd(entry, exit), Decimal("1"))

    def test_partial_or_mismatched_fill_rejected(self):
        with self.assertRaises(ValueError):
            realised_pnl_usd(Fill("buy", Decimal("2"), Decimal("100")),
                             Fill("sell", Decimal("1"), Decimal("101")))

    def test_cooldown_only_blocks_entries_during_window(self):
        self.assertTrue(loss_cooldown_active(1000, 999))
        self.assertTrue(loss_cooldown_active(1898, 999))
        self.assertFalse(loss_cooldown_active(1899, 999))
        self.assertFalse(loss_cooldown_active(1000, None))

    def test_suspicious_entry_quote(self):
        self.assertTrue(quote_requires_review(Decimal("117.10"), Decimal("120.03")))
        self.assertFalse(quote_requires_review(Decimal("119.90"), Decimal("120.03")))


if __name__ == "__main__":
    unittest.main()
