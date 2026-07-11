from __future__ import annotations
import os
from dataclasses import dataclass
from typing import List, Optional

from bot.indicators import adx, ema_last, atr


def _envf(key, default):
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return float(default)


def _envi(key, default):
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return int(default)


# -- ambang (bisa dioverride via .env) --
ADX_TREND_MIN = _envf("ADX_TREND_MIN", 20.0)
ADX_SIDEWAYS_MAX = _envf("ADX_SIDEWAYS_MAX", 18.0)
EMA_FAST = _envi("MODE_EMA_FAST", 20)
EMA_SLOW = _envi("MODE_EMA_SLOW", 50)
EMA_SEP_MIN = _envf("MODE_EMA_SEP_MIN", 0.0015)
RANGE_WINDOW = _envi("MODE_RANGE_WINDOW", 20)
RANGE_ATR_MULT = _envf("MODE_RANGE_ATR_MULT", 2.5)
TOUCH_TOL_ATR = _envf("MODE_TOUCH_TOL_ATR", 0.25)
MIN_TOUCHES = _envi("MODE_MIN_TOUCHES", 2)


@dataclass
class ModeResult:
    mode: str
    direction: Optional[str]
    adx: float
    ema_fast: float
    ema_slow: float
    range_high: float
    range_low: float
    reason: str


def _count_touches(values, level, tol):
    c = 0
    for v in values:
        if abs(v - level) <= tol:
            c += 1
    return c


