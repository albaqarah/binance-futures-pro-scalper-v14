# CHANGELOG — Binance Futures PRO Scalper

Semua versi sebelumnya tetap dicatat di sini sebagai histori. Versi aktif sekarang: **v14**.

---

## v14 — 1 Jul 2026 (ML-polish patch)

### 🎯 Fokus: naikin Profit Factor (perbaikan label + fokus pair)
- **BUG FIX besar — triple-barrier akhirnya kepakai.** `create_scalping_features()` dulu default `label_mode="fixed"` (return ±0.8% dalam 8 candle) → **~55% label jadi HOLD**, model jarang PD confident (PF < 1). Sekarang default via `.env` `LABEL_MODE=triple_barrier`. Uji distribusi: fixed = 55% HOLD/27% long/18% short → triple_barrier = ~50/50 long/short seimbang.
- **Label triple-barrier di-tune utk 15m**: `TB_HORIZON=16` (16×15m = 4 jam), `TB_TP_MULT=1.2` (TP realistis), `TB_SL_MULT=1.0`. Semua bisa diatur via `.env` (`LABEL_MODE/TB_HORIZON/TB_TP_MULT/TB_SL_MULT`, plus `LABEL_HORIZON/LABEL_THRESHOLD` utk mode fixed).
- **`.env` sekarang dimuat saat training.** `features.py` & `setup_and_train.py` memuat `.env` sendiri (dulu tidak, karena tak mengimpor `config`) → `LABEL_MODE/TB_*/PURGED_CV/CALIBRATE_PROBA` benar-benar terbaca saat `python3 setup_and_train.py`.
- **BUG FIX — `setup_and_train.py` tidak lagi menimpa data dalam.** Fungsi download bawaannya dulu selalu tarik ulang 1500 candle BNB/SOL/DOGE/XRP 3m/5m → menimpa hasil `fetch_history.py` (12 bulan). Sekarang: kalau `data_historis/` sudah ada CSV, download dilewati; fallback download ikut `SYMBOLS/TIMEFRAMES`.
- **Fokus 2-3 pair @ 15m.** Default `SYMBOLS=BNBUSDT,SOLUSDT,LINKUSDT`, `TIMEFRAMES=15m` (di `config.py` & `.env.example`). Hanya pair yang punya model terlatih.
- **Anti-overfit default ON** di `.env.example`: `CALIBRATE_PROBA=true`, `PURGED_CV=true`, `PURGE_EMBARGO_FRAC=0.01`.
- **Config bersih (kosmetik).** Header dashboard `v12 HYBRID` → `v14 HYBRID`; baris `Pairs:` kini dinamis dari `settings.symbols` (bukan string statis "BTC ETH BNB SOL DOGE XRP"); timeframe ikut config (tak ada lagi 1m yang tak bermodel).

---

## v14 (current) — 30 Jun 2026

### 🆕 Batch analitik & validasi (verifikasi edge — aman, tidak menyentuh order live)
- **`bot/metrics.py` (C7)** — metrik performa proper dari trade journal: Profit Factor, Expectancy (USDT & R), Payoff, Max Drawdown (USDT & %), Sharpe, Sortino, max beruntun rugi, breakdown per-symbol, plus "vonis" otomatis (warning kalau sampel < 30 trade). Standalone: `python3 -m bot.metrics`.
- **`tools/monte_carlo.py` (D13)** — uji robustness: bootstrap ribuan urutan PnL dari journal → peluang profit, **risk of ruin**, sebaran max drawdown (P5/median/P95). Standalone: `python3 -m tools.monte_carlo --runs 5000 --start 100`.
- **`tests/test_risk_pnl.py` (D12)** — 12 unit test untuk logika UANG (SL/TP long+short, profit_pct, breakeven, sizing/leverage, summarize_income, win_rate). Jalankan: `python3 -m unittest tests.test_risk_pnl -v`. **Status: 12/12 PASS.**
- **Morning Briefing (C7)** — metrik proper + ringkasan Monte Carlo otomatis ditempel ke briefing harian Telegram.
- **CLI baru di `ai_agent.py`**: `--metrics` (cetak metrik performa) dan `--montecarlo` (jalankan simulasi robustness).
- Catatan jujur: batch ini **mengukur** apakah strategi punya edge — ia tidak mengubah sinyal/eksekusi. Item ML-retraining & eksekusi-order masih butuh retrain berbasis data + uji DRY_RUN sebelum live (lihat ringkasan di chat).

