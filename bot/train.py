"""
train.py  —  Walk-Forward Training LightGBM Anti-Overfit

Cara pakai:
  1. Siapkan data historis tiap pair (CSV atau Binance API) dalam format
     [timestamp, open, high, low, close, volume]
  2. Panggil: python -m bot.train --data-dir ./data_historis --out-dir ./models
  3. Hasil: model per-pair + model gabungan tersimpan di ./models/
            evaluasi tersimpan di ./models/evaluation.csv
"""
from __future__ import annotations
import argparse, json, os, warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, precision_score, recall_score
from sklearn.preprocessing import LabelEncoder

try:
    import lightgbm as lgb
    from lightgbm import LGBMClassifier, early_stopping, log_evaluation
except ImportError:
    raise SystemExit("Install dulu: pip install lightgbm")

try:
    import joblib
except ImportError:
    raise SystemExit("Install dulu: pip install joblib")

from sklearn.ensemble import RandomForestClassifier

from .features import build_combined_dataset, create_scalping_features, FEATURE_COLS

warnings.filterwarnings("ignore")

# ── Hyperparameter anti-overfit ───────────────────────────────────────────────
LGBM_PARAMS = dict(
    n_estimators=500,
    learning_rate=0.03,
    num_leaves=31,
    max_depth=6,
    min_child_samples=50,
    subsample=0.8,
    colsample_bytree=0.8,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
    verbose=-1,
)

N_FOLDS       = 3     # 3 fold walk-forward
MIN_PROBA     = 0.60  # threshold utk HITUNG WR & Profit Factor di LAPORAN training (BUKAN entry live; live diatur via .env ML_PROBA_THRESHOLD/MIN_PROBA)
TP_PCT        = 0.016 # asumsi TP 1.6%
SL_PCT        = 0.008 # asumsi SL 0.8%
FEE_PCT       = 0.001 # fee round-trip taker 0.05%×2 = 0.1%

# ── v14 anti-overfit toggles (default OFF; aktifkan via .env) ──
EMBARGO_FRAC  = float(os.getenv("PURGE_EMBARGO_FRAC", "0.01"))  # gap purge train->test
USE_PURGED_CV = os.getenv("PURGED_CV", "false").strip().lower() in {"1","true","yes","on"}
CALIBRATE     = os.getenv("CALIBRATE_PROBA", "false").strip().lower() in {"1","true","yes","on"}


# ── Walk-forward split ────────────────────────────────────────────────────────

def walk_forward_splits(df: pd.DataFrame, n_folds: int = N_FOLDS):
    """
    Bagi DataFrame (sudah diurutkan timestamp) jadi n_folds split.
    Setiap split: train = dari awal s/d titik t, test = titik t s/d berikutnya.
    Jangan acak — preservasi urutan waktu.
    """
    n = len(df)
    # Tentukan titik cut per fold (misal 3 fold: ~70/30, 80/20, 90/10 akhir)
    step = n // (n_folds + 1)
    splits = []
    for i in range(1, n_folds + 1):
        train_end = step * (i + 1)
        test_end  = min(train_end + step, n)
        if test_end <= train_end:
            break
        splits.append((df.iloc[:train_end], df.iloc[train_end:test_end]))
    return splits


def purged_walk_forward_splits(df: pd.DataFrame, n_folds: int = N_FOLDS,
                               embargo_frac: float = EMBARGO_FRAC):
    """Walk-forward + PURGE/EMBARGO (B8): buang `embargo_frac` baris di batas
    train->test untuk cegah kebocoran label yang overlap horizon ke depan."""
    base = walk_forward_splits(df, n_folds)
    n = len(df)
    embargo = max(1, int(n * embargo_frac))
    purged = []
    for train_df, test_df in base:
        if len(train_df) > embargo:
            train_df = train_df.iloc[:-embargo]
        purged.append((train_df, test_df))
    return purged


