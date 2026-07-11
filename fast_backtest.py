#!/usr/bin/env python3
"""
fast_backtest.py  —  Fast vectorized backtester for the v14 scalper

What it does
------------
1. Reads the pair list + timeframe from .env (SYMBOLS / TIMEFRAMES) -> FULLY MANUAL.
   No auto-detect / no folder auto-scan. CLI flags can override for one run only.
2. Loads historical CSVs from data_historis/{SYMBOL}_{TF}.csv (OHLCV).
3. Builds features with the SAME create_scalping_features() used in training/live.
4. Loads the trained model bundle (lgbm_<short>.pkl, or the combined model as
   fallback) exactly like the live MLSignalEngine, then predicts probabilities
   in ONE batch per pair (that's why it's fast).
5. Reproduces the LIVE entry logic: ensemble (LightGBM + RandomForest) average
   probability, EMA-distance filter, volume filter, probability threshold.
6. Simulates each trade forward bar-by-bar with the SAME exit logic as the
   triple-barrier label (ATR-based TP/SL + horizon timeout), or fixed-% TP/SL.
7. Applies leverage, per-trade margin %, and round-trip fee, then prints a full
   performance report (winrate, profit factor, expectancy, max drawdown, etc.)
   plus an optional Monte Carlo robustness check.

Usage
-----
  python3 fast_backtest.py                      # use .env SYMBOLS/TIMEFRAMES
  python3 fast_backtest.py --symbols BNBUSDT,SOLUSDT --tf 15m
  python3 fast_backtest.py --proba 0.66 --montecarlo
  python3 fast_backtest.py --exit-mode fixed --tp 0.016 --sl 0.008
  python3 fast_backtest.py --journal-out logs/backtest_trades.csv

Everything is read-only against your data + models. Nothing is auto-adjusted.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# --- Project imports (features.py loads .env on import, so os.getenv works) ---
from bot.features import (
    create_scalping_features,
    FEATURE_COLS,
    TB_HORIZON,
    TB_TP_MULT,
    TB_SL_MULT,
)
from bot.ml_signal import (
    MLSignalEngine,
    PROBA_THRESHOLD as LIVE_PROBA_THRESHOLD,
    EMA_DIST_MIN as LIVE_EMA_DIST_MIN,
    VOL_MULT_MIN as LIVE_VOL_MULT_MIN,
)

ROOT = Path(__file__).resolve().parent


# ── .env helpers (manual, single source of truth) ────────────────────────────

def _clean_val(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        v = v[1:-1]
    # strip trailing inline comment
    if "#" in v:
        v = v.split("#", 1)[0].strip()
    return v


def _env(key: str, default: str = "") -> str:
    if key in os.environ and os.environ[key] != "":
        return _clean_val(os.environ[key])
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, val = line.split("=", 1)
            if k.strip() == key:
                return _clean_val(val)
    return default


def _env_symbols() -> list[str]:
    raw = _env("SYMBOLS", "BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _env_tf() -> str:
    raw = _env("TIMEFRAMES", "15m")
    # If multiple TFs are listed, backtest uses the first one.
    return raw.split(",")[0].strip()


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except (TypeError, ValueError):
        return default


# ── Data loading ──────────────────────────────────────────────────────────────

def load_ohlcv(symbol: str, tf: str, data_dir: Path) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol}_{tf}.csv"
    if not path.exists():
        print(f"  [SKIP] {symbol}: file not found -> {path}")
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"  [SKIP] {symbol}: read error -> {e}")
        return None
    df.columns = [c.lower() for c in df.columns]
    need = ["timestamp", "open", "high", "low", "close", "volume"]
    if not all(c in df.columns for c in need):
        print(f"  [SKIP] {symbol}: missing columns, need {need}, got {list(df.columns)}")
        return None
    df = df[need].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    if len(df) < 120:
        print(f"  [SKIP] {symbol}: too few rows ({len(df)})")
        return None
    return df


# ── Trade + result containers ────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: int          # +1 long, -1 short
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    bars_held: int
    outcome: str            # "TP" | "SL" | "TIMEOUT"
    gross_ret: float        # price move fraction * direction
    pnl_usdt: float         # net after fee, on account
    proba: float


@dataclass
class BacktestConfig:
    proba_threshold: float
    ema_dist_min: float
    vol_mult_min: float
    use_filters: bool
    exit_mode: str          # "atr" | "fixed"
    horizon: int
    tp_mult: float
    sl_mult: float
    tp_pct: float
    sl_pct: float
    fee_pct: float
    leverage: float
    entry_margin_pct: float
    start_balance: float
    cooldown_bars: int
    allow_long: bool = True
    allow_short: bool = True


# ── Core: backtest one symbol ────────────────────────────────────────────────

def backtest_symbol(symbol: str, df: pd.DataFrame, bundle: dict,
                    cfg: BacktestConfig, balance_ref: list) -> list[Trade]:
    """Vectorized signal generation + bar-by-bar exit simulation.
    balance_ref is a 1-element list so balance compounds across all symbols
    in the order they are processed."""
    # 1) Features for the whole series (single pass)
    try:
        feat = create_scalping_features(df, pair=symbol)
    except Exception as e:
        print(f"  [SKIP] {symbol}: feature error -> {e}")
        return []
    if feat.empty:
        return []

    feat_cols = bundle.get("feature_cols", FEATURE_COLS)
    missing = [c for c in feat_cols if c not in feat.columns]
    if missing:
        print(f"  [SKIP] {symbol}: missing features {missing}")
        return []

    X = feat[feat_cols].fillna(0).to_numpy()

    # 2) Batch probability prediction (ensemble like live)
    model = bundle["model"]
    le = bundle["label_encoder"]
    classes = list(le.classes_)
    idx_long = next((i for i, c in enumerate(classes) if float(c) == 1.0), None)
    idx_short = next((i for i, c in enumerate(classes) if float(c) == -1.0), None)

    proba = model.predict_proba(X)
    prob_long = proba[:, idx_long] if idx_long is not None else np.zeros(len(X))
    prob_short = proba[:, idx_short] if idx_short is not None else np.zeros(len(X))

    rf_model = bundle.get("rf_model")
    if rf_model is not None:
        rf_proba = rf_model.predict_proba(X)
        rf_long = rf_proba[:, idx_long] if idx_long is not None else np.zeros(len(X))
        rf_short = rf_proba[:, idx_short] if idx_short is not None else np.zeros(len(X))
        prob_long = (prob_long + rf_long) / 2.0
        prob_short = (prob_short + rf_short) / 2.0

    # 3) Live-style filters
    ema_dist = feat["ema_dist_pct"].abs().to_numpy()
    vol_ratio = feat["vol_ratio"].to_numpy()
    atr_pct = feat["atr_pct"].to_numpy()
    if cfg.use_filters:
        filt = (ema_dist > cfg.ema_dist_min) & (vol_ratio > cfg.vol_mult_min)
    else:
        filt = np.ones(len(X), dtype=bool)

    long_sig = (prob_long > cfg.proba_threshold) & filt & cfg.allow_long
    short_sig = (prob_short > cfg.proba_threshold) & filt & cfg.allow_short

    # 4) Map feature rows back to raw OHLC positions (by timestamp)
    ts_to_pos = {ts: i for i, ts in enumerate(df["timestamp"].to_numpy())}
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    ts_arr = df["timestamp"].to_numpy()
    n = len(close)

    feat_ts = feat["timestamp"].to_numpy()
    trades: list[Trade] = []
    cooldown_until_pos = -1

    for k in range(len(feat)):
        if not (long_sig[k] or short_sig[k]):
            continue
        pos = ts_to_pos.get(feat_ts[k])
        if pos is None or pos <= cooldown_until_pos:
            continue
        direction = 1 if long_sig[k] else -1
        conf = float(prob_long[k] if direction == 1 else prob_short[k])

        entry_price = close[pos]
        atr = atr_pct[k] * entry_price
        if not np.isfinite(atr) or atr <= 0:
            continue

        # Barriers
        if cfg.exit_mode == "fixed":
            tp = entry_price * (1 + cfg.tp_pct * direction)
            sl = entry_price * (1 - cfg.sl_pct * direction)
        else:  # atr (matches triple-barrier label)
            tp = entry_price + cfg.tp_mult * atr * direction
            sl = entry_price - cfg.sl_mult * atr * direction

        # Walk forward
        exit_pos = min(pos + cfg.horizon, n - 1)
        outcome = "TIMEOUT"
        exit_price = close[exit_pos]
        for j in range(pos + 1, min(pos + cfg.horizon, n - 1) + 1):
            if direction == 1:
                hit_tp = high[j] >= tp
                hit_sl = low[j] <= sl
            else:
                hit_tp = low[j] <= tp
                hit_sl = high[j] >= sl
            if hit_tp and hit_sl:
                # Both in same bar -> conservative: assume SL first (matches label)
                outcome, exit_price, exit_pos = "SL", sl, j
                break
            if hit_tp:
                outcome, exit_price, exit_pos = "TP", tp, j
                break
            if hit_sl:
                outcome, exit_price, exit_pos = "SL", sl, j
                break

        gross_ret = (exit_price - entry_price) / entry_price * direction

        # Account math (futures): notional = margin * leverage
        margin = cfg.entry_margin_pct * balance_ref[0]
        notional = margin * cfg.leverage
        pnl_gross = notional * gross_ret
        fee = notional * cfg.fee_pct           # round-trip fee on notional
        pnl_usdt = pnl_gross - fee
        balance_ref[0] += pnl_usdt

        trades.append(Trade(
            symbol=symbol, direction=direction,
            entry_ts=pd.Timestamp(ts_arr[pos]), exit_ts=pd.Timestamp(ts_arr[exit_pos]),
            entry_price=entry_price, exit_price=exit_price,
            bars_held=exit_pos - pos, outcome=outcome,
            gross_ret=gross_ret, pnl_usdt=pnl_usdt, proba=conf,
        ))

        # Cooldown: no new entry until this many bars after the exit
        cooldown_until_pos = exit_pos + cfg.cooldown_bars

    return trades


# ── Reporting ─────────────────────────────────────────────────────────────────

def _equity_max_drawdown(pnls: list[float], start_balance: float) -> tuple[float, float]:
    """Return (max_dd_usdt, max_dd_pct) from the equity curve."""
    bal = start_balance
    peak = start_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for p in pnls:
        bal += p
        peak = max(peak, bal)
        dd = peak - bal
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak * 100 if peak > 0 else 0.0
    return round(max_dd, 2), round(max_dd_pct, 2)


def format_report(trades: list[Trade], cfg: BacktestConfig, final_balance: float) -> str:
    if not trades:
        return "No trades were generated with the current settings (try lowering --proba or check your data/models)."

    pnls = [t.pnl_usdt for t in trades]
    wins = [t for t in trades if t.pnl_usdt > 0]
    losses = [t for t in trades if t.pnl_usdt <= 0]
    n = len(trades)
    winrate = len(wins) / n * 100

    gross_profit = sum(t.pnl_usdt for t in wins)
    gross_loss = -sum(t.pnl_usdt for t in losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    expectancy = sum(pnls) / n
    total_pnl = sum(pnls)
    ret_pct = (final_balance - cfg.start_balance) / cfg.start_balance * 100
    avg_bars = sum(t.bars_held for t in trades) / n
    max_dd, max_dd_pct = _equity_max_drawdown(pnls, cfg.start_balance)

    n_tp = sum(1 for t in trades if t.outcome == "TP")
    n_sl = sum(1 for t in trades if t.outcome == "SL")
    n_to = sum(1 for t in trades if t.outcome == "TIMEOUT")
    n_long = sum(1 for t in trades if t.direction == 1)
    n_short = n - n_long

    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    lines = [
        "=" * 56,
        "\U0001F9EA FAST BACKTEST REPORT",
        "=" * 56,
        f"Trades           : {n}  (long {n_long} / short {n_short})",
        f"Outcomes         : TP {n_tp} | SL {n_sl} | Timeout {n_to}",
        f"Win rate         : {winrate:.2f}%",
        f"Profit factor    : {pf_str}",
        f"Expectancy/trade : {expectancy:+.4f} USDT",
        f"Avg win / loss   : +{avg_win:.4f} / -{avg_loss:.4f} USDT",
        f"Avg bars held    : {avg_bars:.1f}",
        f"Total PnL        : {total_pnl:+.2f} USDT",
        f"Start balance    : {cfg.start_balance:.2f} USDT",
        f"Final balance    : {final_balance:.2f} USDT  ({ret_pct:+.2f}%)",
        f"Max drawdown     : {max_dd:.2f} USDT ({max_dd_pct:.2f}%)",
    ]

    # Per-symbol breakdown
    by_sym: dict[str, list[Trade]] = {}
    for t in trades:
        by_sym.setdefault(t.symbol, []).append(t)
    lines.append("-" * 56)
    lines.append("Per-symbol:")
    for sym, ts in by_sym.items():
        w = sum(1 for x in ts if x.pnl_usdt > 0)
        gp = sum(x.pnl_usdt for x in ts if x.pnl_usdt > 0)
        gl = -sum(x.pnl_usdt for x in ts if x.pnl_usdt <= 0)
        spf = (gp / gl) if gl > 0 else float("inf")
        spf_str = "inf" if spf == float("inf") else f"{spf:.2f}"
        wr = w / len(ts) * 100
        pnl_sym = sum(x.pnl_usdt for x in ts)
        lines.append(f"  {sym:<10} trades {len(ts):>4} | WR {wr:5.1f}% | PF {spf_str:>5} | PnL {pnl_sym:+.2f}")

    # Verdict
    lines.append("-" * 56)
    if n < 30:
        lines.append("Verdict          : \u26A0\uFE0F sample < 30 trades, not statistically significant yet")
    elif pf == float("inf") or pf >= 1.5:
        lines.append("Verdict          : \u2705 strong edge (PF >= 1.5) on this dataset")
    elif pf >= 1.2:
        lines.append("Verdict          : \u2705 positive edge (PF >= 1.2) \u2014 OK to consider live at small size")
    elif pf >= 1.0:
        lines.append("Verdict          : \u26A0\uFE0F thin edge (PF 1.0\u20131.2) \u2014 fragile after fees/slippage, keep DRY_RUN")
    else:
        lines.append("Verdict          : \u274C negative edge (PF < 1.0) \u2014 do NOT go live, keep DRY_RUN=true")
    lines.append("=" * 56)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Fast vectorized backtester for the v14 scalper")
    ap.add_argument("--symbols", type=str, default=None,
                    help="Comma-separated symbols (default: SYMBOLS in .env)")
    ap.add_argument("--tf", type=str, default=None,
                    help="Timeframe (default: first of TIMEFRAMES in .env)")
    ap.add_argument("--data-dir", type=str, default="data_historis")
    ap.add_argument("--models-dir", type=str, default="models")
    ap.add_argument("--proba", type=float, default=None,
                    help="Entry probability threshold (default: ML_PROBA_THRESHOLD in .env, else live default)")
    ap.add_argument("--exit-mode", choices=["atr", "fixed"], default="atr",
                    help="'atr' matches the triple-barrier label (default), 'fixed' uses --tp/--sl percent")
    ap.add_argument("--tp", type=float, default=0.016, help="Fixed TP fraction (exit-mode=fixed)")
    ap.add_argument("--sl", type=float, default=0.008, help="Fixed SL fraction (exit-mode=fixed)")
    ap.add_argument("--horizon", type=int, default=None, help="Max bars to hold (default: TB_HORIZON)")
    ap.add_argument("--fee", type=float, default=0.001, help="Round-trip fee fraction on notional (default 0.001)")
    ap.add_argument("--leverage", type=float, default=None, help="Leverage (default: LEVERAGE in .env)")
    ap.add_argument("--entry-margin", type=float, default=None,
                    help="Margin fraction of balance per trade (default: ENTRY_MARGIN_PCT in .env)")
    ap.add_argument("--start-balance", type=float, default=100.0)
    ap.add_argument("--cooldown-bars", type=int, default=0, help="Bars to wait after a trade exits")
    ap.add_argument("--no-filters", action="store_true", help="Disable EMA-distance/volume filters")
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--short-only", action="store_true")
    ap.add_argument("--journal-out", type=str, default=None, help="Write per-trade CSV to this path")
    ap.add_argument("--montecarlo", action="store_true", help="Run Monte Carlo robustness on the resulting PnLs")
    args = ap.parse_args()

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else _env_symbols())
    tf = args.tf or _env_tf()
    data_dir = (ROOT / args.data_dir) if not os.path.isabs(args.data_dir) else Path(args.data_dir)
    models_dir = (ROOT / args.models_dir) if not os.path.isabs(args.models_dir) else Path(args.models_dir)

    proba = args.proba if args.proba is not None else _env_float("ML_PROBA_THRESHOLD", LIVE_PROBA_THRESHOLD)
    leverage = args.leverage if args.leverage is not None else _env_float("LEVERAGE", 10.0)
    entry_margin = args.entry_margin if args.entry_margin is not None else _env_float("ENTRY_MARGIN_PCT", 0.10)
    horizon = args.horizon if args.horizon is not None else TB_HORIZON

    cfg = BacktestConfig(
        proba_threshold=proba,
        ema_dist_min=LIVE_EMA_DIST_MIN,
        vol_mult_min=LIVE_VOL_MULT_MIN,
        use_filters=not args.no_filters,
        exit_mode=args.exit_mode,
        horizon=horizon,
        tp_mult=TB_TP_MULT,
        sl_mult=TB_SL_MULT,
        tp_pct=args.tp,
        sl_pct=args.sl,
        fee_pct=args.fee,
        leverage=leverage,
        entry_margin_pct=entry_margin,
        start_balance=args.start_balance,
        cooldown_bars=args.cooldown_bars,
        allow_long=not args.short_only,
        allow_short=not args.long_only,
    )

    print("Fast backtest config")
    print(f"  symbols       : {', '.join(symbols)}")
    print(f"  timeframe     : {tf}")
    print(f"  data dir      : {data_dir}")
    print(f"  models dir    : {models_dir}")
    print(f"  proba thresh  : {cfg.proba_threshold}")
    print(f"  exit mode     : {cfg.exit_mode} (horizon={cfg.horizon}, tp_mult={cfg.tp_mult}, sl_mult={cfg.sl_mult}, tp={cfg.tp_pct}, sl={cfg.sl_pct})")
    print(f"  leverage      : {cfg.leverage}x | margin/trade {cfg.entry_margin_pct*100:.1f}% | fee {cfg.fee_pct*100:.3f}%")
    print(f"  filters       : {'ON' if cfg.use_filters else 'OFF'} (ema_dist>{cfg.ema_dist_min}, vol_ratio>{cfg.vol_mult_min})")
    print(f"  direction     : long={cfg.allow_long} short={cfg.allow_short} | cooldown={cfg.cooldown_bars} bars")
    print("-" * 56)

    if not models_dir.exists():
        sys.exit(f"Models dir not found: {models_dir}. Train first (python setup_and_train.py).")
    engine = MLSignalEngine(models_dir)
    if not engine.is_ready():
        sys.exit("No models loaded. Train first (python setup_and_train.py).")

    all_trades: list[Trade] = []
    balance_ref = [cfg.start_balance]
    for sym in symbols:
        df = load_ohlcv(sym, tf, data_dir)
        if df is None:
            continue
        bundle = engine._get_bundle(sym)
        if bundle is None:
            print(f"  [SKIP] {sym}: no model bundle available")
            continue
        t = backtest_symbol(sym, df, bundle, cfg, balance_ref)
        print(f"  {sym}: {len(t)} trades simulated")
        all_trades.extend(t)

    print()
    print(format_report(all_trades, cfg, balance_ref[0]))

    # Optional per-trade journal
    if args.journal_out and all_trades:
        out = (ROOT / args.journal_out) if not os.path.isabs(args.journal_out) else Path(args.journal_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([t.__dict__ for t in all_trades]).to_csv(out, index=False)
        print(f"\nPer-trade journal written -> {out}")

    # Optional Monte Carlo robustness
    if args.montecarlo and all_trades:
        try:
            from tools.monte_carlo import run_monte_carlo, format_report as mc_report
            pnls = [t.pnl_usdt for t in all_trades]
            res = run_monte_carlo(pnls, runs=5000, start_balance=cfg.start_balance)
            print()
            print(mc_report(res))
        except Exception as e:
            print(f"\n[Monte Carlo] skipped: {e}")


if __name__ == "__main__":
    main()
