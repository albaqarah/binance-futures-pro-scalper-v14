from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List

try:
    from dotenv import load_dotenv
    from pathlib import Path as _Path
    # v12 FIX bug #1: selalu baca .env di folder project ini & OVERRIDE env lama.
    # Tanpa ini, env stale dari systemd (EnvironmentFile) menang -> edit nano .env
    # "balik ke setelan awal" setelah restart. override=True bikin .env selalu menang.
    _ENV_PATH = _Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=str(_ENV_PATH), override=True)
    else:
        load_dotenv(override=True)
except Exception:
    pass


def _bool(name, default):
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1","true","yes","y","on"}

def _float(name, default):
    raw = os.getenv(name)
    return default if raw in {None,""} else float(raw)

def _int(name, default):
    raw = os.getenv(name)
    return default if raw in {None,""} else int(raw)

def _str(name, default):
    return os.getenv(name, default)

def _list(name, default, uppercase=True):
    return [x.strip().upper() if uppercase else x.strip()
            for x in os.getenv(name, default).split(",") if x.strip()]

def _list_tf(name, default):
    """Timeframe list — TIDAK di-uppercase (5m harus tetap 5m bukan 5M)."""
    return _list(name, default, uppercase=False)

# v11: SCALP_MODE — saat true, default komponen berat dimatikan & param dipercepat.
# Env eksplisit tetap menang atas default ini.
_SCALP = _bool("SCALP_MODE", False)


