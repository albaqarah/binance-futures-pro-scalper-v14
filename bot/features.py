"""
features.py  — Feature Engineering + Label untuk LightGBM
TANPA pandas_ta — pakai pure pandas/numpy (support Python 3.14+)
Pair  : BNBUSDT, SOLUSDT, DOGEUSDT, XRPUSDT
TF    : 3m / 5m
Aturan: ZERO lookahead bias
"""
from __future__ import annotations
import os
import pandas as pd
import numpy as np

# v14: muat .env supaya LABEL_MODE / TB_* kebaca apa pun jalur import-nya
# (train.py & setup_and_train.py tidak mengimpor config, jadi .env dimuat di sini).
try:
    from dotenv import load_dotenv as _load_dotenv
    from pathlib import Path as _P
    _EP = _P(__file__).resolve().parent.parent / ".env"
    _load_dotenv(dotenv_path=str(_EP) if _EP.exists() else None, override=True)
except Exception:
    pass


def _label_f(name, default):
    raw = os.getenv(name)
    try:
        return float(raw) if raw not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _label_i(name, default):
    raw = os.getenv(name)
    try:
        return int(float(raw)) if raw not in (None, "") else int(default)
    except (TypeError, ValueError):
        return int(default)


# ── Konfigurasi label via .env (default v14: triple-barrier, tuned utk 15m) ──
LABEL_MODE      = os.getenv("LABEL_MODE", "triple_barrier").strip().lower()
TB_HORIZON      = _label_i("TB_HORIZON", 16)    # 16 bar @15m = 4 jam, cukup utk TP kena
TB_TP_MULT      = _label_f("TB_TP_MULT", 1.2)   # TP lebih realistis -> label menang seimbang
TB_SL_MULT      = _label_f("TB_SL_MULT", 1.0)
FIXED_HORIZON   = _label_i("LABEL_HORIZON", 8)
FIXED_THRESHOLD = _label_f("LABEL_THRESHOLD", 0.008)

FEATURE_COLS = [
    "ema12", "ema26", "ema_dist_pct",
    "rsi14", "rsi_delta",
    "atr14", "atr_pct",
    "vol_ratio",
    "candle_pos",
    "ret_1", "ret_3", "ret_5",
    "ema26_dist_pct",
    "bb_pos",
]


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"]  - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _bbands(close: pd.Series, period: int = 20, std: float = 2.0):
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    return mid + std * sigma, mid, mid - std * sigma  # upper, mid, lower


def triple_barrier_label(close: pd.Series, high: pd.Series, low: pd.Series,
                         atr: pd.Series, horizon: int = 8,
                         tp_mult: float = 1.5, sl_mult: float = 1.0) -> pd.Series:
    """Triple-Barrier Labeling (Lopez de Prado, B5).

    Untuk tiap bar i: barrier atas = close[i] + tp_mult*ATR[i],
    barrier bawah = close[i] - sl_mult*ATR[i], barrier vertikal = i+horizon.
    Label = +1 kalau barrier ATAS tersentuh duluan (high), -1 kalau barrier
    BAWAH duluan (low), 0 kalau timeout (sentuh vertikal tanpa barrier).
    ZERO lookahead: hanya melihat bar i+1..i+horizon. Bar terakhir = NaN.
    """
    c = close.to_numpy(dtype=float)
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    a = atr.to_numpy(dtype=float)
    n = len(c)
    out = np.full(n, np.nan)
    for i in range(n):
        if i + horizon >= n or not np.isfinite(a[i]) or a[i] <= 0:
            continue
        up = c[i] + tp_mult * a[i]
        dn = c[i] - sl_mult * a[i]
        label = 0
        for j in range(i + 1, i + horizon + 1):
            hit_up = h[j] >= up
            hit_dn = l[j] <= dn
            if hit_up and hit_dn:
                # Dua barrier kena di candle sama -> ambil yang lebih konservatif (SL).
                label = -1
                break
            if hit_up:
                label = 1
                break
            if hit_dn:
                label = -1
                break
        out[i] = label
    return pd.Series(out, index=close.index)


