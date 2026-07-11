from __future__ import annotations
"""v11 (1): Detektor Anomali Volume & Order Flow.

Gabungkan cumulative delta (taker buy vs sell), bid-ask imbalance, dan
deteksi 'tembok' order (potensi spoofing / fake support-resistance).
Semua pakai data publik Binance Futures (klines + depth) -> ringan, cocok scalping.
"""


def cumulative_delta(klines: list, lookback: int = 20):
    """Akumulasi (taker_buy - taker_sell) N candle terakhir.

    Index kline Binance: 5=volume(base), 9=taker buy base volume.
    taker_sell = volume - taker_buy ; delta = taker_buy - taker_sell = 2*tbuy - vol.
    Return (delta_absolut, delta_ternormalisasi -1..+1).
    """
    try:
        rows = klines[-lookback:]
        delta = 0.0
        total = 0.0
        for k in rows:
            vol  = float(k[5])
            tbuy = float(k[9])
            delta += (2.0 * tbuy - vol)
            total += vol
        norm = 0.0 if total <= 0 else max(-1.0, min(1.0, delta / total))
        return round(delta, 2), round(norm, 3)
    except Exception:
        return 0.0, 0.0


def detect_wall(depth: dict, side_ratio: float = 0.55):
    """Deteksi satu level order yang ukurannya dominan terhadap sisinya.

    Tembok besar yang tiba-tiba ada sering dipakai utk spoofing (manipulasi).
    Return dict {bid_wall, ask_wall, bid_wall_qty, ask_wall_qty}.
    """
    out = {"bid_wall": False, "ask_wall": False, "bid_wall_qty": 0.0, "ask_wall_qty": 0.0}
    try:
        bids = [(float(p), float(q)) for p, q in depth.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in depth.get("asks", [])]
        bt = sum(q for _, q in bids)
        at = sum(q for _, q in asks)
        if bids and bt > 0:
            _, mq = max(bids, key=lambda x: x[1])
            if mq / bt >= side_ratio:
                out["bid_wall"] = True
                out["bid_wall_qty"] = round(mq, 3)
        if asks and at > 0:
            _, mq = max(asks, key=lambda x: x[1])
            if mq / at >= side_ratio:
                out["ask_wall"] = True
                out["ask_wall_qty"] = round(mq, 3)
    except Exception:
        pass
    return out


def analyze_orderflow(client, symbol: str, klines: list, lookback: int = 20, wall_ratio: float = 0.55) -> dict:
    """Output: bias arah (LONG/SHORT/NEUTRAL), flag spoof, dan warning utk AI/Telegram."""
    res = {"delta": 0.0, "delta_norm": 0.0, "imbalance": 0.0,
           "bias": "NEUTRAL", "spoof": False, "warning": "", "parts": []}
    try:
        d_abs, d_norm = cumulative_delta(klines, lookback)
        res["delta"], res["delta_norm"] = d_abs, d_norm
        try:
            imb = float(client.orderbook_imbalance(symbol))
        except Exception:
            imb = 0.0
        res["imbalance"] = round(imb, 3)
        try:
            depth = client.depth(symbol, 20)
        except Exception:
            depth = {}
        walls = detect_wall(depth, wall_ratio)

        score = d_norm + imb
        if score > 0.12:
            res["bias"] = "LONG"
        elif score < -0.12:
            res["bias"] = "SHORT"

        # Spoof: tembok besar tapi aliran order (delta) justru berlawanan -> fake.
        if walls.get("bid_wall") and d_norm < -0.05:
            res["spoof"] = True
            res["warning"] = (f"{symbol}: tembok BID besar ({walls['bid_wall_qty']}) tapi delta JUAL dominan "
                              f"-> kemungkinan fake support, hati-hati LONG.")
        elif walls.get("ask_wall") and d_norm > 0.05:
            res["spoof"] = True
            res["warning"] = (f"{symbol}: tembok ASK besar ({walls['ask_wall_qty']}) tapi delta BELI dominan "
                              f"-> kemungkinan fake resistance, hati-hati SHORT.")
        res["parts"] = [f"CD{d_norm:+.2f}", f"IMB{imb:+.2f}"]
    except Exception:
        pass
    return res