@dataclass(frozen=True)
class Settings:
    # Koneksi
    api_key:    str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    dry_run:     bool = _bool("DRY_RUN", True)
    use_testnet: bool = _bool("USE_TESTNET", True)

    # Pair & timeframe
    # v14 (LOCKED): 3 kripto likuid + 2 TradFi Perps (emas & perak).
    # XAU/XAG = TradFi Perps Binance (BUKAN 24/7) -> dijaga tradfi_guard saat market tutup.
    # Hanya pair yang PUNYA model terlatih (atau fallback combo) yang sebaiknya di sini.
    symbols:    List[str] = field(default_factory=lambda: _list("SYMBOLS",
                                  "BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT"))
    # TF utama untuk klines (3m untuk scalping cepat, 5m lebih stabil)
    timeframes: List[str] = field(default_factory=lambda: _list_tf("TIMEFRAMES", "15m"))
    # Jumlah candle yang diambil untuk hitung fitur + prediksi
    klines_limit: int = _int("KLINES_LIMIT", 80)

    # Loop
    # Sesuaikan dengan TF: 3m -> 180, 5m -> 300
    loop_seconds: float = _float("LOOP_SECONDS", 90.0 if _SCALP else 300.0)
    log_level:    str   = _str("LOG_LEVEL", "INFO").upper()
    dashboard:    bool  = _bool("DASHBOARD", True)

    # Trading
    leverage:          int   = _int("LEVERAGE", 10)
    entry_margin_pct:  float = _float("ENTRY_MARGIN_PCT", 0.10)   # 10% margin bebas
    max_open_positions: int  = _int("MAX_OPEN_POSITIONS", 2)
    max_daily_trades:   int  = _int("MAX_DAILY_TRADES", 100 if _SCALP else 30)
    cooldown_after_trade_seconds: int = _int("COOLDOWN_AFTER_TRADE_SECONDS", 0 if _SCALP else 60)
    cooldown_after_loss_seconds:  int = _int("COOLDOWN_AFTER_LOSS_SECONDS",  60 if _SCALP else 180)
    min_reentry_seconds:          int = _int("MIN_REENTRY_SECONDS", 5)  # floor anti double-entry candle sama

    # SL/TP (plan_levels() pakai nilai per-profil pair; ini fallback global)
    stop_loss_pct:   float = _float("STOP_LOSS_PCT",  0.008)  # SOL=ATR, lainnya ~0.4-0.8%
    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 0.016) # RR 1:2 -> TP = 2x SL

    # SL+ (kunci breakeven berbasis ROI)
    breakeven_enable:      bool  = _bool("BREAKEVEN_ENABLE", True)
    breakeven_trigger_roi: float = _float("BREAKEVEN_TRIGGER_ROI", 0.05)
    breakeven_lock_roi:    float = _float("BREAKEVEN_LOCK_ROI",    0.03)

    # TP Paksa StochRSI (hanya saat posisi HIJAU)
    force_tp_enable:       bool  = _bool("FORCE_TP_ENABLE", True)
    force_tp_min_profit_pct: float = _float("FORCE_TP_MIN_PROFIT_PCT", 0.0)
    force_tp_stoch_long:   float = _float("FORCE_TP_STOCH_LONG",  70.0)
    force_tp_stoch_short:  float = _float("FORCE_TP_STOCH_SHORT", 20.0)

    # Filter market (v7 dipertahankan)
    range_min_pct:             float = _float("RANGE_MIN_PCT",            0.005)
    funding_rate_max:          float = _float("FUNDING_RATE_MAX",         0.001)
    avoid_first_minutes_of_hour: int = _int("AVOID_FIRST_MIN_OF_HOUR",    5)
    min_tp_pct:                float = _float("MIN_TP_PCT",                0.002)
    taker_fee_pct:             float = _float("TAKER_FEE_PCT",             0.0004)
    # v12 (10): Fee-Aware System — lapor PnL bersih, TP nutup fee, partial OFF utk scalp kecil
    maker_fee_pct:             float = _float("MAKER_FEE_PCT",             0.0002)
    report_net_pnl:            bool  = _bool("REPORT_NET_PNL",             True)
    fee_aware_tp:              bool  = _bool("FEE_AWARE_TP",               True)
    min_net_profit_pct:        float = _float("MIN_NET_PROFIT_PCT",        0.0015)
    prefer_maker_exit:         bool  = _bool("PREFER_MAKER_EXIT",          False)
    spread_filter_enable:      bool  = _bool("SPREAD_FILTER_ENABLE",       True)
    limit_fill_timeout_sec:    int   = _int("LIMIT_FILL_TIMEOUT_SEC",      15)

    # ML (LightGBM)
    ml_model_dir:       str   = _str("ML_MODEL_DIR",       "models")
    ml_proba_threshold: float = _float("ML_PROBA_THRESHOLD", _float("MIN_PROBA", 0.62))
    # v10: AI News-Directional Bias (berita buruk->SHORT, berita baik->LONG)
    news_bias_enable:      bool = _bool("NEWS_BIAS_ENABLE", False)
    news_bias_ttl_seconds: int  = _int("NEWS_BIAS_TTL_SECONDS", 10800)
    news_bias_min_score:   int  = _int("NEWS_BIAS_MIN_SCORE", 1)
    ml_ema_dist_min:    float = _float("ML_EMA_DIST_MIN",    0.001)  # EMA nempel -> skip
    ml_vol_mult_min:    float = _float("ML_VOL_MULT_MIN",    1.5)    # volume cukup -> masuk

    # ── Upgrade v9: Fitur Pro ─────────────────────────────────────────────────
    # Telegram Notification
    telegram_token:   str  = _str("TELEGRAM_TOKEN",   "")
    telegram_chat_id: str  = _str("TELEGRAM_CHAT_ID", "")

    # Session Filter
    session_filter_enable: bool = _bool("SESSION_FILTER_ENABLE", False)

    # v10: Confluence Scoring (Opsi A) — filter jadi poin (+/-), bukan veto mati
    confluence_min_score: float = _float("CONFLUENCE_MIN_SCORE", 1.2)
    w_news_align:        float = _float("W_NEWS_ALIGN",         1.5)
    w_news_against:      float = _float("W_NEWS_AGAINST",      -2.0)
    w_mtf_align:         float = _float("W_MTF_ALIGN",          2.0)
    w_mtf_against:       float = _float("W_MTF_AGAINST",       -2.0)
    w_ob_align:          float = _float("W_OB_ALIGN",           1.5)
    w_ob_against:        float = _float("W_OB_AGAINST",        -1.5)
    w_sentiment_against: float = _float("W_SENTIMENT_AGAINST", -1.5)

    # Multi-Timeframe Confirmation
    mtf_enable: bool = _bool("MTF_ENABLE", not _SCALP)

    # Order Book Imbalance
    orderbook_filter_enable: bool = _bool("ORDERBOOK_FILTER_ENABLE", True)

    # Trailing Stop Loss
    trailing_sl_enable:      bool  = _bool("TRAILING_SL_ENABLE",  True)
    trailing_sl_callback_pct: float = _float("TRAILING_SL_CALLBACK", 0.002 if _SCALP else 0.004)
    trailing_sl_activate_roi: float = _float("TRAILING_SL_ACTIVATE", 0.003 if _SCALP else 0.008)

    # Partial Close
    partial_close_enable:   bool  = _bool("PARTIAL_CLOSE_ENABLE",  False)
    partial_close_ratio:    float = _float("PARTIAL_CLOSE_RATIO",   0.5)   # tutup 50%
    partial_close_roi:      float = _float("PARTIAL_CLOSE_ROI",     0.012) # saat ROI 1.2%

    # ── v10.1: Smart-Entry Upgrade (Regime + Fast-Scan + AI-Confirm + Dynamic Size) ──
    # B) Fast-Scan Breakout — tangkap momentum breakout yang sering kelewat
    fast_scan_enable:    bool  = _bool("FAST_SCAN_ENABLE", True)
    breakout_lookback:   int   = _int("BREAKOUT_LOOKBACK", 20)
    breakout_vol_mult:   float = _float("BREAKOUT_VOL_MULT", 1.3)
    breakout_conf:       float = _float("BREAKOUT_CONF", 0.55)
    w_breakout:          float = _float("W_BREAKOUT", 1.5)

    # G) AI Regime Classifier — auto-tuning threshold/cooldown per kondisi pasar
    regime_enable:       bool  = _bool("REGIME_ENABLE", not _SCALP)
    regime_ttl_seconds:  int   = _int("REGIME_TTL_SECONDS", 7200)
    confluence_min_floor: float = _float("CONFLUENCE_MIN_FLOOR", 1.0)
    confluence_min_ceil:  float = _float("CONFLUENCE_MIN_CEIL", 4.0)

    # H) AI-Confirm Borderline — selametin near-miss entry
    ai_confirm_enable:   bool  = _bool("AI_CONFIRM_ENABLE", not _SCALP)
    borderline_margin:   float = _float("BORDERLINE_MARGIN", 1.0)

    # E) Dynamic Position Sizing — size by conviction (skor confluence)
    dynamic_size_enable:    bool  = _bool("DYNAMIC_SIZE_ENABLE", True)
    dynamic_size_min_mult:  float = _float("DYNAMIC_SIZE_MIN_MULT", 0.6)
    dynamic_size_max_mult:  float = _float("DYNAMIC_SIZE_MAX_MULT", 1.5)
    dynamic_size_per_point: float = _float("DYNAMIC_SIZE_PER_POINT", 0.2)

    # ── v11: Smart-Brain Upgrade ──
    scalp_mode: bool = _SCALP
    # 1) Order-Flow Anomaly (cumulative delta + imbalance + spoof)
    orderflow_enable:    bool  = _bool("ORDERFLOW_ENABLE", True)
    of_lookback:         int   = _int("OF_LOOKBACK", 20)
    w_orderflow_align:   float = _float("W_ORDERFLOW_ALIGN", 1.0)
    w_orderflow_against: float = _float("W_ORDERFLOW_AGAINST", -1.0)
    of_spoof_penalty:    float = _float("OF_SPOOF_PENALTY", -1.5)
    of_wall_ratio:       float = _float("OF_WALL_RATIO", 0.55)  # konsentrasi 1 level dianggap tembok
    # 3) Squeeze / Volatility predictor (funding + OI + realized vol)
    squeeze_enable:          bool  = _bool("SQUEEZE_ENABLE", True)
    squeeze_funding_extreme: float = _float("SQUEEZE_FUNDING_EXTREME", 0.0005)
    squeeze_oi_rise_pct:     float = _float("SQUEEZE_OI_RISE_PCT", 0.02)
    w_squeeze_align:         float = _float("W_SQUEEZE_ALIGN", 1.0)
    # 2) Positioning / Derivatives bias (Binance GRATIS: long/short ratio retail vs top trader)
    positioning_enable:    bool  = _bool("POSITIONING_ENABLE", True)
    ls_crowd_extreme:      float = _float("LS_CROWD_EXTREME", 2.0)
    w_positioning_align:   float = _float("W_POSITIONING_ALIGN", 1.0)
    w_positioning_against: float = _float("W_POSITIONING_AGAINST", -1.0)
    # 4) Session/Day adaptive threshold (belajar dari jurnal)
    session_adaptive_enable: bool = _bool("SESSION_ADAPTIVE_ENABLE", True)
    # 5) Post-trade journal
    journal_enable:      bool  = _bool("JOURNAL_ENABLE", True)

    # ── v12 (5): Screening timeframe 15m (konfirmasi tren TF lebih tinggi) ──
    screen_15m_enable:    bool  = _bool("SCREEN_15M_ENABLE", True)
    screen_15m_tf:        str   = _str("SCREEN_15M_TF", "15m")
    w_screen_15m_align:   float = _float("W_SCREEN_15M_ALIGN", 1.0)
    w_screen_15m_against: float = _float("W_SCREEN_15M_AGAINST", -1.0)

    # ── v12 (7): High-Conviction Mode (perpanjang TP saat sinyal buagus) ──
    # Tier-1: sinyal kuat 15m (conf>=conf1) -> TP jauh, trailing longgar, partial kecil.
    # Tier-2: sinyal kuat 5m  (conf>=conf2) -> TP agak jauh. Selain itu: scalp normal.
    high_conviction_enable: bool = _bool("HIGH_CONVICTION_ENABLE", True)
    hc_tf1:        str   = _str("HIGH_CONVICTION_TF1", "15m")
    hc_conf1:      float = _float("HIGH_CONVICTION_CONF1", 0.80)
    hc_tp_mult1:   float = _float("HIGH_CONVICTION_TP_MULT1", 3.5)
    hc_trail1:     float = _float("HIGH_CONVICTION_TRAIL1", 0.005)
    hc_partial1:   float = _float("HIGH_CONVICTION_PARTIAL1", 0.30)
    hc_tf2:        str   = _str("HIGH_CONVICTION_TF2", "5m")
    hc_conf2:      float = _float("HIGH_CONVICTION_CONF2", 0.80)
    hc_tp_mult2:   float = _float("HIGH_CONVICTION_TP_MULT2", 2.8)
    hc_trail2:     float = _float("HIGH_CONVICTION_TRAIL2", 0.004)
    hc_partial2:   float = _float("HIGH_CONVICTION_PARTIAL2", 0.40)

    # ── v12 (9): Morning Briefing harian (ringkasan 24 jam, dibaca ai_agent.py) ──
    morning_briefing_enable: bool = _bool("MORNING_BRIEFING_ENABLE", True)
    morning_briefing_hour:   int  = _int("MORNING_BRIEFING_HOUR", 7)

    # ── v14 bucket C/D: Eksekusi tingkat lanjut (SEMUA default OFF) ──
    # D1: Maker-first — pasang LIMIT post-only di best bid/ask biar dapat maker fee.
    maker_first_enable:        bool  = _bool("MAKER_FIRST_ENABLE", False)
    maker_first_offset_ticks:  int   = _int("MAKER_FIRST_OFFSET_TICKS", 0)
    maker_first_retries:       int   = _int("MAKER_FIRST_RETRIES", 3)
    # D2: Iceberg — pecah entry market besar jadi beberapa chunk (kurangi impact).
    iceberg_enable:            bool  = _bool("ICEBERG_ENABLE", False)
    iceberg_chunks:            int   = _int("ICEBERG_CHUNKS", 3)
    iceberg_min_notional_mult: float = _float("ICEBERG_MIN_NOTIONAL_MULT", 2.0)
    # C4: Dynamic ATR-based TP/SL — SL/TP adaptif volatilitas, bukan persen flat.
    dynamic_atr_tpsl_enable:   bool  = _bool("DYNAMIC_ATR_TPSL_ENABLE", False)
    atr_tp_mult:               float = _float("ATR_TP_MULT", 3.0)
    atr_sl_mult:               float = _float("ATR_SL_MULT", 1.5)
    atr_tpsl_min_sl_pct:       float = _float("ATR_TPSL_MIN_SL_PCT", 0.003)
    atr_tpsl_max_sl_pct:       float = _float("ATR_TPSL_MAX_SL_PCT", 0.03)
    # D3: Smart trailing SL (chandelier ATR) — helper tersedia, default OFF.
    smart_trailing_enable:     bool  = _bool("SMART_TRAILING_ENABLE", False)
    smart_trailing_atr_mult:   float = _float("SMART_TRAILING_ATR_MULT", 2.0)

    # ── v14: AI Veto Gate (meta-labeling) — AI overseer konfirmasi/veto entry terbaik ──
    # ML = generator sinyal; AI HANYA bisa MELOLOSKAN (grade A/B/C) atau MEM-VETO.
    # FAIL-OPEN: kalau AI error/timeout/tanpa-key -> entry tetap lanjut, KECUALI strict=true.
    ai_veto_enable:  bool = _bool("AI_VETO_ENABLE", True)
    ai_veto_strict:  bool = _bool("AI_VETO_STRICT", False)
    # ── v14: TradFi guard (XAU/XAG bukan 24/7) — skip pair TradFi saat pasar tutup ──
    tradfi_guard_enable: bool = _bool("TRADFI_GUARD_ENABLE", True)
    tradfi_symbols: List[str] = field(default_factory=lambda: _list("TRADFI_SYMBOLS",
                                  "XAUUSDT,XAGUSDT"))
    # ── v14: Daily post-trade review (dijalankan ai_agent.py, read-only saran) ──
    daily_review_enable: bool = _bool("DAILY_REVIEW_ENABLE", True)
