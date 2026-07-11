"""
setup_and_train.py
==================
One command does it all:
  python3 setup_and_train.py

What it does automatically:
  1. Check and install missing libraries
  2. Make sure historical data for the ACTIVE pairs exists (quick-download if missing)
  3. Train the LightGBM model with walk-forward validation
  4. Save models to the models/ folder
  5. Show results: winrate, profit factor per pair

SINGLE SOURCE OF TRUTH (fully manual):
  The active pair list comes ONLY from SYMBOLS in .env, and the timeframe(s)
  from TIMEFRAMES in .env. Training NO LONGER scans every CSV in the folder —
  it trains EXACTLY the pairs you list in SYMBOLS. Any leftover CSV outside
  that list is ignored (not trained), so stale coins can never sneak back in.

After it finishes, run the bot:
  python3 -m bot.main
"""
import subprocess, sys, os, json, csv, time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# v14: load .env first so LABEL_MODE / TB_* / PURGED_CV / CALIBRATE_PROBA
# and SYMBOLS/TIMEFRAMES are visible during training.
try:
    from dotenv import load_dotenv
    _ENV = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=str(_ENV) if _ENV.exists() else None, override=True)
except Exception:
    pass


def active_pairs() -> list[str]:
    """The ONE manual source of truth for pairs: SYMBOLS in .env."""
    raw = os.getenv("SYMBOLS", "BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def active_tfs() -> list[str]:
    raw = os.getenv("TIMEFRAMES", "15m")
    return [t.strip() for t in raw.split(",") if t.strip()]


def wanted_stems() -> set[str]:
    """OHLCV file stems we actually train on, e.g. {'BNBUSDT_15m', 'XAUUSDT_15m'}."""
    return {f"{s}_{tf}" for s in active_pairs() for tf in active_tfs()}


def pip_install(packages):
    print(f"\n[1/4] Installing libraries: {', '.join(packages)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet"] + packages
    )
    print("  Libraries OK")


def check_imports():
    missing = []
    for pkg, imp in [("lightgbm","lightgbm"),("scikit-learn","sklearn"),
                     ("joblib","joblib"),("pandas","pandas"),("numpy","numpy")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        pip_install(missing)


def download_data(out_dir: Path):
    """Ensure OHLCV data exists for EXACTLY the active pairs (SYMBOLS x TIMEFRAMES).
    Uses existing CSVs (e.g. deep history from fetch_history.py) when present,
    and quick-downloads only the missing active pairs."""
    print("\n[2/4] Checking historical data...")
    out_dir.mkdir(exist_ok=True)

    pairs = active_pairs()
    tfs   = active_tfs()
    base  = "https://fapi.binance.com"
    files = []
    missing = []

    for pair in pairs:
        for tf in tfs:
            path = out_dir / f"{pair}_{tf}.csv"
            if path.exists():
                files.append(path)
                print(f"  Using existing: {path.name}")
            else:
                missing.append((pair, tf, path))

    if missing:
        print(f"  Quick-downloading {len(missing)} missing pair(s) (max 1500 candles each)...")
        for pair, tf, path in missing:
            url = f"{base}/fapi/v1/klines?symbol={pair}&interval={tf}&limit=1500"
            try:
                print(f"  {pair} {tf} ... ", end="", flush=True)
                with urlopen(url, timeout=15) as r:
                    data = json.loads(r.read())
                with open(path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["timestamp","open","high","low","close","volume"])
                    for k in data:
                        w.writerow([k[0],k[1],k[2],k[3],k[4],k[5]])
                print(f"{len(data)} candles OK")
                files.append(path)
                time.sleep(0.3)
            except URLError as e:
                print(f"FAILED ({e}) - check internet connection")
            except Exception as e:
                print(f"FAILED: {e}")
    else:
        print("  All active pairs already have data (deep history preserved).")

    print(f"  Total OHLCV files for active pairs: {len(files)}")
    return files


def run_training(data_dir: Path, out_dir: Path):
    print("\n[3/4] Training ML model (walk-forward, ~5-10 minutes)...")
    # Import after making sure libraries are installed
    import warnings; warnings.filterwarnings("ignore")
    import pandas as pd
    import numpy as np
    from bot.features import create_scalping_features, FEATURE_COLS
    from bot.train    import train_pipeline

    wanted = wanted_stems()

    parts = []
    for csv_path in sorted(data_dir.glob("*.csv")):
        pair_name = csv_path.stem  # e.g. SOLUSDT_15m
        # SINGLE SOURCE OF TRUTH: only train pairs listed in SYMBOLS x TIMEFRAMES.
        # This skips stale coins AND auxiliary files (_funding/_oi/_lsr/_taker).
        if pair_name not in wanted:
            continue
        try:
            df   = pd.read_csv(csv_path)
            feat = create_scalping_features(df, pair=pair_name)
            parts.append(feat)
            print(f"  {pair_name}: {len(feat)} feature rows")
        except Exception as e:
            print(f"  WARN {pair_name}: {e}")

    if not parts:
        print("  ERROR: no data matched the active pairs (SYMBOLS x TIMEFRAMES).")
        print(f"  Expected files like: {', '.join(sorted(wanted))}")
        print("  Run: python3 fetch_history.py   (or check your SYMBOLS in .env)")
        return

    combined = pd.concat(parts, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    label_dist = combined["label"].value_counts().to_dict()
    print(f"  Dataset: {len(combined)} rows | label: {label_dist}")
    train_pipeline(combined, out_dir)


def show_results(out_dir: Path):
    print("\n[4/4] Training results:")
    csv_path = out_dir / "evaluation.csv"
    if not csv_path.exists():
        print("  evaluation.csv not found")
        return
    import csv as csvmod
    with open(csv_path) as f:
        rows = list(csvmod.DictReader(f))
    print(f"  {'PAIR':<20} {'FOLD':<6} {'WINRATE':<10} {'PROFIT FACTOR':<15} {'TRADES':<8}")
    print("  " + "-"*60)
    for r in rows:
        wr  = float(r.get("winrate",0))
        pf  = float(r.get("profit_factor",0))
        flag = " OK" if wr >= 0.55 else " !!"
        print(f"  {r.get('pair','?'):<20} {r.get('fold','?'):<6} {wr:<10.3f} {pf:<15.3f} {r.get('n_trades','?'):<8}{flag}")
    models = list(out_dir.glob("*.pkl"))
    print(f"\n  Models saved: {len(models)} file(s)")
    for m in models:
        print(f"    {m.name}")


if __name__ == "__main__":
    print("="*55)
    print("  PRO SCALPER v14  —  Automatic Setup & Training")
    print("="*55)

    DATA_DIR  = Path("data_historis")
    MODEL_DIR = Path("models")

    print(f"\nActive pairs (from .env SYMBOLS): {', '.join(active_pairs())}")
    print(f"Timeframe(s) (from .env TIMEFRAMES): {', '.join(active_tfs())}")
    print("Only these pairs will be trained. Everything else in the folder is ignored.")

    # Step 1: Libraries
    check_imports()

    # Step 2: Data
    files = download_data(DATA_DIR)
    if not files:
        print("\n[ERROR] No data available for the active pairs. Check internet / SYMBOLS.")
        sys.exit(1)

    # Step 3: Training
    run_training(DATA_DIR, MODEL_DIR)

    # Step 4: Results
    show_results(MODEL_DIR)

    print("\n" + "="*55)
    print("  DONE! Start the bot with:")
    print("  python3 -m bot.main")
    print("="*55)
