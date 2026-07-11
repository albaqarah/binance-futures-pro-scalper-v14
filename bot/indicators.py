from __future__ import annotations
from dataclasses import dataclass
from typing import List


def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_series(closes: List[float], period: int = 14) -> List[float]:
    out = []
    for i in range(period + 1, len(closes) + 1):
        out.append(rsi(closes[:i], period))
    return out


def rsi_reversal(closes: List[float], period: int = 6, overbought: float = 70.0, oversold: float = 30.0, lookback: int = 3) -> str | None:
    """Deteksi pembalikan RSI cepat (mis. RSI(6) seperti di chart Binance).

    Return:
      "top"    -> RSI baru saja menyentuh area overbought lalu MULAI turun (sinyal TP untuk LONG)
      "bottom" -> RSI baru saja menyentuh area oversold lalu MULAI naik (sinyal TP untuk SHORT)
      None     -> belum ada pembalikan yang jelas
    """
    series = rsi_series(closes, period)
    if len(series) < max(2, lookback + 1):
        return None
    recent = series[-(lookback + 1):]
    cur = series[-1]
    prev = series[-2]
    if max(recent) >= overbought and cur < prev:
        return "top"
    if min(recent) <= oversold and cur > prev:
        return "bottom"
    return None


def stoch_rsi(closes: List[float], rsi_period: int = 14, stoch_period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> tuple[float, float]:
    rsis = rsi_series(closes, rsi_period)
    if len(rsis) < stoch_period + smooth_k + smooth_d:
        return 50.0, 50.0
    vals = []
    for i in range(stoch_period, len(rsis) + 1):
        win = rsis[i-stoch_period:i]
        lo, hi = min(win), max(win)
        vals.append(50.0 if hi == lo else (rsis[i-1] - lo) / (hi - lo) * 100)
    k_series = []
    for i in range(smooth_k, len(vals) + 1):
        k_series.append(sum(vals[i-smooth_k:i]) / smooth_k)
    d_series = []
    for i in range(smooth_d, len(k_series) + 1):
        d_series.append(sum(k_series[i-smooth_d:i]) / smooth_d)
    return k_series[-1], d_series[-1]


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float, float]:
    if len(closes) < slow + signal + 5:
        return 0.0, 0.0, 0.0, 0.0
    ef = ema(closes, fast)
    es = ema(closes, slow)
    macd_line = [a - b for a, b in zip(ef[-len(es):], es)]
    sig = ema(macd_line, signal)
    hist = macd_line[-1] - sig[-1]
    prev_hist = macd_line[-2] - sig[-2] if len(macd_line) >= 2 and len(sig) >= 2 else hist
    return macd_line[-1], sig[-1], hist, prev_hist


