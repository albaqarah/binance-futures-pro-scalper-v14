from __future__ import annotations
"""v11 (2 — REVISI): Positioning / Derivatives Bias. Binance GRATIS & real-time.

Ganti total on-chain berbayar. Pakai endpoint futures gratis:
  - /futures/data/globalLongShortAccountRatio -> rasio AKUN retail long vs short (CONTRARIAN)
  - /futures/data/topLongShortPositionRatio   -> POSISI top trader / smart money (FOLLOW)

Logika:
  - Retail kelewat LONG (ratio tinggi) -> sering jadi exit liquidity -> contrarian SHORT.
  - Top trader net LONG -> ikut smart money -> LONG.
  - Kalau retail-contrarian & smart-money searah -> sinyal KUAT.
  - Kalau konflik -> NETRAL (jangan maksa).
Update tiap 5m, ringan (REST), cocok scalping. Tanpa API berbayar.
"""


def positioning_signal(client, symbol: str, crowd_extreme: float = 2.0) -> dict:
    res = {"bias": "NEUTRAL", "score": 0.0, "retail": 0.0, "top": 0.0,
           "note": "", "parts": []}
    try:
        retail = float(client.long_short_account_ratio(symbol))      # akun retail long/short
        top    = float(client.top_long_short_position_ratio(symbol))  # posisi top trader
        res["retail"], res["top"] = round(retail, 3), round(top, 3)

        # Retail = contrarian
        retail_bias = "NEUTRAL"
        if retail >= crowd_extreme:
            retail_bias = "SHORT"
        elif 0 < retail <= (1.0 / crowd_extreme):
            retail_bias = "LONG"

        # Top trader = follow
        top_bias = "NEUTRAL"
        if top >= 1.05:
            top_bias = "LONG"
        elif 0 < top <= 0.95:
            top_bias = "SHORT"

        if retail_bias != "NEUTRAL":
            res["parts"].append(f"RETAIL L/S {retail:.2f}->{retail_bias}")
        if top_bias != "NEUTRAL":
            res["parts"].append(f"TOP L/S {top:.2f}->{top_bias}")

        if retail_bias != "NEUTRAL" and top_bias != "NEUTRAL":
            if retail_bias == top_bias:
                res["bias"], res["score"] = retail_bias, 1.0
                res["note"] = (f"{symbol}: retail L/S {retail:.2f} + top trader L/S {top:.2f} "
                               f"-> {retail_bias} bias STRONG (retail contrarian + smart money aligned).")
            else:
                res["bias"] = "NEUTRAL"  # konflik -> jangan entry
        elif top_bias != "NEUTRAL":
            res["bias"], res["score"] = top_bias, 0.5  # ikut smart money
        elif retail_bias != "NEUTRAL":
            res["bias"], res["score"] = retail_bias, 0.5
            _crowd = "LONG" if retail_bias == "SHORT" else "SHORT"
            res["note"] = (f"{symbol}: retail kelewat {_crowd} (L/S {retail:.2f}) "
                           f"-> waspada reversal, bias {retail_bias}.")
    except Exception:
        pass
    return res
