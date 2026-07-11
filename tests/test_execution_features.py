"""
test_execution_features.py — v14 bucket B/C/D unit tests.

Menguji fungsi PURE (tanpa network) untuk:
  - bot/execution.py : maker_price, crosses_spread, split_iceberg,
                       dynamic_atr_tpsl, smart_trailing_sl
  - bot/features.py  : triple_barrier_label (B5)

Jalankan dari root project:
    python3 -m unittest tests.test_execution_features -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.execution import (
    maker_price, crosses_spread, split_iceberg, dynamic_atr_tpsl,
    smart_trailing_sl, TpSl,
)
from bot.features import triple_barrier_label


class TestMakerPrice(unittest.TestCase):
    def test_long_at_bid(self):
        self.assertAlmostEqual(maker_price("LONG", 100.0, 100.2, 0.1), 100.0)

    def test_short_at_ask(self):
        self.assertAlmostEqual(maker_price("SHORT", 100.0, 100.2, 0.1), 100.2)

    def test_offset_long_more_passive(self):
        # offset menggeser LONG lebih rendah (lebih pasif)
        self.assertAlmostEqual(maker_price("LONG", 100.0, 100.2, 0.1, offset_ticks=2), 99.8)

    def test_offset_short_more_passive(self):
        self.assertAlmostEqual(maker_price("SHORT", 100.0, 100.2, 0.1, offset_ticks=2), 100.4)

    def test_never_negative(self):
        self.assertGreaterEqual(maker_price("LONG", 0.05, 0.06, 0.1, offset_ticks=10), 0.0)


class TestCrossesSpread(unittest.TestCase):
    def test_long_crosses_when_at_or_above_ask(self):
        self.assertTrue(crosses_spread("LONG", 100.2, 100.0, 100.2))
        self.assertFalse(crosses_spread("LONG", 100.0, 100.0, 100.2))

    def test_short_crosses_when_at_or_below_bid(self):
        self.assertTrue(crosses_spread("SHORT", 100.0, 100.0, 100.2))
        self.assertFalse(crosses_spread("SHORT", 100.2, 100.0, 100.2))


class TestSplitIceberg(unittest.TestCase):
    def test_sum_preserved(self):
        parts = split_iceberg(9.0, 3)
        self.assertAlmostEqual(sum(parts), 9.0, places=6)
        self.assertEqual(len(parts), 3)

    def test_single_chunk(self):
        self.assertEqual(split_iceberg(5.0, 1), [5.0])

    def test_zero_qty(self):
        self.assertEqual(split_iceberg(0.0, 3), [])

    def test_step_floor_preserves_total(self):
        parts = split_iceberg(10.0, 3, step=0.001)
        self.assertAlmostEqual(sum(parts), 10.0, places=6)
        self.assertTrue(all(p > 0 for p in parts))

    def test_min_qty_merges_small(self):
        # potongan kecil yang < min_qty tidak boleh muncul terpisah
        parts = split_iceberg(3.0, 3, min_qty=2.0)
        self.assertTrue(all(p >= 2.0 or abs(sum(parts) - 3.0) < 1e-9 for p in parts))
        self.assertAlmostEqual(sum(parts), 3.0, places=6)


class TestDynamicAtrTpSl(unittest.TestCase):
    def test_long_basic(self):
        r = dynamic_atr_tpsl("LONG", 100.0, 1.0, sl_mult=1.5, tp_mult=3.0)
        self.assertIsInstance(r, TpSl)
        self.assertAlmostEqual(r.sl_dist, 1.5, places=6)
        self.assertAlmostEqual(r.sl, 98.5, places=6)
        self.assertAlmostEqual(r.tp, 103.0, places=6)

    def test_short_basic(self):
        r = dynamic_atr_tpsl("SHORT", 100.0, 1.0, sl_mult=1.5, tp_mult=3.0)
        self.assertAlmostEqual(r.sl, 101.5, places=6)
        self.assertAlmostEqual(r.tp, 97.0, places=6)

    def test_clamp_max(self):
        # atr besar -> sl_dist dibatasi max_sl_pct (3% dari 100 = 3.0)
        r = dynamic_atr_tpsl("LONG", 100.0, 10.0, sl_mult=1.5, max_sl_pct=0.03)
        self.assertAlmostEqual(r.sl_dist, 3.0, places=6)

    def test_clamp_min(self):
        # atr kecil -> sl_dist minimal min_sl_pct (0.3% dari 100 = 0.3)
        r = dynamic_atr_tpsl("LONG", 100.0, 0.01, sl_mult=1.5, min_sl_pct=0.003)
        self.assertAlmostEqual(r.sl_dist, 0.3, places=6)

    def test_rr_respected(self):
        r = dynamic_atr_tpsl("LONG", 100.0, 1.0, sl_mult=1.5, tp_mult=3.0)
        self.assertGreaterEqual(r.tp_dist, r.sl_dist * 2.0 - 1e-9)

    def test_invalid_entry(self):
        r = dynamic_atr_tpsl("LONG", 0.0, 1.0)
        self.assertEqual((r.sl, r.tp), (0.0, 0.0))


class TestSmartTrailingSl(unittest.TestCase):
    def test_long_locks_profit(self):
        new_sl = smart_trailing_sl("LONG", 100.0, 98.0, 105.0, 1.0, atr_mult=2.0)
        self.assertAlmostEqual(new_sl, 103.0, places=6)

    def test_long_no_move_when_not_better(self):
        # new_sl (98.5) tidak lebih baik dari current_sl (99) -> None
        self.assertIsNone(smart_trailing_sl("LONG", 100.0, 99.0, 100.5, 1.0, atr_mult=2.0))

    def test_short_locks_profit(self):
        new_sl = smart_trailing_sl("SHORT", 100.0, 102.0, 95.0, 1.0, atr_mult=2.0)
        self.assertAlmostEqual(new_sl, 97.0, places=6)

    def test_activate_dist_gate(self):
        # profit (0.5) belum mencapai activate_dist (1.0) -> None
        self.assertIsNone(smart_trailing_sl("LONG", 100.0, 98.0, 100.5, 1.0, activate_dist=1.0))

    def test_zero_atr(self):
        self.assertIsNone(smart_trailing_sl("LONG", 100.0, 98.0, 105.0, 0.0))


class TestTripleBarrierLabel(unittest.TestCase):
    def _series(self):
        n = 12
        close = pd.Series([100.0] * n)
        high = pd.Series([100.5] * n)
        low = pd.Series([99.5] * n)
        atr = pd.Series([1.0] * n)
        # i=0 -> TP atas tersentuh di bar 1 (up=101.5)
        high[1] = 102.0
        # i=4 -> SL bawah tersentuh di bar 5 (dn=98.5)
        low[5] = 98.0
        return close, high, low, atr

    def test_tp_hit_is_plus_one(self):
        close, high, low, atr = self._series()
        lab = triple_barrier_label(close, high, low, atr, horizon=3)
        self.assertEqual(lab.iloc[0], 1.0)

    def test_sl_hit_is_minus_one(self):
        close, high, low, atr = self._series()
        lab = triple_barrier_label(close, high, low, atr, horizon=3)
        self.assertEqual(lab.iloc[4], -1.0)

    def test_timeout_is_zero(self):
        close, high, low, atr = self._series()
        lab = triple_barrier_label(close, high, low, atr, horizon=3)
        self.assertEqual(lab.iloc[8], 0.0)

    def test_tail_is_nan(self):
        close, high, low, atr = self._series()
        lab = triple_barrier_label(close, high, low, atr, horizon=3)
        # bar terakhir (i+horizon >= n) -> NaN, no lookahead
        self.assertTrue(np.isnan(lab.iloc[11]))

    def test_index_aligned(self):
        close, high, low, atr = self._series()
        lab = triple_barrier_label(close, high, low, atr, horizon=3)
        self.assertEqual(len(lab), len(close))
        self.assertTrue((lab.index == close.index).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
