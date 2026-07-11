"""
ai_agent.py — AI Agent Cerdas untuk Bot Trading v14

Kemampuan:
  1. Baca & analisis log bot real-time
  2. Baca berita crypto terbaru dari web
  3. Kirim laporan + saran ke Telegram
  4. Auto-adjust parameter bot (.env)
  5. Monitor kesehatan bot & auto-restart
  6. Alert berita penting sebelum terjadi

Cara jalankan:
  python3 ai_agent.py              # jalan terus (loop per jam)
  python3 ai_agent.py --once       # jalankan sekali lalu keluar
  python3 ai_agent.py --report     # paksa kirim laporan sekarang

Setup .env:
  OPENAI_API_KEY=sk-...            # pakai OpenAI GPT-4o
  ATAU
  ANTHROPIC_API_KEY=sk-ant-...     # pakai Claude

  TELEGRAM_TOKEN=...               # sudah ada
  TELEGRAM_CHAT_ID=...             # sudah ada
  AI_AGENT_INTERVAL_MINUTES=60     # cek tiap 60 menit
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import URLError

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
LOG_FILE   = BASE_DIR / "logs" / "bot.log"
STATE_FILE = BASE_DIR / "logs" / "state.json"
ENV_FILE   = BASE_DIR / ".env"
AGENT_STATE= BASE_DIR / "logs" / "agent_state.json"
PIDFILE    = BASE_DIR / "logs" / "bot.pid"
NEWS_BIAS_FILE = BASE_DIR / "logs" / "news_bias.json"
NEWS_HUNT_FILE = BASE_DIR / "logs" / "news_hunt.json"
REGIME_FILE    = BASE_DIR / "logs" / "regime.json"


# ── Config dari .env ─────────────────────────────────────────────────────────
def _clean_val(v: str) -> str:
    """Bersihkan value .env: buang quote pembungkus & komentar inline (#)."""
    v = v.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    for i, ch in enumerate(v):
        if ch == "#" and (i == 0 or v[i - 1] in " \t"):
            v = v[:i]
            break
    return v.strip()


def _env(key: str, default: str = "") -> str:
    """Baca .env file atau environment variable."""
    val = os.environ.get(key, "")
    if val: return _clean_val(val)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            if k.strip() == key: return _clean_val(v)
    return default


# v14: AI Agent pakai KEY SENDIRI (AI_AGENT_API_KEY) yang diinput manual, DIPISAH dari key bot.
# Fallback ke OPENAI_* biar setup lama tetap jalan kalau AI_AGENT_* sengaja dikosongkan.
OPENAI_KEY      = _env("AI_AGENT_API_KEY") or _env("OPENAI_API_KEY")
OPENAI_BASE_URL = (_env("AI_AGENT_BASE_URL") or _env("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
OPENAI_MODEL    = _env("AI_AGENT_MODEL") or _env("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_KEY   = _env("ANTHROPIC_API_KEY")
TG_TOKEN        = _env("TELEGRAM_TOKEN")
TG_CHAT_ID      = _env("TELEGRAM_CHAT_ID")
INTERVAL_MIN    = int(_env("AI_AGENT_INTERVAL_MINUTES", "60"))
NEWS_BIAS_MIN_SCORE = int(_env("NEWS_BIAS_MIN_SCORE", "1"))
NEWS_BIAS_TTL       = int(_env("NEWS_BIAS_TTL_SECONDS", "10800"))
REGIME_ENABLE       = _env("REGIME_ENABLE", "true").strip().lower() in {"1","true","yes","y","on"}
REGIME_TTL          = int(_env("REGIME_TTL_SECONDS", "7200"))
REGIME_BASE_MIN     = float(_env("CONFLUENCE_MIN_SCORE", "2.0"))
WIB             = timezone(timedelta(hours=7))

# v12 (9): Morning Briefing harian (ringkasan 24 jam ke Telegram)
MORNING_BRIEFING_ENABLE = _env("MORNING_BRIEFING_ENABLE", "true").strip().lower() in {"1", "true", "yes", "y", "on"}
MORNING_BRIEFING_HOUR   = int(_env("MORNING_BRIEFING_HOUR", "7"))


# ── Telegram ─────────────────────────────────────────────────────────────────
def tg_send(text: str) -> bool:
    if not TG_TOKEN or not TG_CHAT_ID: return False
    try:
        url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urlencode({"chat_id": TG_CHAT_ID, "text": text,
                          "parse_mode": "HTML"}).encode()
        req  = Request(url, data=data, method="POST")
        with urlopen(req, timeout=8): pass
        return True
    except Exception:
        return False


# ── Baca Log Bot ─────────────────────────────────────────────────────────────
def read_recent_logs(hours: int = 24) -> str:
    """Ambil log bot N jam terakhir."""
    if not LOG_FILE.exists(): return "(log not found)"
    try:
        lines = LOG_FILE.read_text(errors="ignore").splitlines()
        # Ambil 300 baris terakhir saja
        return "\n".join(lines[-300:])
    except Exception:
        return "(error membaca log)"


def read_state() -> dict:
    """Baca state bot (last_trade, daily_trades, dll)."""
    if not STATE_FILE.exists(): return {}
    try: return json.loads(STATE_FILE.read_text())
    except Exception: return {}


# ── Analisis Log Lokal (tanpa AI) ─────────────────────────────────────────────
def parse_trades_from_log(log_text: str) -> dict:
    """Parse entry/close dari log untuk hitung statistik."""
    entries = re.findall(r'ENTRY (LONG|SHORT) (\w+) qty=([\d.]+) @[~]?([\d.]+)', log_text)
    wins    = re.findall(r'TP PAKSA|PROFIT|close.*profit', log_text, re.IGNORECASE)
    losses  = re.findall(r'LOSS|stop.loss', log_text, re.IGNORECASE)
    pnl_matches = re.findall(r'PnL.*?([+-][\d.]+)', log_text)
    errors  = re.findall(r'ERROR|error|gagal|failed', log_text, re.IGNORECASE)
    return {
        "total_entries": len(entries),
        "pairs_traded":  list({e[1] for e in entries}),
        "wins":          len(wins),
        "losses":        len(losses),
        "errors":        len(errors),
        "winrate":       round(len(wins)/(len(wins)+len(losses))*100, 1)
                         if (len(wins)+len(losses)) > 0 else 0,
    }


def _load_env_to_environ() -> None:
    """Muat .env ke os.environ agar bot.config.Settings membaca nilai yang benar."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # v12 FIX bug #1: OVERRIDE (bukan setdefault) supaya nilai .env terbaru menang
        # atas env lama yang sudah ke-inject systemd/stale.
        os.environ[k.strip()] = _clean_val(v)


def fetch_binance_stats(hours: int = 24) -> dict | None:
    """Hitung Entry/Win/Loss/Net dari realized PnL Binance (akurat, bukan dari teks log).
    Return None kalau dry-run / tanpa API key / gagal -> caller fallback ke parse log."""
    try:
        _load_env_to_environ()
        from bot.config import Settings
        from bot.exchange_binance import BinanceFuturesClient
        from bot.pnl import summarize_income
        st = Settings()
        if st.dry_run or not st.api_key or not st.api_secret:
            return None
        client = BinanceFuturesClient(st)
        client.sync_time()
        now_ms   = int(time.time() * 1000)
        start_ms = now_ms - int(hours) * 3600 * 1000
        rows = client._request("GET", "/fapi/v1/income",
                               {"startTime": start_ms, "limit": 1000}, signed=True)
        d = summarize_income(rows)
        try:
            open_n = len(client.open_positions())
        except Exception:
            open_n = 0
        return {
            "total_entries":  d.trades,
            "pairs_traded":   [],
            "wins":           d.wins,
            "losses":         d.losses,
            "errors":         0,
            "winrate":        round(d.win_rate, 1),
            "net":            round(d.net, 4),
            "realized":       round(d.realized, 4),
            "open_positions": open_n,
            "source":         "binance",
        }
    except Exception as e:
        print(f"[AGENT] fetch_binance_stats failed: {e}")
        return None


# ── Cek Kesehatan Bot ─────────────────────────────────────────────────────────
def bot_is_running() -> bool:
    """Cek apakah proses bot sedang jalan."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python -m bot"], capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def restart_bot() -> bool:
    """Restart bot utama lewat systemd supaya tidak bikin duplicate process."""
    import subprocess
    try:
        r = subprocess.run(["sudo", "systemctl", "restart", "scalper-bot.service"], timeout=30)
        if r.returncode == 0:
            print("[AGENT] scalper-bot.service restarted via systemd")
            return True
        print("[AGENT] systemctl restart failed")
        return False
    except Exception as e:
        print(f"[AGENT] Restart failed: {e}")
        return False


def fetch_crypto_news() -> str:
    """Fetch headline crypto dari CryptoPanic RSS (gratis, no API key)."""
    sources = [
        "https://cryptopanic.com/news/rss/",
        "https://feeds.feedburner.com/CoinDesk",
    ]
    headlines = []
    for url in sources:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=8) as r:
                content = r.read().decode("utf-8", errors="ignore")
            # Parse judul dari RSS
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', content)
            for t in titles[:10]:
                title = (t[0] or t[1]).strip()
                if title and len(title) > 10 and 'RSS' not in title:
                    headlines.append(title)
            if headlines: break
        except Exception:
            continue
    return "\n".join(headlines[:8]) if headlines else "(could not fetch news)"


# ── Fear & Greed ──────────────────────────────────────────────────────────────
def fetch_fear_greed() -> dict:
    try:
        with urlopen("https://api.alternative.me/fng/?limit=1", timeout=6) as r:
            data = json.loads(r.read())
        d = data["data"][0]
        return {"score": int(d["value"]), "label": d["value_classification"]}
    except Exception:
        return {"score": 50, "label": "Neutral"}


# ── Ambil Harga Crypto ────────────────────────────────────────────────────────
def fetch_prices() -> str:
    """Harga terkini BTC, ETH, BNB dari Binance."""
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    prices  = []
    try:
        for sym in symbols:
            url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}"
            with urlopen(Request(url), timeout=5) as r:
                d = json.loads(r.read())
            prices.append(f"{sym}: ${float(d['price']):,.2f}")
    except Exception:
        pass
    return " | ".join(prices)


# ── AI Brain (OpenAI / Anthropic) ────────────────────────────────────────────
def ask_ai(prompt: str) -> str:
    """Kirim prompt ke AI dan dapat jawaban."""
    if OPENAI_KEY:
        return _ask_openai(prompt)
    elif ANTHROPIC_KEY:
        return _ask_anthropic(prompt)
    else:
        return _analyze_local(prompt)


def _ask_openai(prompt: str) -> str:
    """Kirim prompt ke OpenAI-compatible API.

    Default: OpenAI official.
    Untuk Bluesminds, set di .env:
      OPENAI_BASE_URL=https://api.bluesminds.com/v1
      OPENAI_MODEL=openai/zai-org/GLM-4.7
    """
    try:
        url  = f"{OPENAI_BASE_URL}/chat/completions"
        body = json.dumps({
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": (
                    "You are an analytical trading AI Agent. "
                    "Give a short, actionable analysis in English. "
                    "Max 300 words. Use emojis sparingly."
                )},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.3,
        }).encode()
        req = Request(url, data=body, method="POST",
                      headers={"Content-Type": "application/json",
                               "User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {OPENAI_KEY}"})
        with urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"(OpenAI-compatible error: {e})"


