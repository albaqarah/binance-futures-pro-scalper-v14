#!/usr/bin/env python3
"""
fetch_history.py — Binance USDⓈ-M Futures history collector (pure stdlib)

No external dependency (uses only urllib) → runs on a minimal VPS.
Pulls months of history straight from the Binance REST API to retrain the ML.

SINGLE SOURCE OF TRUTH:
  The pair list is read from SYMBOLS in .env (fully manual — you edit it there).
  Timeframe defaults to TIMEFRAMES in .env. Override anytime with --symbols / --tf.

Examples:
  python3 fetch_history.py --months 6
  python3 fetch_history.py --months 3 --symbols BNBUSDT,SOLUSDT --tf 15m --cvd

Output CSV → data_historis/ folder:
  <PAIR>_<TF>.csv         klines OHLCV (ready for train.py)
  <PAIR>_funding.csv      funding rate history
  <PAIR>_oi.csv           open interest history (max 30 days)
  <PAIR>_lsr.csv          global long/short account ratio (max 30 days)
  <PAIR>_taker.csv        taker buy/sell volume ratio (max 30 days)
  <PAIR>_<TF>_cvd.csv     CVD reconstructed from aggTrades (optional --cvd)

HISTORY NOTES:
  - klines & fundingRate: available for months (paginated).
  - openInterestHist / longShortRatio / takerlongshortRatio: LAST 30 days only.
  - orderbook depth has NO history (real-time only) → not fetched.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

FAPI = "https://fapi.binance.com"
OUT = "data_historis"


def _load_env():
    """Load .env so SYMBOLS / TIMEFRAMES are available even when run standalone.
    Tries python-dotenv first, then falls back to a tiny stdlib parser."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path if os.path.exists(env_path) else None, override=False)
        return
    except Exception:
        pass
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


_load_env()


def _env_symbols() -> list[str]:
    """Active pair list — the ONE manual source of truth (SYMBOLS in .env)."""
    raw = os.getenv("SYMBOLS", "BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _env_tfs() -> list[str]:
    raw = os.getenv("TIMEFRAMES", "15m")
    return [t.strip() for t in raw.split(",") if t.strip()]


DEFAULT_SYMBOLS = _env_symbols()
DEFAULT_TFS = _env_tfs()

# Timeframe interval -> milliseconds
TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
}


def _get(path: str, params: dict | None = None, retries: int = 5):
    """GET JSON with retry + exponential backoff (survives rate-limit/timeout)."""
    url = FAPI + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "scalper-v14/fetch"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            # 429/418 = rate limit -> wait longer
            wait = (2 ** attempt) * (5 if e.code in (418, 429) else 1)
            sys.stderr.write(f"  HTTP {e.code} {path} -> retry {attempt+1}/{retries} (sleep {wait}s)\n")
            time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = 2 ** attempt
            sys.stderr.write(f"  ERR {path}: {e} -> retry {attempt+1}/{retries} (sleep {wait}s)\n")
            time.sleep(wait)
    raise RuntimeError(f"Failed GET {path} after {retries}x: {last_err}")


def _write_csv(filename: str, header: list[str], rows: list[list]):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, filename)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  -> {path} ({len(rows)} rows)")
    return path


def fetch_klines(symbol: str, tf: str, months: int) -> list[list]:
    """Pull OHLCV klines paginating backwards `months` months from now."""
    if tf not in TF_MS:
        raise ValueError(f"Unsupported TF: {tf}")
    step = TF_MS[tf]
    end = int(time.time() * 1000)
    start = end - months * 30 * 24 * 60 * 60 * 1000
    rows: list[list] = []
    cursor = start
    while cursor < end:
        data = _get("/fapi/v1/klines", {
            "symbol": symbol, "interval": tf,
            "startTime": cursor, "limit": 1500,
        })
        if not data:
            break
        for k in data:
            # [openTime, open, high, low, close, volume, closeTime, ...]
            rows.append([k[0], k[1], k[2], k[3], k[4], k[5]])
        last_open = data[-1][0]
        nxt = last_open + step
        if nxt <= cursor:
            break
        cursor = nxt
        if len(data) < 1500:
            break
        time.sleep(0.25)  # be polite to the rate limit
    return rows


def fetch_funding(symbol: str, months: int) -> list[list]:
    """Funding rate history (~8h). Paginate backwards."""
    end = int(time.time() * 1000)
    start = end - months * 30 * 24 * 60 * 60 * 1000
    rows: list[list] = []
    cursor = start
    while cursor < end:
        data = _get("/fapi/v1/fundingRate", {
            "symbol": symbol, "startTime": cursor, "limit": 1000,
        })
        if not data:
            break
        for d in data:
            rows.append([d["fundingTime"], d["fundingRate"]])
        last = data[-1]["fundingTime"]
        if last + 1 <= cursor:
            break
        cursor = last + 1
        if len(data) < 1000:
            break
        time.sleep(0.25)
    return rows