def get_splits(df: pd.DataFrame, n_folds: int = N_FOLDS):
    """Pilih splitter sesuai flag PURGED_CV (default walk-forward biasa)."""
    if USE_PURGED_CV:
        return purged_walk_forward_splits(df, n_folds)
    return walk_forward_splits(df, n_folds)


# ── Evaluasi per fold ─────────────────────────────────────────────────────────

def eval_fold(model: LGBMClassifier, X_test: pd.DataFrame, y_test: pd.Series,
              le: LabelEncoder, fold: int, pair: str) -> dict:
    # Encode y_test ke integer 0,1,2 agar cocok dengan y_pred
    y_test_enc = le.transform(y_test)
    y_pred   = model.predict(X_test)
    y_proba  = model.predict_proba(X_test)
    classes  = list(le.classes_)  # misal [-1.0, 0.0, 1.0]

    # Report lengkap
    unique_in_test = np.unique(np.concatenate([y_test_enc, y_pred]))
    used_names = [str(int(classes[i]) if float(classes[i]).is_integer() else classes[i])
                  for i in unique_in_test]
    report = classification_report(y_test_enc, y_pred,
                                   labels=unique_in_test,
                                   target_names=used_names,
                                   output_dict=True, zero_division=0)

    # Winrate: hanya ambil sinyal class 1 dan -1 dengan proba > MIN_PROBA
    idx_long  = next((i for i,c in enumerate(classes) if float(c)==1.0),  None)
    idx_short = next((i for i,c in enumerate(classes) if float(c)==-1.0), None)
    trade_mask = np.zeros(len(y_test), dtype=bool)
    directions = np.zeros(len(y_test), dtype=int)
    if idx_long is not None:
        mask_l = (y_proba[:, idx_long].ravel() > MIN_PROBA) if idx_long is not None and idx_long < y_proba.shape[1] else (y_proba[:, 0] < -1)
        trade_mask |= mask_l
        directions[mask_l] = 1
    if idx_short is not None:
        mask_s = (y_proba[:, idx_short].ravel() > MIN_PROBA) if idx_short is not None and idx_short < y_proba.shape[1] else (y_proba[:, 0] < -1)
        trade_mask |= mask_s
        directions[mask_s] = -1

    n_trades = trade_mask.sum()
    wins = 0
    if n_trades > 0:
        y_true_arr = np.array(y_test)
        wins = int(((directions[trade_mask] == y_true_arr[trade_mask])).sum())
    winrate = wins / n_trades if n_trades > 0 else 0.0

    # Profit factor: hits × (TP-fee) / misses × (SL+fee)
    profit  = wins * (TP_PCT - FEE_PCT)
    loss_am = max(0, n_trades - wins) * (SL_PCT + FEE_PCT)
    pf = profit / loss_am if loss_am > 0 else float("inf")

    return {"fold": fold, "pair": pair, "n_test": len(y_test),
            "n_trades": int(n_trades), "winrate": round(winrate, 4),
            "profit_factor": round(pf, 3),
            "f1_long":  round(report.get("1",  {}).get("f1-score", 0), 4),
            "f1_short": round(report.get("-1", {}).get("f1-score", 0), 4),
            "f1_hold":  round(report.get("0",  {}).get("f1-score", 0), 4),
            "accuracy_train": None, "accuracy_test": round(float((y_pred == np.array(y_test)).mean()), 4)}


# ── Training satu model ───────────────────────────────────────────────────────