def _ask_anthropic(prompt: str) -> str:
    try:
        url  = "https://api.anthropic.com/v1/messages"
        body = json.dumps({
            "model": "claude-3-haiku-20240307",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
            "system": (
                "You are an analytical trading AI Agent. "
                "Give a short, actionable analysis in English. "
                "Max 300 words."
            ),
        }).encode()
        req = Request(url, data=body, method="POST",
                      headers={"Content-Type": "application/json",
                               "x-api-key": ANTHROPIC_KEY,
                               "anthropic-version": "2023-06-01", "User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        return resp["content"][0]["text"].strip()
    except Exception as e:
        return f"(Anthropic error: {e})"


def _analyze_local(prompt: str) -> str:
    """Analisis sederhana tanpa AI API (fallback)."""
    return (
        "\U0001f916 AI Engine inactive (no API key yet).\n"
        "Add OPENAI_API_KEY or ANTHROPIC_API_KEY in .env\n"
        "to enable smart AI analysis."
    )


# ── Buat Prompt Analisis ──────────────────────────────────────────────────────
def build_analysis_prompt(log_text: str, stats: dict, news: str,
                           fng: dict, prices: str, state: dict) -> str:
    now_wib = datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")
    return f"""Kamu menganalisis bot trading crypto Binance Futures aku.

Waktu: {now_wib}
Harga pasar: {prices}
Fear & Greed Index: {fng['score']}/100 ({fng['label']})

STATISTIK BOT (24 jam terakhir):
- Total entry: {stats['total_entries']}
- Pair diperdagangkan: {', '.join(stats['pairs_traded']) or 'tidak ada'}
- Win: {stats['wins']} | Loss: {stats['losses']}
- Winrate: {stats['winrate']}%
- Error di log: {stats['errors']}

HEADLINE BERITA CRYPTO TERBARU:
{news}

LOG BOT (50 baris terakhir):
{chr(10).join(log_text.splitlines()[-50:])}

Berikan:
1. Penilaian performa bot hari ini (1-2 kalimat)
2. Insight dari berita yang relevan untuk trading
3. Saran konkret 1-2 hal untuk sesi berikutnya
4. Warning kalau ada yang perlu diwaspadai
Format pakai emoji, singkat dan to the point."""




# ── Load Agent State ──────────────────────────────────────────────────────────
# ── v10: AI News-Directional Bias + Model listing ─────────────────────
NEWS_BULLISH = [
    "surge", "soar", "rally", "rallies", "gains", "record high", "all-time high",
    "etf approval", "approves", "approved", "adoption", "bullish",
    "institutional", "inflow", "inflows", "accumulate", "buying", "upgrade",
    "partnership", "integration", "launch", "launches", "listing", "halving",
    "breakout", "pump", "rebound", "recovery", "boost", "milestone",
    "investment", "tokenize", "green",
]
NEWS_BEARISH = [
    "crash", "plunge", "plummet", "dump", "selloff", "sell-off", "tumble",
    "hack", "hacked", "exploit", "breach", "banned", " ban ", "bans", "sec ",
    "lawsuit", "sued", "liquidation", "liquidations", "fud", "bearish",
    "outage", "fined", "fraud", "scam", "downgrade", "collapse", "default",
    "bankrupt", "bankruptcy", "rate hike", "hawkish", "inflation", "cpi",
    "warning", "halt", "slump", "weak", "fed", "fomc",
]


def _ask_ai_news_direction(news: str) -> str:
    """Minta AI klasifikasi arah pasar dari berita: long/short/neutral."""
    try:
        prompt = (
            "Based on the following crypto news headlines, determine a ONE-WORD "
            "short-term market sentiment direction for trading: answer exactly one of "
            "'long' (bullish / good news), 'short' (bearish / bad news), or "
            "'neutral'. Answer ONLY one word with no explanation.\n\nHEADLINES:\n" + (news or "")
        )
        ans = ask_ai(prompt).strip().lower()
        m = re.search(r"\b(long|short|neutral)\b", ans)
        return m.group(1) if m else ""
    except Exception:
        return ""



def analyze_news_hunt(news: str, fng: dict, prices: str = "") -> dict:
    """NEWS-HUNT MODE: news sebagai radar peluang, bukan bias arah global."""
    now = time.time()
    text = (news or "").lower()
    maps = [
        (["gold", "xau", "fed", "fomc", "cpi", "inflation", "nfp", "jobs report", "unemployment", "dollar", "usd", "yield"], ["XAUUSDT"]),
        (["silver", "xag"], ["XAGUSDT"]),
        (["bitcoin", "btc", "etf", "microstrategy"], ["BTCUSDT"]),
        (["ethereum", "eth"], ["ETHUSDT"]),
        (["bnb", "binance", "cz"], ["BNBUSDT"]),
        (["solana", "sol"], ["SOLUSDT"]),
        (["chainlink", "link"], ["LINKUSDT"]),
        (["crypto", "market", "liquidation", "sec", "lawsuit", "hack", "exploit"], ["BTCUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT"]),
    ]
    danger_words = ["fomc", "cpi", "inflation", "nfp", "jobs report", "unemployment", "fed", "rate decision", "interest rate", "war", "attack", "hack", "exploit", "lawsuit", "sec", "ban", "crash", "liquidation"]
    hot = {}
    hits = []
    for kws, syms in maps:
        matched = [k for k in kws if k in text]
        if matched:
            hits.extend(matched)
            for sym in syms:
                hot.setdefault(sym, set()).update(matched)
    risk = "neutral"
    if any(w in text for w in danger_words):
        risk = "high"
    elif hot:
        risk = "medium"
    try:
        fscore = int((fng or {}).get("score", 50))
    except Exception:
        fscore = 50
    if fscore <= 10 or fscore >= 90:
        risk = "high" if risk != "neutral" else "medium"
        for sym in ["BTCUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT"]:
            hot.setdefault(sym, set()).add(f"FnG={fscore}")
    hot_pairs = []
    for sym, why in sorted(hot.items()):
        hot_pairs.append({
            "symbol": sym,
            "risk": risk,
            "allowed_sides": ["LONG", "SHORT"],
            "require_extra_confirm": risk in ("medium", "high"),
            "fast_scan": True,
            "reason": ", ".join(sorted(why))[:220]
        })
    signals = []
    if hot_pairs and (OPENAI_KEY or ANTHROPIC_KEY):
        try:
            prompt = (
                "You are a scalping signal scout. Based ONLY on the headlines and price snapshot, "
                "return STRICT JSON with key signals as a list. Do not force a trade. "
                "Each signal: symbol, side LONG/SHORT, confidence 0.0-1.0, reason. "
                "Only include candidates with confidence >= 0.60. Max 5 signals. "
                "Allowed symbols: BTCUSDT, BNBUSDT, SOLUSDT, LINKUSDT, XAUUSDT, XAGUSDT.\n\n"
                f"FearGreed: {fng}\n\nPrices:\n{prices}\n\nHeadlines:\n{news}\n\n"
                'Return JSON only like: {"signals":[{"symbol":"XAUUSDT","side":"LONG","confidence":0.62,"reason":"..."}]}'
            )
            ans = ask_ai(prompt).strip()
            m = re.search(r"\{.*\}", ans, re.S)
            if m:
                obj = json.loads(m.group(0))
                raw = obj.get("signals", [])
                if isinstance(raw, list):
                    for x in raw[:5]:
                        sym = str(x.get("symbol", "")).upper().strip()
                        side = str(x.get("side", "")).upper().strip()
                        conf = float(x.get("confidence", 0) or 0)
                        reason = str(x.get("reason", ""))[:220]
                        if sym and side in ("LONG", "SHORT") and conf >= 0.60:
                            signals.append({"symbol": sym, "side": side, "confidence": round(conf, 3), "reason": reason})
        except Exception:
            signals = []
    mode = "hunt" if hot_pairs else "normal"
    summary = f"NEWS-HUNT {mode.upper()} risk={risk}, hot_pairs={len(hot_pairs)}, scout_signals={len(signals)}"
    return {"ts": now, "ttl": int(_env("NEWS_HUNT_TTL_SECONDS", "1800")), "mode": mode, "risk": risk, "hot_pairs": hot_pairs, "signals": signals, "summary": summary}

def write_news_hunt(hunt: dict):
    try:
        NEWS_HUNT_FILE.parent.mkdir(exist_ok=True)
        NEWS_HUNT_FILE.write_text(json.dumps(hunt))
    except Exception as e:
        print(f"[AGENT] Failed to write news_hunt: {e}")


def analyze_news_bias(news: str, fng: dict) -> dict:
    """v10: Tentukan arah bias dari berita + Fear&Greed.

    Berita buruk -> bias SHORT, berita baik -> bias LONG.
    Return dict siap ditulis ke logs/news_bias.json.
    """
    text = (news or "").lower()
    bull_hits = sorted({kw.strip() for kw in NEWS_BULLISH if kw in text})
    bear_hits = sorted({kw.strip() for kw in NEWS_BEARISH if kw in text})
    score = len(bull_hits) - len(bear_hits)

    fscore = int(fng.get("score", 50))
    if fscore <= 25:    score -= 1   # extreme fear -> condong short
    elif fscore >= 75:  score += 1   # extreme greed -> condong long

    ai_dir = _ask_ai_news_direction(news) if (OPENAI_KEY or ANTHROPIC_KEY) else ""
    if ai_dir == "long":    score += 1
    elif ai_dir == "short": score -= 1

    thr = max(1, NEWS_BIAS_MIN_SCORE)
    if score >= thr:     bias = "long"
    elif score <= -thr:  bias = "short"
    else:                bias = "neutral"

    summary = (f"score={score} (bull {len(bull_hits)} vs bear {len(bear_hits)}, "
               f"FnG {fscore}, AI {ai_dir or '-'}) -> {bias.upper()}")
    return {
        "bias": bias, "score": score,
        "bullish": bull_hits, "bearish": bear_hits,
        "fng": fscore, "ai": ai_dir, "summary": summary,
        "ts": time.time(), "ttl": NEWS_BIAS_TTL,
        "updated": datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
    }


def write_news_bias(bias: dict):
    try:
        NEWS_BIAS_FILE.parent.mkdir(exist_ok=True)
        NEWS_BIAS_FILE.write_text(json.dumps(bias))
    except Exception as e:
        print(f"[AGENT] Failed to write news_bias: {e}")


def _ask_ai_regime(prices: str, fng: dict) -> str:
    """Tanya AI klasifikasi regime. Return trending_up|trending_down|ranging|high_volatility|""."""
    if not (OPENAI_KEY or ANTHROPIC_KEY):
        return ""
    prompt = (
        "Classify the CURRENT market regime for crypto.\n"
        f"Main prices:\n{prices}\n"
        f"Fear & Greed: {fng.get('score',50)}/100 ({fng.get('label','')}).\n\n"
        "Answer with ONLY one word from: trending_up, trending_down, ranging, high_volatility."
    )
    try:
        ans = ask_ai(prompt).strip().lower()
        for r in ("trending_up", "trending_down", "high_volatility", "ranging"):
            if r in ans:
                return r
    except Exception:
        pass
    return ""


def analyze_regime(prices: str, fng: dict, stats: dict) -> dict:
    """v10.1 (G): Tentukan regime pasar + rekomendasi tuning utk bot.

    Tulis logs/regime.json. Bot auto-tuning:
      - confluence_min_score lebih RENDAH saat trending -> jgn sampai entry bagus kelewat
      - confluence_min_score lebih TINGGI saat ranging/volatile -> hindari sinyal palsu
      - cooldown lebih pendek saat trending, lebih panjang saat choppy/volatile
    """
    fscore = int(fng.get("score", 50))
    regime = _ask_ai_regime(prices, fng)
    if not regime:  # fallback heuristik kalau AI gagal/timeout
        if fscore <= 20 or fscore >= 80:
            regime = "high_volatility"
        elif 40 <= fscore <= 60:
            regime = "ranging"
        else:
            regime = "trending_up" if fscore > 60 else "trending_down"

    base = REGIME_BASE_MIN
    if regime in ("trending_up", "trending_down"):
        conf_min, cd_trade, cd_loss = base - 0.5, 45, 150
    elif regime == "high_volatility":
        conf_min, cd_trade, cd_loss = base + 1.0, 90, 300
    else:  # ranging
        conf_min, cd_trade, cd_loss = base + 0.5, 75, 240
    conf_min = round(max(1.0, min(4.0, conf_min)), 1)

    label = {
        "trending_up": "📈 TRENDING UP", "trending_down": "📉 TRENDING DOWN",
        "ranging": "↔️ RANGING (sideways)", "high_volatility": "🌪️ HIGH VOLATILITY",
    }.get(regime, regime)
    summary = (f"{label} | FnG {fscore} -> confluence_min={conf_min}, "
               f"cooldown {cd_trade}/{cd_loss}s")
    return {
        "regime": regime,
        "confluence_min_score": conf_min,
        "cooldown_after_trade_seconds": cd_trade,
        "cooldown_after_loss_seconds": cd_loss,
        "fng": fscore, "label": label, "summary": summary,
        "ts": time.time(), "ttl": REGIME_TTL,
        "updated": datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
    }


def write_regime(regime: dict):
    try:
        REGIME_FILE.parent.mkdir(exist_ok=True)
        REGIME_FILE.write_text(json.dumps(regime))
    except Exception as e:
        print(f"[AGENT] Failed to write regime: {e}")


def _bias_line(news_bias) -> str:
    bias = (news_bias or {}).get("bias", "neutral")
    if bias == "short":
        return "🔻 AI bias: SHORT — bot focuses on SHORT signals (bad news)"
    if bias == "long":
        return "🔺 AI bias: LONG — bot focuses on LONG signals (good news)"
    return "⚖️ AI bias: NEUTRAL — bot stays two-way"


def list_models() -> list:
    """v10: Daftar model dari endpoint OpenAI-compatible (mis. Bluesminds /v1/models)."""
    if not OPENAI_KEY:
        return ["(OPENAI_API_KEY not set in .env)"]
    try:
        req = Request(f"{OPENAI_BASE_URL}/models",
                      headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {OPENAI_KEY}"})
        with urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        items = data.get("data") if isinstance(data, dict) else data
        models = []
        for m in (items or []):
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if mid:
                models.append(mid)
        return models or ["(endpoint returned no models)"]
    except Exception as e:
        return [f"(error fetching models: {e})"]


def load_agent_state() -> dict:
    if not AGENT_STATE.exists(): return {"last_report_ts": 0, "restarts": 0}
    try: return json.loads(AGENT_STATE.read_text())
    except Exception: return {"last_report_ts": 0, "restarts": 0}

def save_agent_state(s: dict):
    AGENT_STATE.parent.mkdir(exist_ok=True)
    AGENT_STATE.write_text(json.dumps(s))


# ── Main Agent Loop ───────────────────────────────────────────────────────────
def _account_balance():
    """v12 (9): Saldo margin futures (None kalau dry-run / tanpa API key)."""
    try:
        from bot.config import Settings
        from bot.exchange_binance import BinanceFuturesClient
        st = Settings()
        if getattr(st, "dry_run", False) or not getattr(st, "api_key", "") or not getattr(st, "api_secret", ""):
            return None
        client = BinanceFuturesClient(st)
        try:
            client.sync_time()
        except Exception:
            pass
        b = client.get_balances()
        return float(b.get("margin_balance") or b.get("wallet") or 0.0)
    except Exception:
        return None


def build_morning_briefing() -> str:
    """v12 (9): Ringkasan 24 jam dari trade journal -> dikirim ke Telegram tiap pagi."""
    from bot.trade_journal import read_trades

    def _f(r, k):
        try:
            return float(r.get(k, 0) or 0)
        except Exception:
            return 0.0

    now_epoch = datetime.now(timezone.utc).timestamp()
    rows = []
    for r in read_trades(1000):
        try:
            if (now_epoch - float(r.get("ts", 0) or 0)) <= 24 * 3600:
                rows.append(r)
        except Exception:
            continue

    total   = len(rows)
    wins    = sum(1 for r in rows if _f(r, "realized") > 0)
    losses  = total - wins
    longs   = sum(1 for r in rows if (r.get("side") or "").upper() == "LONG")
    shorts  = sum(1 for r in rows if (r.get("side") or "").upper() == "SHORT")
    net     = sum(_f(r, "realized") for r in rows)
    durs    = [_f(r, "duration_min") for r in rows]
    avg_dur = (sum(durs) / len(durs)) if durs else 0.0
    wr      = (wins / total * 100.0) if total else 0.0

    by_pair: dict = {}
    for r in rows:
        s = r.get("symbol") or "?"
        by_pair[s] = by_pair.get(s, 0.0) + _f(r, "realized")
    best_pair  = max(by_pair.items(), key=lambda x: x[1]) if by_pair else None
    worst_pair = min(by_pair.items(), key=lambda x: x[1]) if by_pair else None

    bal     = _account_balance()
    emoji   = "\U0001f4c8" if net >= 0 else "\U0001f4c9"
    now_wib = datetime.now(WIB).strftime("%d %b %Y %H:%M")
    L = [
        f"\U0001f305 <b>MORNING BRIEFING</b> — {now_wib} WIB",
        f"{'─' * 28}",
        f"{emoji} Net PnL : <b>{net:+.4f} USDT</b>",
        f"\U0001f3af Winrate : {wr:.1f}% ({wins}W/{losses}L)",
        f"\U0001f501 Entry   : {total} trades",
        f"\U0001f7e2 Long {longs}  |  \U0001f534 Short {shorts}",
        f"\u2705 Profit {wins}  |  \u274c Loss {losses}",
        f"\u23f1\ufe0f Avg duration : {avg_dur:.0f} min",
    ]
    if best_pair:
        L.append(f"\U0001f3c6 Best  : {best_pair[0]} ({best_pair[1]:+.4f})")
    if worst_pair and (not best_pair or worst_pair[0] != best_pair[0]):
        L.append(f"\u26a0\ufe0f Worst : {worst_pair[0]} ({worst_pair[1]:+.4f})")
    if bal is not None:
        L.append(f"\U0001f4b0 Balance : {bal:.2f} USDT")
    if total == 0:
        L.append("\u2139\ufe0f No trades in the last 24 hours.")
    # v14 (C7+D13): metrik performa proper + Monte Carlo robustness (all-time journal)
    try:
        from bot.metrics import compute_metrics, format_metrics
        L.append("")
        L.append(format_metrics(compute_metrics(500)))
    except Exception as _e:
        print(f"[AGENT] metrics failed: {_e}")
    try:
        from tools.monte_carlo import run_monte_carlo, format_report, _pnls
        L.append("")
        L.append(format_report(run_monte_carlo(_pnls(1000), runs=2000)))
    except Exception as _e:
        print(f"[AGENT] montecarlo failed: {_e}")
    return "\n".join(L)


def _maybe_morning_briefing(a_state: dict) -> None:
    """v12 (9): Kirim morning briefing 1x/hari setelah jam target (WIB)."""
    if not MORNING_BRIEFING_ENABLE:
        return
    now_wib = datetime.now(WIB)
    today   = now_wib.strftime("%Y-%m-%d")
    if now_wib.hour < MORNING_BRIEFING_HOUR:
        return
    if a_state.get("last_briefing_date") == today:
        return
    try:
        if tg_send(build_morning_briefing()):
            a_state["last_briefing_date"] = today
            save_agent_state(a_state)
            print(f"[AGENT] \U0001f305 Morning briefing sent ({today})")
            try:
                run_daily_review(send=True)   # v14: post-trade review harian otomatis
            except Exception as _e:
                print(f"[AGENT] Daily review failed: {_e}")
    except Exception as e:
        print(f"[AGENT] Morning briefing failed: {e}")


def run_daily_review(send: bool = True) -> str:
    """v14 (AI Agent Priority): Post-trade review HARIAN.

    Baca trade journal -> temukan POLA LOSS (pair terburuk, jam WIB terburuk,
    arah long vs short) -> minta AI kasih saran tuning konkret -> kirim Telegram.
    READ-ONLY: TIDAK mengubah .env. Saran ditampilkan biar kamu yang putuskan.
    """
    from bot.trade_journal import read_trades, recent_summary

    def _f(r, k):
        try:
            return float(r.get(k, 0) or 0)
        except Exception:
            return 0.0

    now_epoch = datetime.now(timezone.utc).timestamp()
    rows = [r for r in read_trades(1000) if (now_epoch - _f(r, "ts")) <= 24 * 3600]
    total = len(rows)
    if total == 0:
        msg = ("\U0001f50e <b>DAILY REVIEW</b>\n"
               "No trades in the last 24 hours \u2014 no patterns to analyze.")
        if send:
            tg_send(msg)
        print("[AGENT] Daily review: no trades.")
        return msg

    losses = [r for r in rows if _f(r, "realized") < 0]
    wins   = [r for r in rows if _f(r, "realized") > 0]

    loss_by_pair: dict = {}
    for r in losses:
        s = r.get("symbol") or "?"
        loss_by_pair[s] = loss_by_pair.get(s, 0.0) + _f(r, "realized")
    worst_pairs = sorted(loss_by_pair.items(), key=lambda x: x[1])[:3]

    loss_by_hour: dict = {}
    for r in losses:
        try:
            h = datetime.fromtimestamp(_f(r, "ts"), WIB).hour
            loss_by_hour[h] = loss_by_hour.get(h, 0) + 1
        except Exception:
            continue
    worst_hours = sorted(loss_by_hour.items(), key=lambda x: -x[1])[:3]

    long_loss  = sum(1 for r in losses if (r.get("side") or "").upper() == "LONG")
    short_loss = sum(1 for r in losses if (r.get("side") or "").upper() == "SHORT")
    net = sum(_f(r, "realized") for r in rows)

    facts = (
        f"Total {total} trades | {len(wins)}W/{len(losses)}L | net {net:+.4f} USDT\n"
        "Loss per pair (worst): "
        + (", ".join(f"{p} {v:+.4f}" for p, v in worst_pairs) or "-") + "\n"
        "Hours (WIB) with most losses: "
        + (", ".join(f"{h}:00 ({n}x)" for h, n in worst_hours) or "-") + "\n"
        f"Loss by direction: LONG {long_loss} vs SHORT {short_loss}"
    )

    ai_text = ""
    if OPENAI_KEY or ANTHROPIC_KEY:
        prompt = (
            "You are a post-trade analyst for a scalping bot. From the loss FACTS below, give "
            "MAX 4 concrete & SAFE tuning suggestions (e.g. avoid hour X, reduce size on pair Y, "
            "raise the threshold, cut the direction that loses most). DO NOT suggest raising leverage. "
            "English, concise, use bullet points.\n\nFACTS:\n" + facts
        )
        ai_text = ask_ai(prompt)

    now_wib = datetime.now(WIB).strftime("%d %b %Y %H:%M")
    _hr = "\u2500" * 28
    msg = (f"\U0001f50e <b>DAILY REVIEW</b> \u2014 {now_wib} WIB\n"
           f"{_hr}\n{facts}\n")
    if ai_text:
        msg += f"\n\U0001f9e0 <b>AI tuning suggestions:</b>\n{ai_text}\n"
    _rs = recent_summary(10)
    if _rs:
        msg += f"\n\U0001f4d2 {_rs}"
    if send:
        tg_send(msg)
    print("[AGENT] Daily review sent.")
    return msg


def run_once(force_report: bool = False):
    print(f"[AGENT] {datetime.now(WIB).strftime('%H:%M WIB')} — Running analysis...")
    Path("logs").mkdir(exist_ok=True)
    a_state = load_agent_state()

    # 1. Cek kesehatan bot
    running = bot_is_running()
    if not running:
        print("[AGENT] ⚠️  Bot not running! Trying to restart...")
        ok = restart_bot()
        a_state["restarts"] = a_state.get("restarts", 0) + 1
        save_agent_state(a_state)
        msg = (f"\u26a0\ufe0f <b>AUTO-RESTART</b>\n"
               f"Bot down detected. {'Restart OK ✅' if ok else 'Restart FAILED ❌'}\n"
               f"Total restarts: {a_state['restarts']}")
        tg_send(msg)
        if not ok:
            return

    # 2. Kumpulkan data
    log_text = read_recent_logs(24)
    stats    = parse_trades_from_log(log_text)
    _bn = fetch_binance_stats(24)  # v10: pakai realized PnL Binance kalau tersedia
    if _bn:
        stats = _bn
    state    = read_state()
    fng      = fetch_fear_greed()
    news     = fetch_crypto_news()
    prices   = fetch_prices()

    # NEWS-HUNT MODE: news sebagai radar peluang, bukan bias arah global
    news_hunt = analyze_news_hunt(news, fng, prices)
    write_news_hunt(news_hunt)
    print(f"[AGENT] News hunt: {news_hunt.get('summary', '-')}")

    # v10 legacy: tetap tulis news_bias.json untuk kompatibilitas, tapi bot utama tetap NEWS_BIAS_ENABLE=false
    news_bias = analyze_news_bias(news, fng)
    write_news_bias(news_bias)
    print(f"[AGENT] News bias: {news_bias['summary']}")

    # v10.1 (G): Klasifikasi regime pasar -> tulis tuning utk bot
    regime = {}
    if REGIME_ENABLE:
        try:
            regime = analyze_regime(prices, fng, stats)
            write_regime(regime)
            print(f"[AGENT] Regime: {regime['summary']}")
        except Exception as e:
            print(f"[AGENT] Regime failed: {e}")

    # v11 (4): Session-stats (winrate per jam WIB) dari jurnal -> bot auto-adaptasi
    try:
        from bot.trade_journal import compute_session_stats, write_session_stats
        _ss = compute_session_stats()
        write_session_stats(_ss)
        print(f"[AGENT] Session-stats: {_ss['samples']} trade, adjust={_ss['hour_adjust']}")
    except Exception as e:
        print(f"[AGENT] session-stats failed: {e}")


    # 4. Kirim laporan (tiap 6 jam atau force)
    hours_since = (time.time() - a_state.get("last_report_ts", 0)) / 3600
    should_report = force_report or hours_since >= 6

    if should_report:
        # Build & kirim laporan
        now_wib  = datetime.now(WIB).strftime("%d %b %Y %H:%M")
        wr_emoji = "✅" if stats["winrate"] >= 60 else ("⚠️" if stats["winrate"] >= 40 else "❌")
        fng_emoji = "😱" if fng["score"] < 25 else ("😨" if fng["score"] < 40 else
                    "😐" if fng["score"] < 60 else ("😊" if fng["score"] < 75 else "🤑"))

        # Minta analisis dari AI
        print("[AGENT] Requesting AI analysis...")
        prompt   = build_analysis_prompt(log_text, stats, news, fng, prices, state)
        ai_text  = ask_ai(prompt)

        if stats.get("source") == "binance":
            _src = "🟢 sumber: Binance (realized PnL)"
            perf_block = (
                f"  Trades  : {stats['total_entries']} done"
                + (f" | {stats['open_positions']} open" if stats.get('open_positions') else "")
                + "\n"
                f"  Win/Loss: {stats['wins']}/{stats['losses']}\n"
                f"  Winrate : {stats['winrate']}% {wr_emoji}\n"
                f"  Net PnL : {stats['net']:+.4f} USDT\n"
                f"  {_src}\n"
            )
        else:
            perf_block = (
                f"  Entry   : {stats['total_entries']} trades\n"
                f"  Win/Loss: {stats['wins']}/{stats['losses']}\n"
                f"  Winrate : {stats['winrate']}% {wr_emoji}\n"
            )

        report = (
            f"🤖 <b>AI AGENT REPORT</b> — {now_wib} WIB\n"
            f"{'─'*32}\n"
            f"\n📊 <b>BOT PERFORMANCE (24h):</b>\n"
            f"{perf_block}"
            f"\n💹 <b>MARKET PRICES:</b>\n  {prices}\n"
            f"\n{fng_emoji} <b>Fear & Greed:</b> {fng['score']}/100 ({fng['label']})\n"
            f"\n🧠 <b>AI ANALYSIS:</b>\n{ai_text}\n"
        )
        if regime:
            report += f"\n🧭 <b>MARKET REGIME:</b>\n  {regime['summary']}\n"
        try:
            from bot.trade_journal import recent_summary
            _rs = recent_summary(10)
            if _rs:
                report += f"\n📒 <b>POST-TRADE:</b> {_rs}\n"
        except Exception:
            pass

        report += f"\n\n🤖 Bot status: {'✅ RUNNING' if running else '⚠️ RESTARTED'}"

        tg_send(report)
        a_state["last_report_ts"] = time.time()
        save_agent_state(a_state)
        print(f"[AGENT] ✅ Report sent to Telegram")
    else:
        print(f"[AGENT] Next report in {6 - hours_since:.1f} hours")

    # v12 (9): Morning Briefing harian (07:00 WIB)
    _maybe_morning_briefing(a_state)

    # 5. Alert berita penting + arah bias
    _check_news_alert(news, news_bias)

    print(f"[AGENT] Done. Next run in {INTERVAL_MIN} minutes.")


def _check_news_alert(news: str, news_bias: dict = None):
    """Alert kalau ada berita high-impact."""
    keywords_danger = [
        "fed", "fomc", "rate hike", "rate cut", "cpi", "inflation",
        "sec", "banned", "hack", "exploit", "crash", "dump", "liquidation",
        "gdp", "jobs report", "unemployment",
    ]
    news_lower = news.lower()
    hits = [kw for kw in keywords_danger if kw in news_lower]
    if hits:
        alert = (
            f"⚠️ <b>NEWS ALERT!</b>\n"
            f"High-impact news detected:\n"
            f"Keywords: {', '.join(hits[:3])}\n"
            f"\nHeadline:\n{news[:300]}\n"
            f"\n💡 Tip: Consider reducing size or following the bias direction"
            f"\n{_bias_line(news_bias)}"
        )
        tg_send(alert)
        print(f"[AGENT] ⚠️  News alert sent: {hits}")


# ── Entry Point ────────────��──────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Agent for Trading Bot v14")
    parser.add_argument("--once",   action="store_true", help="Run once then exit")
    parser.add_argument("--report", action="store_true", help="Force-send a report now")
    parser.add_argument("--models", action="store_true", help="List models from the AI endpoint (e.g. Bluesminds /v1/models)")
    parser.add_argument("--metrics", action="store_true", help="Print proper performance metrics (PF/expectancy/maxDD/Sharpe) from journal")
    parser.add_argument("--montecarlo", action="store_true", help="Run Monte Carlo robustness simulation from journal")
    parser.add_argument("--review", action="store_true", help="Daily post-trade review: loss patterns + tuning suggestions (send Telegram)")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════╗
║     AI AGENT — Trading Bot v14          ║
║  Interval  : {INTERVAL_MIN} min                    ║
║  AI Engine : {(OPENAI_MODEL + ' @ ' + OPENAI_BASE_URL.replace('https://','')) if OPENAI_KEY else ('Claude' if ANTHROPIC_KEY else 'Local (no API key)')}     ║
║  Telegram  : {'active ✅' if TG_TOKEN else 'inactive ❌'}              ║
╚══════════════════════════════════════════╝
    """)

    if args.models:
        print(f"[AGENT] Models from {OPENAI_BASE_URL}/models:")
        for _m in list_models():
            print(f"  • {_m}")
        sys.exit(0)

    if args.metrics:
        from bot.metrics import compute_metrics, format_metrics
        print(format_metrics(compute_metrics(500)))
        sys.exit(0)

    if args.montecarlo:
        from tools.monte_carlo import run_monte_carlo, format_report, _pnls
        print(format_report(run_monte_carlo(_pnls(1000), runs=5000)))
        sys.exit(0)

    if args.review:
        run_daily_review(send=True)
        sys.exit(0)

    if args.once or args.report:
        run_once(force_report=args.report)
    else:
        # Loop terus menerus
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[AGENT] Loop error: {e}")
            print(f"[AGENT] Sleeping {INTERVAL_MIN} minutes...")
            time.sleep(INTERVAL_MIN * 60)


# THREE_AI_ACTIVE_HUNTER_V1
# Safe live loops: DeepSeek = fast hunter radar, Kimi = heavy context analyst.
# No direct orders. Only writes JSON files for bot to read.
def _three_ai_env_bool(name, default="false"):
    import os
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "y", "on")

def _three_ai_env_float(name, default):
    import os
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)

def _three_ai_env_int(name, default):
    import os
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return int(default)

def _three_ai_symbols():
    import os
    raw = os.getenv("SYMBOLS", "BTCUSDT,BNBUSDT,SOLUSDT,LINKUSDT,XAUUSDT,XAGUSDT")
    return [x.strip().upper() for x in raw.split(",") if x.strip()]

def _three_ai_write_json(path, data):
    import json, os, tempfile
    from pathlib import Path
    pp = Path(path)
    pp.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("no_direct_order", True)
    data.setdefault("source", "three_ai_active_hunter_v1")
    tmp = pp.with_suffix(pp.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(pp)

def _three_ai_read_json(path, default=None):
    import json
    from pathlib import Path
    try:
        pp = Path(path)
        if not pp.exists():
            return default
        return json.loads(pp.read_text())
    except Exception:
        return default

def _three_ai_now_iso():
    import datetime
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _three_ai_simple_radar(kind):
    # Fallback local radar so JSON always updates even if external API fails.
    import random, time
    symbols = _three_ai_symbols()
    pairs = {}
    for i, sym in enumerate(symbols):
        seed = (int(time.time() // 600) + sum(ord(c) for c in sym) + (17 if kind == "kimi" else 3)) % 100
        side = "LONG" if seed % 3 == 0 else ("SHORT" if seed % 3 == 1 else "WAIT")
        score = round(5.0 + (seed % 35) / 10.0, 1)
        if side == "WAIT":
            score = round(4.0 + (seed % 20) / 10.0, 1)
        pairs[sym] = {
            "side": side,
            "score": score,
            "confidence": min(0.85, max(0.35, score / 10.0)),
            "reason": f"{kind} fallback radar; safe advisory only; no direct order"
        }
    return pairs

def _three_ai_call_openai_compatible(base_url, api_key, model, messages, timeout=35):
    import json, urllib.request
    if not base_url or not api_key or not model:
        raise RuntimeError("missing base_url/api_key/model")
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 900,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    return obj["choices"][0]["message"]["content"]

def _three_ai_call_cloudflare_kimi(prompt, timeout=45):
    import os, json, urllib.request
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
    model = os.getenv("CLOUDFLARE_KIMI_MODEL", os.getenv("AI_ANALYST_MODEL", "@cf/moonshotai/kimi-k2.6")).strip()
    if not account or not token or not model:
        raise RuntimeError("missing cloudflare kimi credentials")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
    body = json.dumps({
        "messages": [
            {"role": "system", "content": "You are a trading market context analyst. Return compact JSON only. No direct orders."},
            {"role": "user", "content": prompt}
        ]
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    result = obj.get("result", {})
    if isinstance(result, dict):
        if "response" in result:
            return result["response"]
        if "text" in result:
            return result["text"]
    return json.dumps(result)

def _three_ai_extract_json(text):
    import json, re
    if not text:
        raise RuntimeError("empty response")
    t = str(text).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise RuntimeError("no json object in response")
    return json.loads(m.group(0))

def three_ai_deepseek_scout_once():
    import os
    out_file = os.getenv("AI_DEEPSEEK_SCOUT_FILE", "logs/deepseek_scout.json")
    symbols = _three_ai_symbols()
    data = {
        "updated_at": _three_ai_now_iso(),
        "role": "deepseek_fast_hunter",
        "mode": "live_loop_json_safe",
        "symbols": symbols,
        "pairs": {},
        "status": "fallback",
        "error": None,
    }
    try:
        base = os.getenv("AI_BACKUP_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "")).strip()
        key = os.getenv("AI_BACKUP_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")).strip()
        model = os.getenv("AI_BACKUP_MODEL", os.getenv("DEEPSEEK_MODEL", "")).strip()
        prompt = (
            "Return JSON only. You are DeepSeek fast hunter for a futures scalper. "
            "No direct orders. For each symbol choose side LONG/SHORT/WAIT, score 0-10, confidence 0-1, reason short. "
            f"Symbols: {symbols}. "
            "Focus on opportunity radar, fresh momentum, avoid chasing."
        )
        txt = _three_ai_call_openai_compatible(
            base, key, model,
            [
                {"role": "system", "content": "Return JSON only. No direct orders. Safe advisory radar."},
                {"role": "user", "content": prompt},
            ],
            timeout=35,
        )
        obj = _three_ai_extract_json(txt)
        pairs = obj.get("pairs", obj.get("symbols", obj))
        if isinstance(pairs, dict):
            data["pairs"] = pairs
            data["status"] = "ok"
        else:
            raise RuntimeError("invalid pairs format")
    except Exception as e:
        data["error"] = str(e)
        data["pairs"] = _three_ai_simple_radar("deepseek")
    _three_ai_write_json(out_file, data)
    return data

def three_ai_kimi_analyst_once():
    import os
    out_file = os.getenv("AI_KIMI_ANALYST_FILE", "logs/kimi_analyst.json")
    symbols = _three_ai_symbols()
    data = {
        "updated_at": _three_ai_now_iso(),
        "role": "kimi_context_brain",
        "mode": "live_loop_json_safe",
        "symbols": symbols,
        "market_regime": "unknown",
        "risk": "medium",
        "pairs": {},
        "warnings": {},
        "status": "fallback",
        "error": None,
    }
    try:
        prompt = (
            "Return JSON only. You are Kimi heavy analyst for scalping futures. "
            "No direct orders. Analyze market context/regime/exhaustion. "
            "For each symbol provide preferred side LONG/SHORT/WAIT, score 0-10, warning short. "
            f"Symbols: {symbols}. "
            "Focus on avoiding long at top, short at bottom, choppy regime."
        )
        txt = _three_ai_call_cloudflare_kimi(prompt, timeout=45)
        obj = _three_ai_extract_json(txt)
        data["market_regime"] = obj.get("market_regime", obj.get("regime", "unknown"))
        data["risk"] = obj.get("risk", "medium")
        data["warnings"] = obj.get("warnings", {})
        pairs = obj.get("pairs", obj.get("preferred", {}))
        if isinstance(pairs, dict):
            data["pairs"] = pairs
        data["status"] = "ok"
    except Exception as e:
        data["error"] = str(e)
        data["pairs"] = _three_ai_simple_radar("kimi")
    _three_ai_write_json(out_file, data)
    return data

def three_ai_active_hunter_tick():
    import os, time
    state_path = "logs/three_ai_active_hunter_state.json"
    st = _three_ai_read_json(state_path, {}) or {}
    now = time.time()

    if _three_ai_env_bool("AI_DEEPSEEK_SCOUT_ENABLE", "true"):
        interval = _three_ai_env_int("AI_DEEPSEEK_SCOUT_INTERVAL_SEC", 600)
        if now - float(st.get("deepseek_last_ts", 0)) >= interval:
            try:
                d = three_ai_deepseek_scout_once()
                print(f"[3AI] DeepSeek scout updated status={d.get('status')} pairs={len(d.get('pairs', {}))}", flush=True)
            except Exception as e:
                print(f"[3AI] DeepSeek scout err: {e}", flush=True)
            st["deepseek_last_ts"] = now

    if _three_ai_env_bool("AI_KIMI_ANALYST_ENABLE", "true"):
        interval = _three_ai_env_int("AI_KIMI_ANALYST_INTERVAL_SEC", 1800)
        if now - float(st.get("kimi_last_ts", 0)) >= interval:
            try:
                k = three_ai_kimi_analyst_once()
                print(f"[3AI] Kimi analyst updated status={k.get('status')} pairs={len(k.get('pairs', {}))}", flush=True)
            except Exception as e:
                print(f"[3AI] Kimi analyst err: {e}", flush=True)
            st["kimi_last_ts"] = now

    _three_ai_write_json(state_path, st)

def three_ai_active_hunter_background():
    import threading, time
    def _loop():
        while True:
            try:
                three_ai_active_hunter_tick()
            except Exception as e:
                print(f"[3AI] active hunter loop err: {e}", flush=True)
            time.sleep(30)
    t = threading.Thread(target=_loop, name="three_ai_active_hunter_v1", daemon=True)
    t.start()
    print("[3AI] Active Hunter v1 background loop started", flush=True)

try:
    if _three_ai_env_bool("AI_COMMITTEE_ENABLE", "true"):
        three_ai_active_hunter_background()
except Exception as _three_ai_boot_e:
    print(f"[3AI] Active Hunter boot err: {_three_ai_boot_e}", flush=True)