def fetch_metric(path: str, symbol: str, value_keys: list[str], period: str = "5m") -> list[list]:
    """Generic /futures/data metric (OI / long-short / taker). Max 30 days (limit 500)."""
    data = _get(path, {"symbol": symbol, "period": period, "limit": 500})
    rows: list[list] = []
    for d in data:
        ts = d.get("timestamp")
        rows.append([ts] + [d.get(k) for k in value_keys])
    return rows


def fetch_cvd(symbol: str, tf: str, hours: int = 24) -> list[list]:
    """Reconstruct CVD (Cumulative Volume Delta) from aggTrades.
    m=True means the buyer is the maker -> aggressive SELL side.
    Limited to the last `hours` so it does not explode (aggTrades is huge).
    """
    step = TF_MS.get(tf, 300_000)
    end = int(time.time() * 1000)
    start = end - hours * 60 * 60 * 1000
    buckets: dict[int, float] = {}
    cursor = start
    while cursor < end:
        try:
            data = _get("/fapi/v1/aggTrades", {
                "symbol": symbol, "startTime": cursor,
                "endTime": min(cursor + 60 * 60 * 1000, end), "limit": 1000,
            })
        except Exception:
            break
        if not data:
            cursor += 60 * 60 * 1000
            continue
        for t in data:
            ts = t["T"]
            qty = float(t["q"])
            delta = -qty if t.get("m") else qty  # m=True -> aggressive sell
            bkt = (ts // step) * step
            buckets[bkt] = buckets.get(bkt, 0.0) + delta
        last = data[-1]["T"]
        if last + 1 <= cursor:
            cursor += 60 * 60 * 1000
        else:
            cursor = last + 1
        time.sleep(0.2)
    rows = [[b, round(buckets[b], 4)] for b in sorted(buckets)]
    return rows


def main():
    ap = argparse.ArgumentParser(description="Binance Futures history collector")
    ap.add_argument("--months", type=int, default=6, help="How many months of klines/funding (default 6)")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                    help="Comma-separated. Default = SYMBOLS from .env")
    ap.add_argument("--tf", default=",".join(DEFAULT_TFS),
                    help="Timeframe(s), comma-separated. Default = TIMEFRAMES from .env")
    ap.add_argument("--cvd", action="store_true", help="Also reconstruct CVD (slow)")
    ap.add_argument("--cvd-hours", type=int, default=24, help="Last N hours for CVD")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]

    os.makedirs(OUT, exist_ok=True)
    print(f"Active pairs (from .env SYMBOLS unless overridden): {', '.join(symbols)}")
    print(f"Fetching {len(symbols)} symbols x {len(tfs)} TF | {args.months} months -> {OUT}/")

    for sym in symbols:
        print(f"\n=== {sym} ===")
        for tf in tfs:
            print(f"[klines {tf}]")
            kl = fetch_klines(sym, tf, args.months)
            if kl:
                _write_csv(f"{sym}_{tf}.csv",
                           ["timestamp", "open", "high", "low", "close", "volume"], kl)
            if args.cvd:
                print(f"[cvd {tf}]")
                cvd = fetch_cvd(sym, tf, args.cvd_hours)
                if cvd:
                    _write_csv(f"{sym}_{tf}_cvd.csv", ["timestamp", "cvd_delta"], cvd)

        print("[funding]")
        fr = fetch_funding(sym, args.months)
        if fr:
            _write_csv(f"{sym}_funding.csv", ["timestamp", "funding_rate"], fr)

        # Last 30 days only
        try:
            print("[open interest 30d]")
            oi = fetch_metric("/futures/data/openInterestHist", sym,
                              ["sumOpenInterest", "sumOpenInterestValue"])
            if oi:
                _write_csv(f"{sym}_oi.csv", ["timestamp", "sum_oi", "sum_oi_value"], oi)
        except Exception as e:  # noqa: BLE001
            print(f"  skip OI: {e}")

        try:
            print("[long/short ratio 30d]")
            lsr = fetch_metric("/futures/data/globalLongShortAccountRatio", sym,
                               ["longShortRatio", "longAccount", "shortAccount"])
            if lsr:
                _write_csv(f"{sym}_lsr.csv",
                           ["timestamp", "long_short_ratio", "long_account", "short_account"], lsr)
        except Exception as e:  # noqa: BLE001
            print(f"  skip LSR: {e}")

        try:
            print("[taker ratio 30d]")
            tk = fetch_metric("/futures/data/takerlongshortRatio", sym,
                              ["buySellRatio", "buyVol", "sellVol"])
            if tk:
                _write_csv(f"{sym}_taker.csv",
                           ["timestamp", "buy_sell_ratio", "buy_vol", "sell_vol"], tk)
        except Exception as e:  # noqa: BLE001
            print(f"  skip taker: {e}")

    print("\nDone. Check the folder:", OUT)


if __name__ == "__main__":
    main()