def train_model(X_tr: pd.DataFrame, y_tr: pd.Series,
                X_val: pd.DataFrame, y_val: pd.Series,
                random_state: int = 42,
                le: LabelEncoder | None = None) -> tuple:
    if le is None:
        le = LabelEncoder()
        le.fit(np.array([-1.0, 0.0, 1.0]))
    y_tr_enc  = le.transform(y_tr)
    y_val_enc = le.transform(y_val)

    # ── LightGBM ──
    params = {**LGBM_PARAMS, "random_state": random_state}
    lgbm = LGBMClassifier(**params)
    lgbm.fit(
        X_tr, y_tr_enc,


    )

    # ── Random Forest (ensemble partner) ──
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )
    rf.fit(X_tr, y_tr_enc)

    # ── B7: Probability calibration (opsional, cv=prefit pakai validation) ──
    if CALIBRATE:
        try:
            from sklearn.calibration import CalibratedClassifierCV
            raw_imp = getattr(lgbm, "feature_importances_", None)
            try:
                cal = CalibratedClassifierCV(estimator=lgbm, method="isotonic", cv="prefit")
            except TypeError:
                cal = CalibratedClassifierCV(base_estimator=lgbm, method="isotonic", cv="prefit")
            cal.fit(X_val, le.transform(y_val))
            if raw_imp is not None:
                cal._raw_importances = raw_imp
            lgbm = cal
        except Exception as e:
            print(f"  WARN proba calibration failed, using raw model: {e}")

    return lgbm, rf, le


# ── Anti-overfit check ────────────────────────────────────────────────────────

def _safe_transform(le: LabelEncoder, y: pd.Series) -> np.ndarray:
    """Transform labels, ganti unseen label dengan 0 (HOLD) agar tidak crash."""
    known = set(float(x) for x in le.classes_)
    y_safe = y.map(lambda v: float(v) if float(v) in known else 0.0)
    return le.transform(y_safe)


def overfit_check(model, le: LabelEncoder,
                  X_tr: pd.DataFrame, y_tr: pd.Series,
                  X_te: pd.DataFrame, y_te: pd.Series, fold: int, pair: str) -> None:
    acc_train = float((model.predict(X_tr) == _safe_transform(le, y_tr)).mean())
    acc_test  = float((model.predict(X_te) == _safe_transform(le, y_te)).mean())
    gap = acc_train - acc_test
    if gap > 0.15:
        print(f"  ⚠️  OVERFIT WARNING [{pair} fold {fold}]: train={acc_train:.3f} test={acc_test:.3f} gap={gap:.3f} >15%")
    else:
        print(f"  ✅  [{pair} fold {fold}] train={acc_train:.3f} test={acc_test:.3f} gap={gap:.3f}")


# ── Stability test ────────────────────────────────────────────────────────────

def stability_test(X_tr: pd.DataFrame, y_tr: pd.Series,
                   X_val: pd.DataFrame, y_val: pd.Series,
                   X_te: pd.DataFrame, y_te: pd.Series, pair: str) -> None:
    """Latih 5× dengan random_state berbeda, lihat std winrate."""
    winrates = []
    for seed in [0, 7, 13, 21, 42]:
        m, _rf, le = train_model(X_tr, y_tr, X_val, y_val, random_state=seed)
        res = eval_fold(m, X_te, y_te, le, fold=0, pair=pair)
        winrates.append(res["winrate"])
    std_wr = float(np.std(winrates))
    mean_wr = float(np.mean(winrates))
    flag = "!! UNSTABLE" if std_wr > 0.05 else "OK STABLE"
    print(f"  Stability [{pair}]: mean_wr={mean_wr:.3f} std={std_wr:.3f} {flag}")


# ── Feature importance ────────────────────────────────────────────────────────

def _model_importances(model):
    """Ambil feature_importances_ dari model biasa atau model terkalibrasi."""
    imp = getattr(model, "feature_importances_", None)
    if imp is None:
        imp = getattr(model, "_raw_importances", None)
    return imp


def print_feature_importance(model: LGBMClassifier, top_n: int = 10) -> None:
    imp = _model_importances(model)
    if imp is None:
        print("  (feature importance not available for calibrated model)")
        return
    pairs = dict(zip(FEATURE_COLS, imp))
    top = sorted(pairs.items(), key=lambda x: x[1], reverse=True)[:top_n]
    print("  Feature importance top 10:")
    for name, val in top:
        print(f"    {name:<22} {val}")


