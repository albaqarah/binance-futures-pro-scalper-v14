"""
monte_carlo.py — v14 (D13): Uji robustness strategi via Monte Carlo.

Ambil urutan PnL per-trade dari journal, lalu acak-ulang (bootstrap) ribuan kali
untuk melihat SEBARAN hasil yang mungkin — bukan cuma satu jalur historis yang
kebetulan. Output: probabilitas profit, sebaran max drawdown, dan risk-of-ruin.

Kenapa penting: winrate historis tunggal gampang menipu. MC kasih lihat seberapa
sering strategi ini bisa BANGKRUT kalau urutan menang/kalah-nya beda.

Jalankan dari root project:
    python3 -m tools.monte_carlo --runs 5000 --start 100
"""
from __future__ import annotations
import argparse
import random
import sys
from pathlib import Path

# Pastikan root project ada di sys.path saat dijalankan langsung
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.trade_journal import read_trades  # noqa: E402


def _pnls(limit: int = 1000) -> list[float]:
    out = []
    for r in read_trades(limit):
        try:
            out.append(float(r.get("realized") or 0.0))
        except (TypeError, ValueError):
            continue
    return out


def _max_drawdown(seq: list[float]) -> float:
    equity = peak = 0.0
    mdd = 0.0
    for p in seq:
        equity += p
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return mdd


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def run_monte_carlo(pnls: list[float], runs: int = 5000, start_balance: float = 100.0,
                    seed: int = 42) -> dict:
    if not pnls:
        return {"error": "journal empty — no trades to simulate yet"}
    rng = random.Random(seed)
    n = len(pnls)
    finals: list[float] = []
    drawdowns: list[float] = []
    ruin = 0
    profit_runs = 0
    for _ in range(runs):
        sample = [pnls[rng.randrange(n)] for _ in range(n)]  # bootstrap with replacement
        # equity path + cek ruin (saldo <= 0)
        equity = start_balance
        busted = False
        path = []
        for p in sample:
            equity += p
            path.append(equity - start_balance)
            if equity <= 0:
                busted = True
                break
        final = equity - start_balance
        finals.append(final)
        drawdowns.append(_max_drawdown(sample))
        if busted:
            ruin += 1
        if final > 0:
            profit_runs += 1
    finals.sort()
    drawdowns.sort()
    return {
        "runs": runs,
        "n_trades_per_run": n,
        "start_balance": start_balance,
        "prob_profit_pct": round(profit_runs / runs * 100.0, 2),
        "risk_of_ruin_pct": round(ruin / runs * 100.0, 2),
        "final_pnl_median": round(_pct(finals, 0.50), 4),
        "final_pnl_p05": round(_pct(finals, 0.05), 4),
        "final_pnl_p95": round(_pct(finals, 0.95), 4),
        "max_dd_median": round(_pct(drawdowns, 0.50), 4),
        "max_dd_p95": round(_pct(drawdowns, 0.95), 4),
        "hist_total_pnl": round(sum(pnls), 4),
    }


def format_report(res: dict) -> str:
    if res.get("error"):
        return f"\U0001F3B2 Monte Carlo: {res['error']}"
    lines = [
        "\U0001F3B2 MONTE CARLO ROBUSTNESS",
        f"\u2022 {res['runs']} simulations × {res['n_trades_per_run']} trades (bootstrap), starting balance {res['start_balance']} USDT",
        f"\u2022 Profit probability: {res['prob_profit_pct']}%  |  Risk of ruin: {res['risk_of_ruin_pct']}%",
        f"\u2022 Final PnL — median {res['final_pnl_median']:+} | P5 {res['final_pnl_p05']:+} | P95 {res['final_pnl_p95']:+} USDT",
        f"\u2022 Max drawdown — median {res['max_dd_median']} | P95 {res['max_dd_p95']} USDT",
    ]
    rr = res["risk_of_ruin_pct"]
    pp = res["prob_profit_pct"]
    if rr >= 5:
        lines.append(f"\u2022 \u26A0\uFE0F Risk of ruin {rr}% HIGH — reduce size / leverage.")
    if pp < 50:
        lines.append("\u2022 \u274C Profit probability < 50% — negative edge, don't go live yet.")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Monte Carlo robustness from the trade journal")
    ap.add_argument("--runs", type=int, default=5000)
    ap.add_argument("--start", type=float, default=100.0)
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    res = run_monte_carlo(_pnls(args.limit), runs=args.runs, start_balance=args.start, seed=args.seed)
    print(format_report(res))
