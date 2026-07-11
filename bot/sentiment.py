"""
sentiment.py — Fear & Greed Index + News Sentiment Filter

Sumber data GRATIS, tidak butuh API key:
  1. Alternative.me Fear & Greed Index (update harian)
  2. CoinDesk RSS headline keyword scoring

Cara kerja:
  - Skor 0-100: 0=Extreme Fear, 50=Neutral, 100=Extreme Greed
  - Bot pakai filter:
      Extreme Fear  (<=5) → skip LONG entry
      Extreme Greed (>95) → skip SHORT entry
      Range normal  (25-75) → bebas entry dua arah
"""
from __future__ import annotations
import json
import time
from urllib.request import urlopen, Request
from urllib.error import URLError
from datetime import datetime

# ── Konstanta ─────────────────────────────────────────────────────────────────
FNG_URL     = "https://api.alternative.me/fng/?limit=1&format=json"
CACHE_TTL   = 3600  # refresh tiap 1 jam (bukan tiap loop)

_cache: dict = {"score": 50, "label": "Neutral", "ts": 0.0}


def get_fear_greed() -> dict:
    """
    Return dict:
      {
        "score": 42,
        "label": "Fear",        # Extreme Fear / Fear / Neutral / Greed / Extreme Greed
        "signal_filter": "ok",  # "skip_long" | "skip_short" | "ok"
        "ok": True
      }
    """
    global _cache
    now = time.time()
    if now - _cache["ts"] < CACHE_TTL and _cache["ts"] > 0:
        return _build_result(_cache["score"], _cache["label"])

    try:
        req = Request(FNG_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        entry = data["data"][0]
        score = int(entry["value"])
        label = entry["value_classification"]
        _cache = {"score": score, "label": label, "ts": now}
        return _build_result(score, label)
    except (URLError, KeyError, Exception) as e:
        # Kalau gagal fetch → neutral, tetap bisa entry
        return _build_result(50, "Neutral (offline)", ok=False)


def _build_result(score: int, label: str, ok: bool = True) -> dict:
    if score <= 5:
        sf = "skip_long"    # Extreme Fear → jangan LONG (market mau turun)
    elif score > 95:
        sf = "skip_short"   # Extreme Greed → jangan SHORT (market mau naik)
    else:
        sf = "ok"            # Normal → bebas entry
    return {"score": score, "label": label, "signal_filter": sf, "ok": ok}


def sentiment_emoji(score: int) -> str:
    if score <= 5:  return "😱"
    if score < 45:  return "😰"
    if score < 55:  return "😐"
    if score < 75:  return "😄"
    return "🤑"


def log_sentiment(sent: dict, logger=None) -> str:
    score = sent["score"]
    label = sent["label"]
    sf    = sent["signal_filter"]
    emoji = sentiment_emoji(score)
    msg   = f"[SENTIMENT] {emoji} Fear&Greed={score} ({label})"
    if sf == "skip_long":
        msg += " → SKIP LONG entry (Extreme Fear)"
    elif sf == "skip_short":
        msg += " → SKIP SHORT entry (Extreme Greed)"
    else:
        msg += " → Two-way entry OK"
    if logger:
        logger.info(msg)
    return msg
