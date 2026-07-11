from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from .colors import pnl


@dataclass
class DailyPnL:
    realized: float = 0.0
    commission: float = 0.0
    funding: float = 0.0
    other: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0

    @property
    def net(self) -> float:
        return self.realized + self.commission + self.funding + self.other

    @property
    def win_rate(self) -> float:
        return 0.0 if self.trades == 0 else self.wins / self.trades * 100


def summarize_income(rows: list[dict[str, Any]]) -> DailyPnL:
    d = DailyPnL()
    for r in rows:
        typ = str(r.get("incomeType", "")).upper()
        val = float(r.get("income", 0) or 0)
        if typ == "REALIZED_PNL":
            d.realized += val
            d.trades += 1
            if val > 0: d.wins += 1
            elif val < 0: d.losses += 1
        elif typ == "COMMISSION":
            d.commission += val
        elif typ == "FUNDING_FEE":
            d.funding += val
        else:
            d.other += val
    return d


def format_daily(d: DailyPnL) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"Daily PnL {today} | Net={pnl(d.net, f'{d.net:+.4f} USDT')} | "
        f"Realized={pnl(d.realized, f'{d.realized:+.4f}')} | Commission={d.commission:+.4f} | "
        f"Funding={pnl(d.funding, f'{d.funding:+.4f}')} | Trades={d.trades} Wins={d.wins} Losses={d.losses} WinRate={d.win_rate:.2f}%"
    )
