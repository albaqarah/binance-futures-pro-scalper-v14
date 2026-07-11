"""
metrics.py — v14: Metrik performa proper dari trade journal.

Menghitung indikator kesehatan strategi yang BENAR (bukan cuma winrate):
  - Profit Factor, Expectancy, Payoff ratio
  - Max Drawdown (dari equity curve realized)
  - Sharpe & Sortino (per-trade)
  - Max consecutive losses, exposure per simbol

Dipakai oleh ai_agent.py (Morning Briefing) & tools/monte_carlo.py.
Pure stdlib + (opsional) tidak butuh pandas. ZERO efek ke jalur order live.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from math import sqrt
from typing import Any

from .trade_journal import read_trades


@dataclass
class PerfMetrics:
    n_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0          # %
    gross_pnl: float = 0.0         # sum realized (USDT)
    avg_pnl: float = 0.0           # expectancy per trade (USDT)
    gross_profit: float = 0.0      # sum trade menang
    gross_loss: float = 0.0        # sum |trade rugi|
    profit_factor: float = 0.0     # gross_profit / gross_loss
    avg_win: float = 0.0
    avg_loss: float = 0.0          # nilai positif (rata-rata kerugian)
    payoff_ratio: float = 0.0      # avg_win / avg_loss
    expectancy_r: float = 0.0      # ekspektasi dalam satuan R (payoff & winrate)
    max_drawdown: float = 0.0      # USDT, dari equity curve realized
    max_drawdown_pct: float = 0.0  # % dari puncak equity
    sharpe: float = 0.0            # per-trade, tanpa anualisasi
    sortino: float = 0.0
    max_consec_losses: int = 0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    by_symbol: dict = field(default_factory=dict)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_metrics(limit: int = 500, rows: list | None = None) -> PerfMetrics:
    """Hitung metrik dari journal. `realized` dianggap PnL bersih per trade (USDT)."""
    rows = rows if rows is not None else read_trades(limit)
    m = PerfMetrics()
    if not rows:
        return m

    pnls: list[float] = []
    sym_pnl: dict[str, list[float]] = {}
    for r in rows:
        val = _to_float(r.get("realized"))
        pnls.append(val)
        sym = (r.get("symbol") or "?").upper()
        sym_pnl.setdefault(sym, []).append(val)

    m.n_trades = len(pnls)
    wins_list = [p for p in pnls if p > 0]
    loss_list = [p for p in pnls if p < 0]
    m.wins = len(wins_list)
    m.losses = len(loss_list)
    m.win_rate = (m.wins / m.n_trades * 100.0) if m.n_trades else 0.0
    m.gross_pnl = sum(pnls)
    m.avg_pnl = m.gross_pnl / m.n_trades if m.n_trades else 0.0
    m.gross_profit = sum(wins_list)
    m.gross_loss = abs(sum(loss_list))
    m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else float("inf") if m.gross_profit > 0 else 0.0
    m.avg_win = (m.gross_profit / m.wins) if m.wins else 0.0
    m.avg_loss = (m.gross_loss / m.losses) if m.losses else 0.0
    m.payoff_ratio = (m.avg_win / m.avg_loss) if m.avg_loss > 0 else 0.0
    # Expectancy dalam R: (winrate*payoff) - (lossrate)
    wr = m.win_rate / 100.0
    m.expectancy_r = round(wr * m.payoff_ratio - (1 - wr), 4)
    m.best_trade = max(pnls)
    m.worst_trade = min(pnls)

    # Equity curve & max drawdown (realized, urut sesuai journal)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
    m.max_drawdown = round(max_dd, 4)
    m.max_drawdown_pct = round(max_dd_pct, 2)

    # Sharpe & Sortino per-trade (mean/std). Tanpa anualisasi — buat banding internal.
    n = len(pnls)
    mean = m.avg_pnl
    if n > 1:
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        std = sqrt(var)
        m.sharpe = round(mean / std, 3) if std > 0 else 0.0
        downside = [p for p in pnls if p < 0]
        if downside:
            dvar = sum(p ** 2 for p in downside) / len(downside)
            dstd = sqrt(dvar)
            m.sortino = round(mean / dstd, 3) if dstd > 0 else 0.0

    # Max consecutive losses
    streak = 0
    worst_streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    m.max_consec_losses = worst_streak

    # Breakdown per simbol
    by_sym = {}
    for sym, lst in sym_pnl.items():
        w = sum(1 for x in lst if x > 0)
        by_sym[sym] = {
            "n": len(lst),
            "wr": round(w / len(lst) * 100.0, 1) if lst else 0.0,
            "pnl": round(sum(lst), 4),
        }
    m.by_symbol = dict(sorted(by_sym.items(), key=lambda kv: kv[1]["pnl"]))

    # Bulatkan nilai utama
    for f in ("win_rate", "gross_pnl", "avg_pnl", "gross_profit", "gross_loss",
              "avg_win", "avg_loss", "payoff_ratio", "best_trade", "worst_trade"):
        setattr(m, f, round(getattr(m, f), 4))
    if m.profit_factor not in (float("inf"),):
        m.profit_factor = round(m.profit_factor, 3)
    return m


def format_metrics(m: PerfMetrics) -> str:
    """Ringkasan teks untuk Telegram / Morning Briefing."""
    if m.n_trades == 0:
        return "\U0001F4CA Metrics: no trades recorded in the journal yet."
    pf = "\u221E" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    verdict = _verdict(m)
    lines = [
        "\U0001F4CA PERFORMANCE METRICS (journal)",
        f"\u2022 Trades: {m.n_trades} | Win {m.wins} / Loss {m.losses} | WR {m.win_rate:.1f}%",
        f"\u2022 Net PnL: {m.gross_pnl:+.4f} USDT | Expectancy/trade: {m.avg_pnl:+.4f} USDT",
        f"\u2022 Profit Factor: {pf} | Payoff: {m.payoff_ratio:.2f} | Expectancy: {m.expectancy_r:+.3f} R",
        f"\u2022 Avg win: {m.avg_win:+.4f} | Avg loss: -{m.avg_loss:.4f}",
        f"\u2022 Max Drawdown: -{m.max_drawdown:.4f} USDT ({m.max_drawdown_pct:.1f}%)",
        f"\u2022 Sharpe: {m.sharpe} | Sortino: {m.sortino} | Max consecutive losses: {m.max_consec_losses}",
        f"\u2022 Best: {m.best_trade:+.4f} | Worst: {m.worst_trade:+.4f}",
        f"\u2022 Verdict: {verdict}",
    ]
    return "\n".join(lines)


def _verdict(m: PerfMetrics) -> str:
    pf = m.profit_factor
    if m.n_trades < 30:
        return "\u26A0\uFE0F sample < 30 trades, not yet statistically significant"
    if m.expectancy_r <= 0 or m.gross_pnl <= 0:
        return "\u274C NEGATIVE — strategy not profitable yet, don't increase size"
    if pf != float("inf") and pf < 1.2:
        return "\u26A0\uFE0F thin (PF<1.2) — likely to turn negative after fees/slippage"
    return "\u2705 positive — keep it up, re-evaluate every +50 trades"


if __name__ == "__main__":
    import json
    mm = compute_metrics()
    print(format_metrics(mm))
    print()
    print(json.dumps(asdict(mm), indent=2, default=str))