def kdj(highs: List[float], lows: List[float], closes: List[float], period: int = 9) -> tuple[float, float, float]:
    if len(closes) < period:
        return 50.0, 50.0, 50.0
    k, d = 50.0, 50.0
    for i in range(period - 1, len(closes)):
        hh = max(highs[i-period+1:i+1])
        ll = min(lows[i-period+1:i+1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
    j = 3 * k - 2 * d
    return k, d, j


def ema_last(values: List[float], period: int) -> float:
    s = ema(values, period)
    return s[-1] if s else 0.0


def sma(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if period <= 0 or len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    n = len(closes)
    if n < 2:
        return 0.0
    trs = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def bollinger(closes: List[float], period: int = 20, mult: float = 2.0) -> tuple[float, float, float]:
    if not closes:
        return 0.0, 0.0, 0.0
    if len(closes) < period:
        m = sum(closes) / len(closes)
        return m, m, m
    window = closes[-period:]
    m = sum(window) / period
    sd = (sum((x - m) ** 2 for x in window) / period) ** 0.5
    return m, m + mult * sd, m - mult * sd


def vwap(highs: List[float], lows: List[float], closes: List[float], volumes: List[float]) -> float:
    num = 0.0
    den = 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3
        num += tp * v
        den += v
    return num / den if den > 0 else (closes[-1] if closes else 0.0)


def stochastic(highs: List[float], lows: List[float], closes: List[float], k_period: int = 5, d_period: int = 3, smooth: int = 3) -> tuple[float, float, float, float]:
    """Stochastic klasik di harga. Return (%K, %D, %K_prev, %D_prev) untuk deteksi cross."""
    n = len(closes)
    if n < k_period + d_period:
        return 50.0, 50.0, 50.0, 50.0
    raw = []
    for i in range(k_period - 1, n):
        hh = max(highs[i-k_period+1:i+1])
        ll = min(lows[i-k_period+1:i+1])
        raw.append(50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100)
    kser = []
    for i in range(smooth, len(raw) + 1):
        kser.append(sum(raw[i-smooth:i]) / smooth)
    if not kser:
        return 50.0, 50.0, 50.0, 50.0
    dser = []
    for i in range(d_period, len(kser) + 1):
        dser.append(sum(kser[i-d_period:i]) / d_period)
    k_now = kser[-1]
    k_prev = kser[-2] if len(kser) >= 2 else k_now
    d_now = dser[-1] if dser else k_now
    d_prev = dser[-2] if len(dser) >= 2 else d_now
    return k_now, d_now, k_prev, d_prev


@dataclass
class IndicatorPack:
    timeframe: str
    rsi: float
    stoch_k: float
    stoch_d: float
    macd_hist: float
    macd_prev_hist: float
    kdj_k: float
    kdj_d: float
    kdj_j: float
    close: float


def build_pack(timeframe: str, klines: list) -> IndicatorPack:
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    sk, sd = stoch_rsi(closes)
    _, _, mh, pmh = macd(closes)
    kk, kd, kj = kdj(highs, lows, closes)
    return IndicatorPack(timeframe, rsi(closes), sk, sd, mh, pmh, kk, kd, kj, closes[-1])

# -- v15: ADX (Wilder) --
def adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    n = len(closes)
    if n < period * 2:
        return 0.0
    plus_dm = [0.0]
    minus_dm = [0.0]
    trs = [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        if up > dn and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0.0)
        if dn > up and dn > 0:
            minus_dm.append(dn)
        else:
            minus_dm.append(0.0)
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1]),
        ))

    def _smooth(vals, period):
        if len(vals) < period + 1:
            return []
        out = [sum(vals[1:period+1])]
        for v in vals[period+1:]:
            out.append(out[-1] - (out[-1] / period) + v)
        return out

    tr_s = _smooth(trs, period)
    pdm_s = _smooth(plus_dm, period)
    mdm_s = _smooth(minus_dm, period)
    if not tr_s:
        return 0.0
    plus_di = []
    minus_di = []
    for p, t in zip(pdm_s, tr_s):
        plus_di.append(100 * (p / t) if t > 0 else 0.0)
    for m, t in zip(mdm_s, tr_s):
        minus_di.append(100 * (m / t) if t > 0 else 0.0)
    dx = []
    for p, m in zip(plus_di, minus_di):
        if (p + m) > 0:
            dx.append(100 * abs(p - m) / (p + m))
        else:
            dx.append(0.0)
    if not dx:
        return 0.0
    if len(dx) < period:
        return sum(dx) / len(dx)
    adx_val = sum(dx[:period]) / period
    for d in dx[period:]:
        adx_val = (adx_val * (period - 1) + d) / period
    return adx_val


# -- v15: ADX (Wilder) --
def adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    n = len(closes)
    if n < period * 2:
        return 0.0
    plus_dm = [0.0]
    minus_dm = [0.0]
    trs = [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        if up > dn and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0.0)
        if dn > up and dn > 0:
            minus_dm.append(dn)
        else:
            minus_dm.append(0.0)
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1]),
        ))

    def _smooth(vals, period):
        if len(vals) < period + 1:
            return []
        out = [sum(vals[1:period+1])]
        for v in vals[period+1:]:
            out.append(out[-1] - (out[-1] / period) + v)
        return out

    tr_s = _smooth(trs, period)
    pdm_s = _smooth(plus_dm, period)
    mdm_s = _smooth(minus_dm, period)
    if not tr_s:
        return 0.0
    plus_di = []
    minus_di = []
    for p, t in zip(pdm_s, tr_s):
        plus_di.append(100 * (p / t) if t > 0 else 0.0)
    for m, t in zip(mdm_s, tr_s):
        minus_di.append(100 * (m / t) if t > 0 else 0.0)
    dx = []
    for p, m in zip(plus_di, minus_di):
        if (p + m) > 0:
            dx.append(100 * abs(p - m) / (p + m))
        else:
            dx.append(0.0)
    if not dx:
        return 0.0
    if len(dx) < period:
        return sum(dx) / len(dx)
    adx_val = sum(dx[:period]) / period
    for d in dx[period:]:
        adx_val = (adx_val * (period - 1) + d) / period
    return adx_val


# -- v15: Pivot Fractal (n=2, confirmed) --
def is_pivot_low(lows: List[float], i: int, n: int = 2) -> bool:
    if i - n < 0 or i + n >= len(lows):
        return False
    left = all(lows[i] < lows[i-k] for k in range(1, n+1))
    right = all(lows[i] <= lows[i+k] for k in range(1, n+1))
    return left and right


def is_pivot_high(highs: List[float], i: int, n: int = 2) -> bool:
    if i - n < 0 or i + n >= len(highs):
        return False
    left = all(highs[i] > highs[i-k] for k in range(1, n+1))
    right = all(highs[i] >= highs[i+k] for k in range(1, n+1))
    return left and right


def last_confirmed_pivot_low(lows: List[float], n: int = 2):
    for i in range(len(lows) - n - 1, n - 1, -1):
        if is_pivot_low(lows, i, n):
            return i, lows[i]
    return None


def last_confirmed_pivot_high(highs: List[float], n: int = 2):
    for i in range(len(highs) - n - 1, n - 1, -1):
        if is_pivot_high(highs, i, n):
            return i, highs[i]
    return None