### 🧠 Batch ML & Eksekusi tingkat lanjut (bucket B/C/D — pengembangan, butuh retrain & DRY_RUN sebelum live)
- **`fetch_history.py` (B-data)** — downloader histori Binance Futures untuk retrain: klines (paginasi 1500), funding rate, Open Interest / Long-Short Ratio / Taker ratio (limit 30 hari), dan CVD dari aggTrades. Output CSV ke `data_historis/`. Jalankan di VPS: `python3 fetch_history.py --months 6`.
- **Triple-Barrier Labeling (B5)** di `bot/features.py` — `triple_barrier_label()` + parameter baru `label_mode` di `create_scalping_features` (`"fixed"` = default lama, `"triple_barrier"` = barrier ATR atas/bawah + barrier vertikal horizon). ZERO lookahead, bar ekor = NaN.
- **Purged + Embargo Walk-Forward CV (B8)** di `bot/train.py` — `purged_walk_forward_splits()` membuang `PURGE_EMBARGO_FRAC` baris di batas train→test untuk cegah kebocoran label yang overlap horizon. Aktif via `PURGED_CV=true` (default OFF, tetap walk-forward biasa).
- **Kalibrasi probabilitas (B7)** di `bot/train.py` — opsi `CALIBRATE_PROBA=true` membungkus model dengan `CalibratedClassifierCV` (isotonic, cv=prefit pakai validation) supaya angka confidence ML lebih jujur. Default OFF.
- **Export feature importance JSON (D10)** — `export_feature_importance()` menulis `feature_importance_<pair>.json` & `feature_importance_all.json` ke folder model untuk audit/monitoring drift.
- **`bot/execution.py` (bucket C/D, fungsi PURE & ter-unit-test)**:
  - **Maker-first pricing (D1)** — `maker_price()` pasang LIMIT di best bid/ask biar dapat maker fee; `crosses_spread()` cek anti-taker.
  - **Iceberg / order splitting (D2)** — `split_iceberg()` pecah entry besar jadi beberapa chunk (jaga total qty).
  - **Dynamic ATR TP/SL (C4)** — `dynamic_atr_tpsl()` SL/TP adaptif volatilitas (clamp min/max %, jaga RR).
  - **Smart trailing SL chandelier (D3)** — `smart_trailing_sl()` ikuti harga ekstrem minus ATR×mult, hanya geser ke arah kunci profit.
- **Wiring ke `bot/main.py` (SEMUA default OFF via flag `.env`)**: dynamic ATR TP/SL override level entry, maker-first pricing di jalur limit, dan iceberg di jalur market. Tanpa mengaktifkan flag, perilaku live **identik** seperti sebelumnya.
- **Flag baru di `bot/config.py` (default OFF)**: `MAKER_FIRST_ENABLE`/`MAKER_FIRST_OFFSET_TICKS`/`MAKER_FIRST_RETRIES`, `ICEBERG_ENABLE`/`ICEBERG_CHUNKS`/`ICEBERG_MIN_NOTIONAL_MULT`, `DYNAMIC_ATR_TPSL_ENABLE`/`ATR_TP_MULT`/`ATR_SL_MULT`/`ATR_TPSL_MIN_SL_PCT`/`ATR_TPSL_MAX_SL_PCT`, `SMART_TRAILING_ENABLE`/`SMART_TRAILING_ATR_MULT`, `PURGED_CV`/`PURGE_EMBARGO_FRAC`, `CALIBRATE_PROBA`.
- **`tests/test_execution_features.py` (D12)** — 28 unit test untuk semua fungsi PURE di atas (maker/iceberg/ATR TP-SL/trailing/triple-barrier). **Status keseluruhan suite: 40/40 PASS.**
- Catatan jujur: fitur ML (triple-barrier, purged CV, kalibrasi) **baru aktif setelah retrain** pakai `fetch_history.py`. Fitur eksekusi (maker/iceberg/dynamic ATR) **default OFF** — uji `DRY_RUN=true` dulu sebelum diaktifkan live.

### 🔄 Rebrand
- Semua **branding versi** di seluruh proyek diganti ke **v14**: header README, judul & logo Web Dashboard, banner AI Agent, deskripsi systemd service (`scalper-bot.service`, `scalper-agent.service`, `install_service.sh`), banner `setup_and_train.py`, runtime log/Telegram start banner di `bot/main.py`, dan nama folder/zip `binance-futures-pro-scalper-v14`.
- Catatan: komentar **changelog historis** di dalam kode (mis. `# v10:`, `# v11 (4):`, `# v12 (10):`) sengaja **dipertahankan** sebagai penanda kapan sebuah fitur diperkenalkan. Ini bukan branding versi aktif. Kalau mau ini juga di-flat-kan ke v14, tinggal bilang.

