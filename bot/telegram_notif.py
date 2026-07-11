"""
telegram_notif.py — Real-time notifications to your phone via Telegram Bot

Setup:
  1. Chat @BotFather on Telegram → /newbot → get the TOKEN
  2. Chat your bot → get the CHAT_ID via @userinfobot
  3. Put in .env: TELEGRAM_TOKEN=xxx TELEGRAM_CHAT_ID=xxx
"""
from __future__ import annotations
import json, time
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlencode

_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_last_send = 0.0
_MIN_INTERVAL = 1.5  # seconds between messages


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = bool(token and chat_id)

    def _send(self, text: str) -> bool:
        global _last_send
        if not self.enabled:
            return False
        # Rate limit
        gap = time.time() - _last_send
        if gap < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - gap)
        try:
            url  = _BASE.format(token=self.token)
            data = urlencode({
                "chat_id":    self.chat_id,
                "text":       text,
                "parse_mode": "HTML",
            }).encode()
            req = Request(url, data=data, method="POST")
            with urlopen(req, timeout=8) as r:
                resp = json.loads(r.read())
            _last_send = time.time()
            return resp.get("ok", False)
        except Exception:
            return False

    def entry(self, sym: str, side: str, qty: float, price: float,
              sl: float, tp: float, conf: float, fng: int = 50) -> None:
        arrow = "\U0001f7e2 LONG  \u25b2" if side == "LONG" else "\U0001f534 SHORT \u25bc"
        msg = (
            f"\u26a1 <b>ENTRY</b> — {sym}\n"
            f"{arrow}\n"
            f"\U0001f4cd Price  : <b>{price:.4f}</b>\n"
            f"\U0001f6d1 SL     : {sl:.4f}\n"
            f"\U0001f3af TP     : {tp:.4f}\n"
            f"\U0001f9e0 Conf   : {conf*100:.0f}%\n"
            f"\U0001f4ca F&G    : {fng}/100"
        )
        self._send(msg)

    def close_win(self, sym: str, side: str, pnl: float, roi: float, dur_min: int) -> None:
        msg = (
            f"\U0001f4b0 <b>PROFIT</b> — {sym}\n"
            f"Side   : {side}\n"
            f"PnL net: <b>+{pnl:.4f} USDT</b>\n"
            f"ROI    : +{roi:.2f}%\n"
            f"Duration: {dur_min} min"
        )
        self._send(msg)

    def close_loss(self, sym: str, side: str, pnl: float, roi: float, dur_min: int) -> None:
        msg = (
            f"\u274c <b>LOSS</b> — {sym}\n"
            f"Side   : {side}\n"
            f"PnL net: <b>{pnl:.4f} USDT</b>\n"
            f"ROI    : {roi:.2f}%\n"
            f"Duration: {dur_min} min"
        )
        self._send(msg)

    def breakeven(self, sym: str, roi: float) -> None:
        msg = f"\U0001f512 <b>SL+</b> — {sym} profit locked\nCurrent ROI: +{roi:.2f}%"
        self._send(msg)

    def daily_summary(self, net: float, trades: int, wr: float) -> None:
        emoji = "\U0001f4c8" if net >= 0 else "\U0001f4c9"
        msg = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"Net PnL : {'+'if net>=0 else ''}{net:.4f} USDT\n"
            f"Trades  : {trades}\n"
            f"Winrate : {wr:.1f}%"
        )
        self._send(msg)

    def alert(self, text: str) -> None:
        self._send(f"\u26a0\ufe0f {text}")


_instance: TelegramNotifier | None = None

def get_notifier(token: str = "", chat_id: str = "") -> TelegramNotifier:
    global _instance
    if _instance is None:
        _instance = TelegramNotifier(token, chat_id)
    return _instance
