"""
session_filter.py — Filter jam trading optimal (Asia/London/NY session)
Hanya entry saat likuiditas tinggi, hindari jam sepi.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

# Jam dalam UTC (WIB = UTC+7)
SESSIONS = [
    (0,  4),   # Asia open  07:00-11:00 WIB
    (8,  12),  # London     15:00-19:00 WIB
    (13, 20),  # NY         20:00-03:00 WIB
]

WIB = timezone(timedelta(hours=7))


def is_trading_session(enabled: bool = True) -> tuple[bool, str]:
    """
    Return (is_active, session_name)
    Kalau enabled=False, selalu return True (bypass filter).
    """
    if not enabled:
        return True, "ALL (filter off)"

    now_utc = datetime.now(timezone.utc)
    h = now_utc.hour
    m = now_utc.minute
    t = h + m / 60.0

    for start, end in SESSIONS:
        if start <= t < end:
            # label dalam WIB
            label = _session_label(start)
            return True, label

    now_wib = datetime.now(WIB)
    nxt = _next_session_wib(now_wib)
    return False, f"Sepi — sesi berikutnya {nxt}"


def _session_label(utc_start: int) -> str:
    wib = utc_start + 7
    if wib >= 24: wib -= 24
    labels = {0: "Asia 🇦🇺", 8: "London 🇬🇧", 13: "New York 🇺🇸"}
    return labels.get(utc_start, "Aktif")


def _next_session_wib(now_wib: datetime) -> str:
    """Jam sesi berikutnya dalam WIB."""
    sessions_wib = [(7, "Asia"), (15, "London"), (20, "NY")]
    h = now_wib.hour + now_wib.minute / 60.0
    for start_wib, name in sessions_wib:
        if h < start_wib:
            return f"{start_wib:02d}:00 WIB ({name})"
    return "07:00 WIB besok (Asia)"
