"""
test_risk_pnl.py — v14 (D12): Unit test untuk logika UANG (risk & pnl).

Ini file paling kritikal buat dites karena salah hitung SL/TP atau PnL = rugi nyata.
Jalankan dari root project:
    python3 -m unittest tests.test_risk_pnl -v
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.risk import calc_sl_tp, profit_pct, calc_breakeven_sl, calc_entry_from_free_margin
from bot.pnl import DailyPnL, summarize_income
from bot.config import Settings


class TestRisk(unittest.TestCase):
    def test_sl_tp_long(self):
        sl, tp = calc_sl_tp("LONG", 100.0, 0.008, 0.016)
        self.assertAlmostEqual(sl, 99.2, places=6)
        self.assertAlmostEqual(tp, 101.6, places=6)

    def test_sl_tp_short(self):
        sl, tp = calc_sl_tp("SHORT", 100.0, 0.008, 0.016)
        self.assertAlmostEqual(sl, 100.8, places=6)
        self.assertAlmostEqual(tp, 98.4, places=6)

    def test_sl_tp_invalid_side(self):
        with self.assertRaises(ValueError):
            calc_sl_tp("SIDEWAYS", 100.0, 0.008, 0.016)

    def test_profit_pct_long(self):
        self.assertAlmostEqual(profit_pct("LONG", 100.0, 101.0), 0.01, places=6)
        self.assertAlmostEqual(profit_pct("LONG", 100.0, 99.0), -0.01, places=6)

    def test_profit_pct_short(self):
        self.assertAlmostEqual(profit_pct("SHORT", 100.0, 99.0), 0.01, places=6)
        self.assertAlmostEqual(profit_pct("SHORT", 100.0, 101.0), -0.01, places=6)

    def test_profit_pct_zero_entry(self):
        self.assertEqual(profit_pct("LONG", 0.0, 100.0), 0.0)

    def test_breakeven_locks_profit_side(self):
        # LONG breakeven harus DI ATAS entry (kunci profit kecil)
        self.assertGreater(calc_breakeven_sl("LONG", 100.0, 0.003), 100.0)
        # SHORT breakeven harus DI BAWAH entry
        self.assertLess(calc_breakeven_sl("SHORT", 100.0, 0.003), 100.0)

    def test_entry_sizing_scales_with_mult(self):
        s = Settings()
        base = calc_entry_from_free_margin("BNBUSDT", "LONG", 1000.0, s, size_mult=1.0)
        big = calc_entry_from_free_margin("BNBUSDT", "LONG", 1000.0, s, size_mult=1.5)
        self.assertGreater(big.entry_margin, base.entry_margin)
        # notional = margin * leverage
        self.assertAlmostEqual(base.notional, base.entry_margin * s.leverage, places=6)

    def test_entry_sizing_floor(self):
        # size_mult sangat kecil tetap di-floor ke 0.1 (tidak boleh 0)
        s = Settings()
        tiny = calc_entry_from_free_margin("BNBUSDT", "LONG", 1000.0, s, size_mult=0.0)
        self.assertGreater(tiny.entry_margin, 0.0)


class TestPnL(unittest.TestCase):
    def test_summarize_income_splits_types(self):
        rows = [
            {"incomeType": "REALIZED_PNL", "income": "1.5"},
            {"incomeType": "REALIZED_PNL", "income": "-0.5"},
            {"incomeType": "COMMISSION", "income": "-0.04"},
            {"incomeType": "FUNDING_FEE", "income": "0.01"},
        ]
        d = summarize_income(rows)
        self.assertEqual(d.trades, 2)
        self.assertEqual(d.wins, 1)
        self.assertEqual(d.losses, 1)
        self.assertAlmostEqual(d.realized, 1.0, places=6)
        self.assertAlmostEqual(d.commission, -0.04, places=6)
        self.assertAlmostEqual(d.funding, 0.01, places=6)
        # net = realized + commission + funding + other
        self.assertAlmostEqual(d.net, 1.0 - 0.04 + 0.01, places=6)

    def test_win_rate(self):
        d = DailyPnL(trades=4, wins=3)
        self.assertAlmostEqual(d.win_rate, 75.0, places=6)

    def test_win_rate_zero_trades(self):
        self.assertEqual(DailyPnL().win_rate, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
