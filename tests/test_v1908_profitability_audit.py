import unittest
from backend.v1908_profitability_audit import profitability_audit

def trade(pnl):
    return {"pnl_gbp": pnl, "entry_price": 10, "exit_price": 11, "qty": 1}

class ProfitabilityAuditTests(unittest.TestCase):
    def test_loss_larger_than_win(self):
        result = profitability_audit([trade(1),trade(1),trade(-3)], [])
        self.assertEqual(result["recordedPnlGbp"],-1)
        self.assertEqual(result["wins"],2)
        self.assertEqual(result["losses"],1)
        self.assertAlmostEqual(result["profitFactor"],2/3,places=4)
        self.assertFalse(result["validatedProfitability"])
        self.assertEqual(result["decision"],"DO_NOT_AUTO_PROMOTE")

    def test_empty_and_invalid(self):
        self.assertIsNone(profitability_audit([],[])["winRatePct"])
        result=profitability_audit([{"pnl_gbp":2},trade(-1)],[])
        self.assertEqual(result["invalidTrades"],1)
        self.assertEqual(result["validTrades"],1)

    def test_peak_leakage(self):
        row={"id":17,"symbol":"KSS","recordedPeakPct":6.77,"actualPnlPct":0.1}
        result=profitability_audit([trade(1)],[row])
        self.assertEqual(result["sampledPeakLeakage"]["tradesOver1pp"],1)
        self.assertAlmostEqual(result["sampledPeakLeakage"]["largest"][0]["peakToExitPp"],6.67)

if __name__ == "__main__":
    unittest.main()