def create_scalping_features(df: pd.DataFrame, pair: str = "UNKNOWN",
                             label_mode: str | None = None, tb_horizon: int | None = None,
                             tb_tp_mult: float | None = None, tb_sl_mult: float | None = None) -> pd.DataFrame:
    """
    Input : DataFrame [timestamp, open, high, low, close, volume] minimal 60 baris
    Output: DataFrame fitur + label + timestamp + pair (tanpa OHLCV)
    ZERO lookahead bias — label pakai shift(-8), baris terakhir label=NaN

    label_mode:
      "fixed"         -> label lama (return 8 candle ke depan, threshold +/-0.8%)
      "triple_barrier" -> Triple-Barrier ATR-based (B5)
    """
    # v14: default label diambil dari .env (LABEL_MODE/TB_*) kalau caller tidak set eksplisit
    label_mode = (label_mode or LABEL_MODE)
    tb_horizon = TB_HORIZON if tb_horizon is None else tb_horizon
    tb_tp_mult = TB_TP_MULT if tb_tp_mult is None else tb_tp_mult
    tb_sl_mult = TB_SL_MULT if tb_sl_mult is None else tb_sl_mult

    df = df.copy().reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    close = df["close"]

    # EMA 12 & 26
    df["ema12"] = _ema(close, 12)
    df["ema26"] = _ema(close, 26)
    df["ema_dist_pct"] = (df["ema12"] - df["ema26"]) / df["ema26"]

    # RSI 14
    df["rsi14"]   = _rsi(close, 14)
    df["rsi_delta"] = df["rsi14"] - df["rsi14"].shift(1)

    # ATR 14
    df["atr14"]  = _atr(df, 14)
    df["atr_pct"] = df["atr14"] / close

    # Volume ratio (vol / SMA vol 20)
    vol_sma       = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / vol_sma.replace(0, np.nan)

    # Posisi close dalam candle: (close-low)/(high-low)
    hl_range        = (df["high"] - df["low"]).replace(0, np.nan)
    df["candle_pos"] = (close - df["low"]) / hl_range

    # Return 1, 3, 5 candle lalu
    df["ret_1"] = close.pct_change(1)
    df["ret_3"] = close.pct_change(3)
    df["ret_5"] = close.pct_change(5)

    # Jarak harga ke EMA26
    df["ema26_dist_pct"] = (close - df["ema26"]) / df["ema26"]

    # Bollinger Bands 20,2 — posisi harga dalam band [0,1]
    bb_upper, _, bb_lower = _bbands(close, 20, 2.0)
    bb_width          = (bb_upper - bb_lower).replace(0, np.nan)
    df["bb_pos"]       = (close - bb_lower) / bb_width

    # Label
    if label_mode == "triple_barrier":
        df["label"] = triple_barrier_label(
            close, df["high"], df["low"], df["atr14"],
            horizon=tb_horizon, tp_mult=tb_tp_mult, sl_mult=tb_sl_mult,
        )
    else:
        # Fixed-horizon return (configurable via .env: LABEL_HORIZON / LABEL_THRESHOLD)
        _h = FIXED_HORIZON
        future_ret  = close.shift(-_h) / close - 1
        df["label"]  = 0
        df.loc[future_ret >  FIXED_THRESHOLD, "label"] =  1
        df.loc[future_ret < -FIXED_THRESHOLD, "label"] = -1
        df.loc[df.index[-_h:], "label"]       = np.nan

    df["pair"] = pair

    keep    = ["timestamp"] + FEATURE_COLS + ["label", "pair"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom hilang: {missing}")

    return df[keep].copy().dropna().reset_index(drop=True)


def build_combined_dataset(df_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Input : {"BNBUSDT": df_bnb, "SOLUSDT": df_sol, ...}
    Output: DataFrame gabungan 4 pair, siap training
    """
    parts = []
    for pair, df in df_dict.items():
        try:
            feat = create_scalping_features(df, pair=pair)
            parts.append(feat)
            print(f"  {pair}: {len(feat)} baris fitur")
        except Exception as e:
            print(f"  WARN {pair}: {e}")
    combined = pd.concat(parts, ignore_index=True)
    return combined.sort_values("timestamp").reset_index(drop=True)


if __name__ == "__main__":
    n = 300
    np.random.seed(42)
    px = 100 + np.cumsum(np.random.randn(n) * 0.1)
    dummy = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
        "open":   px - 0.05,
        "high":   px + 0.15,
        "low":    px - 0.15,
        "close":  px,
        "volume": np.random.randint(500, 2000, n).astype(float),
    })
    out = create_scalping_features(dummy, pair="TEST")
    print(out.tail())
    print("Distribusi label:", out["label"].value_counts().to_dict())
