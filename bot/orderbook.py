"""
orderbook.py — Order Book Imbalance Filter
Cek tekanan beli vs jual dari Binance order book sebelum entry.
"""
from __future__ import annotations
import json
from urllib.request import urlopen, Request
from urllib.error import URLError

BINANCE_DEPTH = "https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit=20"


def get_imbalance(symbol: str) -> dict:
    """
    Return:
      {
        "bid_vol": 123.4,   # total bid qty top-20
        "ask_vol": 98.2,    # total ask qty top-20
        "ratio":   1.26,    # bid/ask ratio
        "signal":  "buy"    # "buy"|"sell"|"neutral"
        "ok":      True
      }
    Ratio > 1.2  = tekanan beli kuat  -> dukung LONG
    Ratio < 0.83 = tekanan jual kuat  -> dukung SHORT
    """
    try:
        url = BINANCE_DEPTH.format(symbol=symbol)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=6) as r:
            data = json.loads(r.read())
        bid_vol = sum(float(b[1]) for b in data.get("bids", []))
        ask_vol = sum(float(a[1]) for a in data.get("asks", []))
        ratio   = bid_vol / ask_vol if ask_vol > 0 else 1.0
        if ratio > 1.2:
            sig = "buy"
        elif ratio < 0.83:
            sig = "sell"
        else:
            sig = "neutral"
        return {"bid_vol": bid_vol, "ask_vol": ask_vol,
                "ratio": ratio, "signal": sig, "ok": True}
    except Exception:
        return {"bid_vol": 0, "ask_vol": 0, "ratio": 1.0,
                "signal": "neutral", "ok": False}


def orderbook_confirms(ob: dict, signal: str) -> bool:
    """
    Apakah order book mendukung sinyal?
    LONG butuh ob.signal == 'buy' atau 'neutral'
    SHORT butuh ob.signal == 'sell' atau 'neutral'
    Kalau fetch gagal (ok=False) -> lolos (jangan block entry)
    """
    if not ob.get("ok", True):
        return True  # fallback: lolos
    ob_sig = ob.get("signal", "neutral")
    if signal == "LONG"  and ob_sig == "sell":   return False
    if signal == "SHORT" and ob_sig == "buy":    return False
    return True
