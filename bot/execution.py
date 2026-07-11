"""
execution.py — Helper eksekusi order tingkat lanjut (v14 bucket C/D)

SEMUA fitur di sini DEFAULT OFF lewat config flag. Tujuannya: kasih opsi
maker-first / iceberg / smart-SL / dynamic ATR TP-SL TANPA mengubah perilaku
live yang sekarang sampai user secara eksplisit mengaktifkan via .env.

Fungsi-fungsi di file ini PURE (tidak menyentuh network) supaya gampang
ditest. Pemanggilan order live tetap lewat ExchangeClient di main.py.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


# ── D1: Maker-first pricing ───────────────────────────────────────────────────

def maker_price(side: str, best_bid: float, best_ask: float, tick: float,
                offset_ticks: int = 0) -> float:
    """Harga LIMIT post-only yang kemungkinan jadi MAKER (dapat rebate, hindari
    taker fee). LONG -> pasang di/at bawah best_bid; SHORT -> di/atas best_ask.

    offset_ticks menggeser lebih agresif (mengejar fill) atau lebih pasif.
    """
    side = side.upper()
    t = max(tick, 0.0)
    if side == "LONG":
        # taruh di best_bid (atau lebih rendah) supaya tidak langsung cross.
        return max(0.0, best_bid - offset_ticks * t)
    else:
        return best_ask + offset_ticks * t


def crosses_spread(side: str, price: float, best_bid: float, best_ask: float) -> bool:
    """True jika harga limit akan langsung jadi TAKER (tidak diinginkan utk maker)."""
    side = side.upper()
    if side == "LONG":
        return price >= best_ask
    return price <= best_bid


# ── D2: Iceberg / order splitting ─────────────────────────────────────────────

def split_iceberg(total_qty: float, chunks: int, step: float = 0.0,
                  min_qty: float = 0.0) -> List[float]:
    """Pecah qty besar jadi beberapa potongan untuk mengurangi market impact.

    Menjaga total ~= total_qty (sisa pembulatan ditambahkan ke potongan terakhir).
    Potongan di-floor ke step bila step>0. Potongan < min_qty digabung.
    """
    chunks = max(1, int(chunks))
    if total_qty <= 0:
        return []
    if chunks == 1:
        return [total_qty]

    base = total_qty / chunks

    def _floor(v: float) -> float:
        if step and step > 0:
            import math
            return math.floor(v / step) * step
        return v

    parts = [_floor(base) for _ in range(chunks - 1)]
    parts = [p for p in parts if p > 0 and (min_qty <= 0 or p >= min_qty)]
    used = sum(parts)
    last = total_qty - used
    if last > 0:
        parts.append(round(last, 10))
    # Bersihkan nol
    return [p for p in parts if p > 0]


# ── C4: Dynamic ATR-based TP/SL ───────────────────────────────────────────────

@dataclass(frozen=True)
class TpSl:
    sl: float
    tp: float
    sl_dist: float
    tp_dist: float


def dynamic_atr_tpsl(side: str, entry: float, atr: float,
                     sl_mult: float = 1.5, tp_mult: float = 3.0,
                     min_sl_pct: float = 0.003, max_sl_pct: float = 0.03) -> TpSl:
    """Hitung SL/TP berbasis ATR (volatility-adaptive), bukan persen flat.

    sl_dist = clamp(atr*sl_mult, entry*min_sl_pct, entry*max_sl_pct)
    tp_dist = atr*tp_mult (atau RR sl_dist*tp_mult/sl_mult kalau atr<=0).
    """
    side = side.upper()
    if entry <= 0:
        return TpSl(0.0, 0.0, 0.0, 0.0)
    if atr and atr > 0:
        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult
    else:
        sl_dist = entry * min_sl_pct
        tp_dist = sl_dist * (tp_mult / sl_mult if sl_mult else 2.0)

    lo = entry * min_sl_pct
    hi = entry * max_sl_pct
    sl_dist = min(max(sl_dist, lo), hi)
    # Jaga RR sesuai rasio mult
    if sl_mult > 0:
        tp_dist = max(tp_dist, sl_dist * (tp_mult / sl_mult))

    if side == "LONG":
        sl = entry - sl_dist
        tp = entry + tp_dist
    else:
        sl = entry + sl_dist
        tp = entry - tp_dist
    return TpSl(sl=sl, tp=tp, sl_dist=sl_dist, tp_dist=tp_dist)


# ── D3: Smart trailing SL (ATR chandelier) ────────────────────────────────────

def smart_trailing_sl(side: str, entry: float, current_sl: float,
                      best_price: float, atr: float, atr_mult: float = 2.0,
                      activate_dist: float = 0.0) -> Optional[float]:
    """Chandelier-style trailing: ikuti harga terbaik (best_price) minus ATR*mult.
    Hanya menggeser SL ke arah yang MENGUNCI profit (tidak pernah mundur).

    Return SL baru bila perlu digeser, atau None bila tidak ada perubahan.
    best_price = harga ekstrem terbaik sejauh ini (high utk LONG, low utk SHORT).
    activate_dist = jarak minimal profit sebelum trailing aktif.
    """
    side = side.upper()
    if entry <= 0 or atr <= 0:
        return None
    gap = atr * atr_mult
    if side == "LONG":
        if best_price - entry < activate_dist:
            return None
        new_sl = best_price - gap
        if new_sl > current_sl and new_sl < best_price:
            return new_sl
    else:
        if entry - best_price < activate_dist:
            return None
        new_sl = best_price + gap
        if (current_sl <= 0 or new_sl < current_sl) and new_sl > best_price:
            return new_sl
    return None
