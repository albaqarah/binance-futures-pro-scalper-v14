try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception as e:
    print("no dotenv:", e)
try:
    import bot.config
except Exception as e:
    print("no bot.config:", e)

import requests
from bot.mode_selector import (
    detect_mode, klines_to_hlc, _count_touches,
    ADX_TREND_MIN, ADX_SIDEWAYS_MAX, EMA_SEP_MIN,
    EMA_FAST, EMA_SLOW, RANGE_WINDOW, RANGE_ATR_MULT,
    TOUCH_TOL_ATR, MIN_TOUCHES,
)
from bot.indicators import adx, ema_last, atr

print("THRESH ADX_TREND_MIN=%s ADX_SW_MAX=%s EMA_SEP_MIN=%s FAST=%s SLOW=%s RANGE_ATR=%s MINTOUCH=%s TOL=%s" % (
    ADX_TREND_MIN, ADX_SIDEWAYS_MAX, EMA_SEP_MIN, EMA_FAST, EMA_SLOW, RANGE_ATR_MULT, MIN_TOUCHES, TOUCH_TOL_ATR))

SYMS = ["BTCUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT"]
TFS = ["3m", "5m", "15m"]
URL = "https://fapi.binance.com/fapi/v1/klines"

for tf in TFS:
    print("")
    print("===== TF " + tf + " =====")
    for s in SYMS:
        try:
            r = requests.get(URL, params={"symbol": s, "interval": tf, "limit": 80}, timeout=10)
            kl = r.json()
            highs, lows, closes = klines_to_hlc(kl)
            res = detect_mode(highs, lows, closes)
            av = adx(highs, lows, closes)
            ef = ema_last(closes, EMA_FAST)
            es = ema_last(closes, EMA_SLOW)
            a = atr(highs, lows, closes)
            sep = abs(ef - es) / es if es else 0.0
            win = min(RANGE_WINDOW, len(closes))
            rh = max(highs[-win:])
            rl = min(lows[-win:])
            rsize = rh - rl
            tol = a * TOUCH_TOL_ATR
            sup = _count_touches(lows[-win:], rl, tol)
            rst = _count_touches(highs[-win:], rh, tol)
            range_ok = a > 0 and rsize >= RANGE_ATR_MULT * a
            touch_ok = sup >= MIN_TOUCHES and rst >= MIN_TOUCHES
            print("%-9s n=%d mode=%-10s adx=%.1f sep=%.3f%% range_ok=%s touch=%d/%d touch_ok=%s reason=%s" % (
                s, len(closes), res.mode, av, sep * 100, range_ok, sup, rst, touch_ok, res.reason))
        except Exception as e:
            print("%-9s ERROR %s" % (s, e))
