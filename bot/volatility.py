from __future__ import annotations
"""v11 (3): Prediksi Volatilitas / Squeeze Detector.

Gabungkan funding rate + perubahan open interest + realized volatility utk
memprediksi kapan volatilitas berpotensi meledak (squeeze) -> sinkron dgn
Fast-Scan Breakout. Data dari Binance Futures (no API berbayar).

Catatan: Implied Volatility dari options (Deribit) butuh sumber terpisah dan
belum diaktifkan di sini; pakai realized vol + funding + OI sebagai proxy.
"""
from statistics import pstdev


def realized_vol(klines: list, lookback: int = 20) -> float:
    """Stdev return antar candle (dalam %), proxy realized volatility."""
    try:
        closes = [float(k[4]) for k in klines[-(lookback + 1):]]
        if len(closes) < 3:
            return 0.0
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] > 0]
        return round(pstdev(rets) * 100, 4)
    except Exception:
        return 0.0


def squeeze_signal(client, symbol: str, klines: list,
                   funding_extreme: float = 0.0005, oi_rise_pct: float = 0.02) -> dict:
    """Deteksi potensi squeeze.

    - funding NEGATIF ekstrem + OI naik -> short menumpuk -> potensi SHORT-SQUEEZE (harga naik).
    - funding POSITIF ekstrem + OI naik -> long menumpuk -> potensi LONG-SQUEEZE (harga turun).
    Return dict {squeeze, funding, oi_change, rvol, direction, note}.
    """
    res = {"squeeze": False, "funding": 0.0, "oi_change": 0.0, "rvol": 0.0,
           "direction": "NEUTRAL", "note": ""}
    try:
        funding = float(client.funding_rate(symbol))
        res["funding"] = round(funding, 6)
        res["rvol"] = realized_vol(klines)
        oi_chg = 0.0
        try:
            hist = client.open_interest_hist(symbol, "5m", 6)
            if hist and len(hist) >= 2:
                first = float(hist[0].get("sumOpenInterest", 0) or 0)
                last  = float(hist[-1].get("sumOpenInterest", 0) or 0)
                if first > 0:
                    oi_chg = (last - first) / first
        except Exception:
            pass
        res["oi_change"] = round(oi_chg, 4)

        if abs(funding) >= funding_extreme and oi_chg >= oi_rise_pct:
            res["squeeze"] = True
            if funding < 0:
                res["direction"] = "LONG"
                res["note"] = (f"{symbol}: funding {funding*100:.3f}% NEG + OI +{oi_chg*100:.1f}% "
                               f"-> potensi SHORT-SQUEEZE (naik). Siapin fast-scan LONG.")
            else:
                res["direction"] = "SHORT"
                res["note"] = (f"{symbol}: funding {funding*100:.3f}% POS + OI +{oi_chg*100:.1f}% "
                               f"-> potensi LONG-SQUEEZE (turun). Siapin fast-scan SHORT.")
    except Exception:
        pass
    return res
