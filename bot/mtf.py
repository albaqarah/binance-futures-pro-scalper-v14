"""
mtf.py — Multi-Timeframe Confirmation
Cek trend di TF lebih besar sebelum entry di TF kecil.
Mencegah entry melawan trend utama.
"""
from __future__ import annotations
import pandas as pd

# TF higher untuk setiap TF entry
HTF_MAP = {
    "1m":  "5m",
    "3m":  "15m",
    "5m":  "15m",
    "15m": "1h",
    "30m": "4h",
    "1h":  "4h",
}


def get_htf_trend(client, symbol: str, entry_tf: str) -> str:
    """
    Return: "UP" | "DOWN" | "NEUTRAL"
    Pakai EMA20 vs EMA50 di HTF untuk tentukan trend.
    """
    htf = HTF_MAP.get(entry_tf, "15m")
    try:
        klines = client.klines(symbol, htf, 60)
        df = pd.DataFrame(klines, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","qav","trades","tbav","tqav","ignore"
        ])
        close = df["close"].astype(float)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        gap_pct = abs(e20 - e50) / e50 * 100
        if e20 > e50 and gap_pct > 0.05:
            return "UP"
        elif e20 < e50 and gap_pct > 0.05:
            return "DOWN"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"  # fallback: tidak block entry


def mtf_confirms(htf_trend: str, signal: str) -> bool:
    """
    LONG hanya kalau HTF UP atau NEUTRAL
    SHORT hanya kalau HTF DOWN atau NEUTRAL
    """
    if signal == "LONG"  and htf_trend == "DOWN":  return False
    if signal == "SHORT" and htf_trend == "UP":    return False
    return True