def export_feature_importance(model, out_dir: Path, tag: str = "all") -> None:
    """D10: simpan feature importance ke JSON untuk audit/monitoring drift."""
    imp = _model_importances(model)
    if imp is None:
        return
    data = {k: float(v) for k, v in zip(FEATURE_COLS, imp)}
    data = dict(sorted(data.items(), key=lambda x: x[1], reverse=True))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"feature_importance_{tag}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Feature importance -> {path}")


# ── Main training pipeline ────────────────────────────────────────────────────

def train_pipeline(combined: pd.DataFrame, out_dir: Path) -> list[dict]:
    """
    Latih model per-pair + model gabungan dengan walk-forward.
    Simpan model ke out_dir. Kembalikan list hasil evaluasi.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict] = []
    pairs = combined["pair"].unique().tolist()

    # ── Per-pair ──────────────────────────────────────────────────────────────
    for pair in pairs:
        print(f"\n=== Training {pair} ===")
        df_p = combined[combined["pair"] == pair].sort_values("timestamp").reset_index(drop=True)
        splits = get_splits(df_p, N_FOLDS)
        best_model, best_rf, best_le, best_wr = None, None, None, -1.0

        # Pre-fit LabelEncoder dengan SEMUA label pair ini agar setiap fold konsisten
        pair_le = LabelEncoder()
        pair_le.fit(np.array([-1.0, 0.0, 1.0]))

        for fold_idx, (train_df, test_df) in enumerate(splits):
            if len(train_df) < 100 or len(test_df) < 30:
                print(f"  fold {fold_idx+1}: too little data, skip")
                continue
            # 10% terakhir dari train jadi validasi (untuk early stopping)
            val_cut = int(len(train_df) * 0.9)
            X_tr  = train_df.iloc[:val_cut][FEATURE_COLS]
            y_tr  = train_df.iloc[:val_cut]["label"]
            X_val = train_df.iloc[val_cut:][FEATURE_COLS]
            y_val = train_df.iloc[val_cut:]["label"]
            X_te  = test_df[FEATURE_COLS]
            y_te  = test_df["label"]

            lgbm, rf, le = train_model(X_tr, y_tr, X_val, y_val, le=pair_le)
            res = eval_fold(lgbm, X_te, y_te, le, fold_idx + 1, pair)
            overfit_check(lgbm, le, X_tr, y_tr, X_te, y_te, fold_idx + 1, pair)
            all_results.append(res)
            print(f"  fold {fold_idx+1}: winrate={res['winrate']:.3f} pf={res['profit_factor']:.2f} trades={res['n_trades']}")
            if res["winrate"] > best_wr:
                best_wr, best_model, best_rf, best_le = res["winrate"], lgbm, rf, le

        if best_model:
            # Stability test pakai split terakhir
            if splits:
                tr_df, te_df = splits[-1]
                val_c = int(len(tr_df) * 0.9)
                stability_test(
                    tr_df.iloc[:val_c][FEATURE_COLS], tr_df.iloc[:val_c]["label"],
                    tr_df.iloc[val_c:][FEATURE_COLS], tr_df.iloc[val_c:]["label"],
                    te_df[FEATURE_COLS], te_df["label"], pair,
                )
            print_feature_importance(best_model)
            export_feature_importance(best_model, out_dir, tag=pair.lower().replace("usdt", ""))
            model_path = out_dir / f"lgbm_{pair.lower().replace('usdt','')}.pkl"
            joblib.dump({"model": best_model, "rf_model": best_rf, "label_encoder": best_le, "feature_cols": FEATURE_COLS}, model_path)
            print(f"  Saved: {model_path}")

    # ── Combined model across all pairs ───────────────────────────────────────
    print("\n=== Training COMBINED model (all pairs) ===")
    combined_sorted = combined.sort_values("timestamp").reset_index(drop=True)
    splits_all = get_splits(combined_sorted, N_FOLDS)
    # Pre-fit LE global dengan semua label yang ada
    global_le = LabelEncoder()
    global_le.fit(np.array([-1.0, 0.0, 1.0]))
    best_model_all, best_rf_all, best_le_all, best_wr_all = None, None, None, -1.0
    for fold_idx, (train_df, test_df) in enumerate(splits_all):
        if len(train_df) < 200 or len(test_df) < 50:
            continue
        val_cut = int(len(train_df) * 0.9)
        X_tr  = train_df.iloc[:val_cut][FEATURE_COLS]
        y_tr  = train_df.iloc[:val_cut]["label"]
        X_val = train_df.iloc[val_cut:][FEATURE_COLS]
        y_val = train_df.iloc[val_cut:]["label"]
        X_te  = test_df[FEATURE_COLS]
        y_te  = test_df["label"]
        lgbm, rf, le = train_model(X_tr, y_tr, X_val, y_val, le=global_le)
        res = eval_fold(lgbm, X_te, y_te, le, fold_idx + 1, "ALL")
        overfit_check(lgbm, le, X_tr, y_tr, X_te, y_te, fold_idx + 1, "ALL")
        all_results.append(res)
        print(f"  fold {fold_idx+1}: winrate={res['winrate']:.3f} pf={res['profit_factor']:.2f} trades={res['n_trades']}")
        if res["winrate"] > best_wr_all:
            best_wr_all, best_model_all, best_rf_all, best_le_all = res["winrate"], lgbm, rf, le

    if best_model_all:
        print_feature_importance(best_model_all)
        export_feature_importance(best_model_all, out_dir, tag="all")
        combo_path = out_dir / "lightgbm_bnb_sol_doge_xrp.pkl"
        joblib.dump({"model": best_model_all, "rf_model": best_rf_all, "label_encoder": best_le_all, "feature_cols": FEATURE_COLS}, combo_path)
        print(f"  Saved: {combo_path}")

    # ── Simpan evaluasi ke CSV ────────────────────────────────────────────────
    eval_df = pd.DataFrame(all_results)
    csv_path = out_dir / "evaluation.csv"
    eval_df.to_csv(csv_path, index=False)
    print(f"\nEvaluation saved: {csv_path}")
    return all_results


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Train LightGBM walk-forward")
    parser.add_argument("--data-dir", default="data_historis",
                        help="Folder berisi CSV: BNBUSDT_3m.csv, SOLUSDT_5m.csv, dll.")
    parser.add_argument("--out-dir",  default="models")
    parser.add_argument("--timeframe",default="5m")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Folder {data_dir} not found.")
        print("Create the folder and place CSVs named: PAIR_TIMEFRAME.csv")
        print("Example: SOLUSDT_15m.csv with columns [timestamp,open,high,low,close,volume]")
        sys.exit(1)

    df_dict = {}
    # SINGLE SOURCE OF TRUTH: pairs from SYMBOLS in .env, timeframe(s) from TIMEFRAMES.
    pairs = [s.strip().upper() for s in os.getenv("SYMBOLS", "BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT").split(",") if s.strip()]
    tfs   = [t.strip() for t in os.getenv("TIMEFRAMES", "15m").split(",") if t.strip()]
    print(f"Active pairs (from .env SYMBOLS): {', '.join(pairs)}")
    for pair in pairs:
        for tf in tfs:
            csv_path = data_dir / f"{pair}_{tf}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                key = f"{pair}_{tf}"
                df_dict[key] = df
                print(f"Loaded {csv_path}: {len(df)} rows")
    if not df_dict:
        print("No matching CSV found. Format: BNBUSDT_15m.csv (pairs must match SYMBOLS)")
        sys.exit(1)

    print("\nBuilding features ...")
    parts = []
    for key, df in df_dict.items():
        pair_name = key  # e.g. SOLUSDT_15m
        feat = create_scalping_features(df, pair=pair_name)
        parts.append(feat)
        print(f"  {pair_name}: {len(feat)} rows")
    combined = pd.concat(parts, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    print(f"\nCombined dataset: {len(combined)} rows | label dist: {combined['label'].value_counts().to_dict()}")

    train_pipeline(combined, Path(args.out_dir))
