from __future__ import annotations
"""v11 (4 & 5): Trade Journal + Session/Day Auto-Threshold + bahan Post-Trade Analyst.

Setiap trade selesai dicatat ke logs/trade_journal.csv. AI Agent menghitung
winrate per jam (WIB) & per hari -> tulis logs/session_stats.json dgn rekomendasi
delta threshold. Bot membaca rekomendasi itu (session_threshold_adjust) supaya
otomatis lebih ketat di jam jelek, lebih agresif di jam bagus.
"""
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

JOURNAL = Path("logs/trade_journal.csv")
SESSION_STATS = Path("logs/session_stats.json")
WIB = timezone(timedelta(hours=7))

FIELDS = ["ts", "datetime_wib", "symbol", "side", "realized", "roi_pct",
          "duration_min", "result", "score", "regime", "news_bias", "reason"]


def log_trade(row: dict):
    """Append satu baris trade ke CSV (buat header otomatis)."""
    try:
        JOURNAL.parent.mkdir(exist_ok=True)
        is_new = not JOURNAL.exists()
        with JOURNAL.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if is_new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in FIELDS})
    except Exception as e:
        print(f"[JOURNAL] write failed: {e}")


def read_trades(limit: int = 500) -> list:
    rows = []
    try:
        if not JOURNAL.exists():
            return rows
        with JOURNAL.open(newline="") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except Exception:
        pass
    return rows[-limit:]


def compute_session_stats(min_samples: int = 4) -> dict:
    """Winrate per jam (WIB) & per weekday + rekomendasi delta threshold."""
    rows = read_trades()
    by_hour: dict = {}
    by_day: dict = {}
    for r in rows:
        try:
            win = 1 if (r.get("result") or "").lower() == "win" else 0
            dt = datetime.fromtimestamp(float(r.get("ts", 0) or 0), WIB)
            by_hour.setdefault(dt.hour, []).append(win)
            by_day.setdefault(dt.weekday(), []).append(win)
        except Exception:
            continue

    def _wr(lst):
        return (sum(lst) / len(lst) * 100.0) if lst else 0.0

    hour_wr = {str(h): {"n": len(v), "wr": round(_wr(v), 1)} for h, v in by_hour.items()}
    day_wr  = {str(d): {"n": len(v), "wr": round(_wr(v), 1)} for d, v in by_day.items()}

    # Jam dgn winrate rendah -> naikin threshold (+0.5); tinggi -> turunin (-0.5).
    hour_adjust = {}
    for h, s in hour_wr.items():
        if s["n"] >= min_samples:
            if s["wr"] < 40:
                hour_adjust[h] = 0.5
            elif s["wr"] > 65:
                hour_adjust[h] = -0.5
    return {
        "hour_wr": hour_wr, "day_wr": day_wr, "hour_adjust": hour_adjust,
        "samples": len(rows), "ts": datetime.now(WIB).timestamp(),
        "updated": datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
    }


def write_session_stats(stats: dict):
    try:
        SESSION_STATS.parent.mkdir(exist_ok=True)
        SESSION_STATS.write_text(json.dumps(stats))
    except Exception as e:
        print(f"[JOURNAL] failed to write session_stats: {e}")


def session_threshold_adjust() -> float:
    """Dibaca bot: delta threshold confluence utk jam (WIB) saat ini."""
    try:
        if not SESSION_STATS.exists():
            return 0.0
        data = json.loads(SESSION_STATS.read_text())
        h = str(datetime.now(WIB).hour)
        return float((data.get("hour_adjust") or {}).get(h, 0.0))
    except Exception:
        return 0.0


def recent_summary(n: int = 10) -> str:
    """Ringkasan singkat utk laporan Post-Trade Analyst."""
    rows = read_trades(n)
    if not rows:
        return ""
    wins = sum(1 for r in rows if (r.get("result") or "").lower() == "win")
    losses = len(rows) - wins
    pnl = sum(float(r.get("realized", 0) or 0) for r in rows)
    return f"{len(rows)} trade terakhir: {wins}W/{losses}L | net {pnl:+.4f} USDT"