### 🗑️ Dihapus
- **`auto_adjust_params()` dihapus total** dari `ai_agent.py`:
  - definisi fungsi (blok `# ── Auto-Adjust Parameter ──`),
  - call-site `adjustments = auto_adjust_params(stats, fng)`,
  - blok laporan Telegram `⚙️ AUTO-ADJUST:` yang memakai variabel `adjustments`.
  - Alasan: AI Agent **tidak lagi mengubah `.env` secara otomatis**. Semua parameter sekarang sepenuhnya dikontrol manual. Agent fokus ke analisis, news bias, regime, session-stats, dan Morning Briefing — bukan auto-tuning.

### ✅ Diwarisi dari v12 (tetap aktif)
- Fee-Aware System (lapor PnL bersih, TP menutup fee, partial OFF untuk scalp kecil).
- 8 pair tanpa BTC/ETH: BNB, SOL, XRP, LINK, SUI, AVAX, APT, TIA.
- Screening timeframe 15m (konfirmasi tren TF lebih tinggi).
- High-Conviction Mode (perpanjang TP + partial saat sinyal kuat).
- Morning Briefing harian 07:00 WIB (ringkasan 24 jam ke Telegram).
- `ML_PROBA_THRESHOLD = 0.62`, `CONFLUENCE_MIN_SCORE = 1.2`.
- Breakeven move (state `breakeven_done`).
- Force-close posisi + cancel sisa algo order saat posisi ditutup di sisi Binance.
- `.env` dibaca dengan absolute path + `override=True` (fix bug `.env` ke-revert).

---

## 🧭 Roadmap terkunci (belum diimplementasi — lihat dokumen "Pro Scalper v14 — Spec & Roadmap (LOCKED)")

Status jujur dari hasil review struktur kode (perlu verifikasi baris-per-baris saat lanjut implementasi):

### Eksekusi order (microstructure)
- ❌ Maker-first execution (post-only → fallback market)
- ❌ Iceberg / split order
- ❌ Smart SL berbasis struktur (swing low / likuiditas)

### Manajemen posisi
- ⚠️ Trailing stop adaptif **ATR** (saat ini HC pakai trailing %-based, belum ATR)
- ✅ Breakeven move (sudah ada)
- ❌ Scale-in terkontrol (tanpa averaging down)

### Sinyal & ML
- ❌ Ensemble model (LightGBM + baseline + 1 nonlinear)
- ❌ Confidence-based sizing (size proporsional ke proba; sekarang flat ~10%)
- ❌ Online/incremental learning harian (sekarang retrain mingguan)
- ❌ Feature importance monitoring
- ⚠️ Konsistensi fitur train vs live (perlu audit `train.py` vs `ml_signal.py` + cek leakage)
- 📌 Hindari over-optimize / overfit (bukti: `OVERFIT [DOGEUSDT_5m] train=1.000 test=0.511 gap=0.489`)

### Sinyal-quality (institutional)
- ❌ Order book imbalance, CVD, funding/OI, relative volume vs ATR
- ❌ Triple-barrier labeling + meta-labeling + calibrated probability
- ❌ Walk-forward + purged/embargoed CV, backtest realistis (fee+slippage+latency)
- ❌ Regime detection terintegrasi ke entry
- ✅ LLM **tidak** dipakai di jalur eksekusi (hanya monitor/analisis) — sesuai prinsip

### Data & infra
- ❌ Latency optimization / WebSocket (sekarang REST polling)
- ❌ Spread filter sebelum entry
- ❌ Dynamic ATR-based TP/SL
- ❌ Data hygiene (validasi gap/dedup OHLCV)

### Metrik & monitoring
- ❌ Metrik proper di briefing: profit factor, expectancy, max drawdown, Sharpe (quick-win berikutnya)
- ⚠️ Reconciliation harian (bot PnL vs Binance realized) — agent sudah tarik income Binance, belum cross-check otomatis
- ✅ CHANGELOG.md (file ini)

### Pengujian
- ❌ Unit test `risk.py` & `pnl.py`
- ❌ Monte Carlo simulation (acak urutan trade → sebaran drawdown)

---

> ⚠️ **Reminder realita:** live 2 hari terakhir tercatat winrate ~29.6% dengan PnL -5.20 USDT, dan ada sinyal overfit kuat di model. Target "90% winrate" belum tervalidasi di kondisi live. Roadmap di atas adalah jalan menuju kualitas sinyal yang lebih jujur — bukan janji winrate.
