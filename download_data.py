"""
download_data.py  —  Download data historis dari Binance Futures API
Jalankan: python download_data.py
Hasil   : folder data_historis/ berisi CSV untuk training
"""
import os, time, csv, urllib.request, json
from pathlib import Path

PAIRS     = ["BNBUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]
TIMEFRAMES= ["3m", "5m"]
LIMIT     = 1500   # candle per request (max Binance = 1500)
OUT_DIR   = Path("data_historis")
BASE_URL  = "https://fapi.binance.com"   # Binance Futures

OUT_DIR.mkdir(exist_ok=True)

def download(pair: str, tf: str) -> str:
    url = (f"{BASE_URL}/fapi/v1/klines"
           f"?symbol={pair}&interval={tf}&limit={LIMIT}")
    print(f"  Download {pair} {tf} ... ", end="", flush=True)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    path = OUT_DIR / f"{pair}_{tf}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp","open","high","low","close","volume"])
        for k in data:
            w.writerow([k[0], k[1], k[2], k[3], k[4], k[5]])
    print(f"{len(data)} candle -> {path}")
    return str(path)

if __name__ == "__main__":
    print("=== Download data historis dari Binance Futures ===")
    ok = []
    for pair in PAIRS:
        for tf in TIMEFRAMES:
            try:
                ok.append(download(pair, tf))
                time.sleep(0.3)  # hindari rate limit
            except Exception as e:
                print(f"GAGAL {pair} {tf}: {e}")
    print(f"\nSelesai. {len(ok)} file tersimpan di '{OUT_DIR}/':")
    for f in ok:
        print(f"  {f}")
    print("\nLangkah selanjutnya:")
    print("  python -m bot.train --data-dir data_historis --out-dir models")