def detect_mode(
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> ModeResult:
    if len(closes) < EMA_SLOW + 5:
        return ModeResult(
            "NO_TRADE", None, 0.0, 0.0, 0.0,
            0.0, 0.0, "data kurang",
        )
    adx_val = adx(highs, lows, closes)
    ema_f = ema_last(closes, EMA_FAST)
    ema_s = ema_last(closes, EMA_SLOW)
    a = atr(highs, lows, closes)
    close = closes[-1]

    sep = abs(ema_f - ema_s) / ema_s if ema_s else 0.0

    win = min(RANGE_WINDOW, len(closes))
    r_high = max(highs[-win:])
    r_low = min(lows[-win:])
    r_size = r_high - r_low

    # -- TREND --
    if adx_val >= ADX_TREND_MIN and sep >= EMA_SEP_MIN:
        if ema_f > ema_s and close >= ema_f:
            return ModeResult(
                "TREND", "long", adx_val, ema_f, ema_s,
                r_high, r_low, "adx kuat + ema naik",
            )
        if ema_f < ema_s and close <= ema_f:
            return ModeResult(
                "TREND", "short", adx_val, ema_f, ema_s,
                r_high, r_low, "adx kuat + ema turun",
            )

    # -- SIDEWAYS --
    tol = a * TOUCH_TOL_ATR
    sup_touch = _count_touches(lows[-win:], r_low, tol)
    res_touch = _count_touches(highs[-win:], r_high, tol)
    range_ok = a > 0 and r_size >= RANGE_ATR_MULT * a
    touch_ok = sup_touch >= MIN_TOUCHES and res_touch >= MIN_TOUCHES
    if adx_val <= ADX_SIDEWAYS_MAX and range_ok and touch_ok:
        return ModeResult(
            "SIDEWAYS", None, adx_val, ema_f, ema_s,
            r_high, r_low, "adx lemah + range jelas",
        )

    return ModeResult(
        "NO_TRADE", None, adx_val, ema_f, ema_s,
        r_high, r_low, "belum ada kondisi jelas",
    )


# -- v15: AND-gate helper --
MODE_GATE_ENABLE = os.getenv("MODE_GATE_ENABLE", "1") not in ("0", "false", "False", "")


def klines_to_hlc(klines):
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    return highs, lows, closes


def gate_ok(signal, klines):
    highs, lows, closes = klines_to_hlc(klines)
    res = detect_mode(highs, lows, closes)
    if not MODE_GATE_ENABLE:
        return True, res
    sig = (signal or "").upper()
    if res.mode == "NO_TRADE":
        return False, res
    if res.mode == "TREND":
        if res.direction == "long" and sig == "LONG":
            return True, res
        if res.direction == "short" and sig == "SHORT":
            return True, res
        return False, res
    if res.mode == "SIDEWAYS":
        return True, res
    return False, res


# -- v15: 5m entry trigger --
from bot.indicators import rsi as _rsi5

ENTRY_5M_ENABLE = os.getenv("ENTRY_5M_ENABLE", "1") not in ("0", "false", "False", "")
ENTRY_TF = os.getenv("ENTRY_TF", "5m")
ENTRY_EMA = _envi("ENTRY_EMA", 9)
ENTRY_RSI_MAX = _envf("ENTRY_RSI_MAX", 75.0)
ENTRY_RSI_MIN = _envf("ENTRY_RSI_MIN", 25.0)
ENTRY_KLINES = _envi("ENTRY_KLINES", 120)


def entry_trigger_5m(signal, client, sym):
    if not ENTRY_5M_ENABLE:
        return True, "5m off"
    sig = (signal or "").upper()
    try:
        kl5 = client.klines(sym, ENTRY_TF, ENTRY_KLINES)
    except Exception:
        return True, "5m fetch gagal"
    closes = [float(k[4]) for k in kl5]
    if len(closes) < ENTRY_EMA + 5:
        return True, "5m data kurang"
    ema_f = ema_last(closes, ENTRY_EMA)
    r = _rsi5(closes, 14)
    last = closes[-1]
    prev = closes[-2]
    if sig == "LONG":
        ok = last > ema_f and last > prev and r <= ENTRY_RSI_MAX
        return ok, "5m long"
    if sig == "SHORT":
        ok = last < ema_f and last < prev and r >= ENTRY_RSI_MIN
        return ok, "5m short"
    return False, "5m no dir"


# -- v15: pivot-fractal trailing --
from bot.indicators import last_confirmed_pivot_low as _lcpl
from bot.indicators import last_confirmed_pivot_high as _lcph

PIVOT_TRAIL_ENABLE = os.getenv("PIVOT_TRAIL_ENABLE", "1") not in ("0", "false", "False", "")
PIVOT_TRAIL_ATR_MULT = _envf("PIVOT_TRAIL_ATR_MULT", 0.6)
PIVOT_TRAIL_N = _envi("PIVOT_TRAIL_N", 2)


def _pivot_price(piv):
    if piv is None:
        return None
    if isinstance(piv, (tuple, list)):
        return piv[-1] if piv else None
    return piv


def pivot_trail_sl(side, highs, lows, atr):
    if not PIVOT_TRAIL_ENABLE:
        return None
    if not highs or not lows or atr <= 0:
        return None
    s = (side or "").upper()
    off = PIVOT_TRAIL_ATR_MULT * atr
    if s == "LONG":
        price = _pivot_price(_lcpl(lows, PIVOT_TRAIL_N))
        if not price:
            return None
        return price - off
    if s == "SHORT":
        price = _pivot_price(_lcph(highs, PIVOT_TRAIL_N))
        if not price:
            return None
        return price + off
    return None


# -- v15: per-symbol cooldown settings --
PAIR_CD_ENABLE = os.getenv("PAIR_CD_ENABLE", "1") not in ("0", "false", "False", "")
PAIR_CD_LOSS = _envi("PAIR_CD_LOSS", 600)
PAIR_CD_WIN = _envi("PAIR_CD_WIN", 90)
GLOBAL_CD_ENABLE = os.getenv("GLOBAL_COOLDOWN_ENABLE", "0") not in ("0", "false", "False", "")


# -- v15: A+ override settings --
APLUS_OVERRIDE = os.getenv("APLUS_OVERRIDE", "1") not in ("0", "false", "False", "")
APLUS_CONF = _envf("APLUS_CONF", 0.80)
