from __future__ import annotations
import re
from datetime import datetime
from .colors import (
    GREEN, RED, YELLOW, CYAN, MAGENTA, GRAY, WHITE, BOLD, DIM, RESET,
    NEON_GREEN, NEON_CYAN, NEON_PINK, NEON_ORANGE, NEON_PURPLE,
    NEON_YELLOW, NEON_RED, NEON_BLUE,
    BG_BLACK,
    use_color, color, pnl as cpnl, side as cside,
)

_ANSI = re.compile(r"\033\[[0-9;]*m")
WIDTH = 76

# ── Box chars ─────────────────────────────────────────────────────────────────
# Outer double-line box
OTL = "\u2554"; OTR = "\u2557"; OBL = "\u255a"; OBR = "\u255d"
OH  = "\u2550"; OV  = "\u2551"
OML = "\u2560"; OMR = "\u2563"   # left/right mid-connector ╠ ╣
# Inner single-line divider
DL  = "\u255e"; DR  = "\u2561"; DH = "\u2500"  # ╞ ╡ ─


def _vlen(s: str) -> int:
    return len(_ANSI.sub("", s))


def _row(inner: str, pad_char: str = " ") -> str:
    pad = WIDTH - _vlen(inner)
    if pad < 0:
        # trim inner (strip trailing ANSI-invisible chars)
        inner = inner[:WIDTH]
        pad = 0
    return OV + " " + inner + pad_char * pad + " " + OV


def _center(text: str) -> str:
    vis = _vlen(text)
    total = WIDTH - vis
    left  = total // 2
    right = total - left
    return OV + " " * (left + 1) + text + " " * (right + 1) + OV


def _top() -> str:
    return OTL + OH * (WIDTH + 2) + OTR


def _mid() -> str:
    """Heavy mid-divider ╠══╣"""
    return OML + OH * (WIDTH + 2) + OMR


def _thin() -> str:
    """Thin mid-divider ╞──╡"""
    return DL + DH * (WIDTH + 2) + DR


def _bot() -> str:
    return OBL + OH * (WIDTH + 2) + OBR


def _bar(value: float, max_val: float, width: int = 20,
         fill: str = "█", empty: str = "░") -> str:
    """ASCII progress bar."""
    ratio = max(0.0, min(1.0, value / max_val if max_val else 0))
    filled = int(ratio * width)
    return fill * filled + empty * (width - filled)


def _pnl_bar(net: float, width: int = 16) -> str:
    """Signed PnL bar: positive = green blocks right, negative = red left."""
    c = use_color()
    ratio = max(-1.0, min(1.0, net / max(abs(net), 10) if net else 0))
    blocks = int(abs(ratio) * width)
    bar   = "█" * blocks + "░" * (width - blocks)
    if not c:
        return ("[+]" if net >= 0 else "[-]") + bar
    return (color(bar, BOLD + NEON_GREEN) if net >= 0 else color(bar, BOLD + NEON_RED))


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


# ── Sentiment badge ───────────────────────────────────────────────────────────
def _sent_badge(score: int, label: str, sf: str) -> str:
    c = use_color()
    if score < 25:
        emoji = "\U0001f631"; col = NEON_RED
    elif score < 45:
        emoji = "\U0001f630"; col = NEON_ORANGE
    elif score < 55:
        emoji = "\U0001f610"; col = NEON_YELLOW
    elif score < 75:
        emoji = "\U0001f604"; col = NEON_GREEN
    else:
        emoji = "\U0001f911"; col = NEON_PINK
    bar = _bar(score, 100, 14)
    bar_c = color(bar, col) if c else bar
    sf_txt = {
        "skip_long":  color(" ⚠ SKIP LONG",  BOLD + NEON_RED)    if c else " SKIP LONG",
        "skip_short": color(" ⚠ SKIP SHORT", BOLD + NEON_ORANGE)  if c else " SKIP SHORT",
        "ok":         color(" ✓ ALL OK",     NEON_GREEN)           if c else " ALL OK",
    }.get(sf, "")
    score_c = color(str(score), BOLD + col) if c else str(score)
    label_c = color(label, col) if c else label
    return f"{emoji} F&G {score_c}/100 [{bar_c}] {label_c}{sf_txt}"


# ── Main render ───────────────────────────────────────────────────────────────
def render(view: dict) -> str:
    c = use_color()
    L: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    L.append(_top())
    title = "⚡  BINANCE FUTURES PRO SCALPER  v14  HYBRID  ⚡"
    title_c = color(title, BOLD + NEON_CYAN) if c else title
    L.append(_center(title_c))

    sub = "ML Ensemble (LightGBM + RF) + Rule Fallback + AI Agent + Sentiment"
    sub_c = color(sub, DIM + NEON_PURPLE) if c else sub
    L.append(_center(sub_c))
    L.append(_mid())

    # ── Status bar ───────────────────────────────────────────────────────────
    mode = "◉ LIVE" if not view.get("dry_run") else "◎ DRY-RUN"
    net  = "⚡ REAL" if not view.get("testnet") else "✦ TESTNET"
    mode_c = color(mode, BOLD + NEON_GREEN  if "LIVE" in mode else BOLD + NEON_YELLOW) if c else mode
    net_c  = color(net,  BOLD + NEON_RED    if "REAL" in net  else BOLD + NEON_BLUE)   if c else net
    clock  = color(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"), NEON_CYAN) if c else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lev_c  = color(f"{view.get('leverage')}x", BOLD + NEON_ORANGE) if c else f"{view.get('leverage')}x"
    L.append(_row(f"  {mode_c}   {net_c}   Lev: {lev_c}   🕐 {clock}"))

    tf_c   = color(str(view.get('timeframes','')), NEON_YELLOW) if c else str(view.get('timeframes',''))
    _pairs = view.get("symbols") or view.get("pairs") or []
    _pairs_str = " ".join(_pairs) if _pairs else "—"
    pairs_c = color(_pairs_str, NEON_CYAN) if c else _pairs_str
    L.append(_row(f"  Timeframe: {tf_c}   Pairs: {pairs_c}"))
    L.append(_thin())

    # ── Balance ───────────────────────────────────────────────────────────────
    wallet  = view.get('wallet', 0.0)
    avail   = view.get('available', view.get('free', 0.0))
    mbal    = view.get('margin_balance', 0.0)
    upnl_a  = view.get('upnl_acct', 0.0)
    epct    = view.get('entry_pct', 0.10) * 100

    bal_label  = color("💰 BALANCE", BOLD + NEON_YELLOW) if c else "BALANCE"
    w_c = color(f"{wallet:.4f}",  BOLD + WHITE)     if c else f"{wallet:.4f}"
    a_c = color(f"{avail:.4f}",   NEON_GREEN)        if c else f"{avail:.4f}"
    m_c = color(f"{mbal:.4f}",    NEON_CYAN)         if c else f"{mbal:.4f}"
    u_c = cpnl(upnl_a, f"{upnl_a:+.4f}")            if c else f"{upnl_a:+.4f}"
    e_c = color(f"{epct:.0f}%",   NEON_ORANGE)       if c else f"{epct:.0f}%"
    L.append(_row(f"  {bal_label}   Wallet: {w_c} USDT   Avail: {a_c} USDT"))
    L.append(_row(f"  Margin Bal: {m_c} USDT   uPnL: {u_c} USDT   Entry size: {e_c}"))

    # ── Sentiment ─────────────────────────────────────────────────────────────
    sent = view.get("sentiment")
    if sent:
        L.append(_thin())
        sent_label = color("📡 MARKET SENTIMENT", BOLD + NEON_PURPLE) if c else "MARKET SENTIMENT"
        badge = _sent_badge(sent.get("score",50), sent.get("label","Neutral"), sent.get("signal_filter","ok"))
        L.append(_row(f"  {sent_label}   {badge}"))

    # ── Daily PnL ─────────────────────────────────────────────────────────────
    d = view.get("daily")
    if d is not None:
        L.append(_mid())
        pnl_label = color("📊 PnL TODAY", BOLD + NEON_YELLOW) if c else "PnL TODAY"
        net_val   = d.net
        net_c2    = cpnl(net_val, f"{net_val:+.4f}") if c else f"{net_val:+.4f}"
        wr        = d.win_rate
        wr_c      = color(f"{wr:.1f}%", NEON_GREEN if wr >= 60 else NEON_ORANGE if wr >= 40 else NEON_RED) if c else f"{wr:.1f}%"
        bar_vis   = _pnl_bar(net_val)
        trades_c  = color(str(d.trades), BOLD + WHITE) if c else str(d.trades)
        win_c     = color(str(d.wins),   NEON_GREEN)   if c else str(d.wins)
        loss_c    = color(str(d.losses), NEON_RED)     if c else str(d.losses)
        L.append(_row(f"  {pnl_label}   Net: {net_c2} USDT  {bar_vis}"))
        L.append(_row(f"  Trades: {trades_c}   Win: {win_c}  ✓   Loss: {loss_c}  ✗   WR: {wr_c}"))

    # ── Open positions ────────────────────────────────────────────────────────
    L.append(_mid())
    positions = view.get("positions") or []
    maxp      = view.get("max_positions", 1)
    pos_title = color(f"📈 OPEN POSITIONS  ({len(positions)}/{maxp})", BOLD + NEON_CYAN) if c else f"POSITIONS ({len(positions)}/{maxp})"
    L.append(_row(f"  {pos_title}"))
    L.append(_thin())

    if positions:
        for pos in positions:
            sym_c  = color(pos['symbol'], BOLD + NEON_YELLOW)     if c else pos['symbol']
            sd_c   = cside(pos['side'])                            if c else pos['side']
            up     = pos['upnl']
            up_c   = cpnl(up, f"{up:+.4f}")                       if c else f"{up:+.4f}"
            roi    = pos.get('roi', pos.get('profit_pct', 0.0)) * 100
            roi_c  = cpnl(roi, f"{roi:+.2f}%")                    if c else f"{roi:+.2f}%"
            be     = pos.get('breakeven_done', False)
            be_c   = color("✓ BE", BOLD + NEON_GREEN) if (c and be) else (color("✗ BE", GRAY) if c else "BE?")
            qty_c  = color(str(pos['qty']),   NEON_CYAN)  if c else str(pos['qty'])
            ent_c  = color(str(pos['entry']), WHITE)      if c else str(pos['entry'])
            mrk_c  = color(str(pos['mark']),  NEON_YELLOW) if c else str(pos['mark'])
            # ROI mini-bar
            rbar   = _bar(min(abs(roi), 10), 10, 10)
            rbar_c = color(rbar, NEON_GREEN if roi >= 0 else NEON_RED) if c else rbar
            L.append(_row(f"  {sym_c}  {sd_c}  qty={qty_c}  entry={ent_c}  mark={mrk_c}"))
            L.append(_row(f"  uPnL={up_c} USDT  ROI={roi_c} [{rbar_c}]  {be_c}"))
    else:
        idle = color("  ◌  No open positions — screening the market...", DIM + NEON_CYAN) if c else "No open positions."
        L.append(_row(idle))

    # ── Screening table ───────────────────────────────────────────────────────
    rows = view.get("screen") or []
    if rows:
        L.append(_mid())
        sc_title = color("🔍 SCREENING PAIRS", BOLD + NEON_PURPLE) if c else "SCREENING PAIRS"
        L.append(_row(f"  {sc_title}"))
        L.append(_thin())
        hdr   = f"  {'PAIR':<11}{'LONG':>7}{'SHORT':>8}   STATUS"
        hdr_c = color(hdr, DIM + WHITE) if c else hdr
        L.append(_row(hdr_c))
        for r in rows:
            sym    = r.get('symbol', '')
            status = r.get('status', '')
            sd     = r.get('side', 'NONE')
            if c:
                if sd == 'LONG':
                    sym_c    = color(f"  {sym:<11}", BOLD + NEON_GREEN)
                    stat_c   = color(f"▶ {status}", BOLD + NEON_GREEN)
                elif sd == 'SHORT':
                    sym_c    = color(f"  {sym:<11}", BOLD + NEON_RED)
                    stat_c   = color(f"▼ {status}", BOLD + NEON_RED)
                else:
                    sym_c    = color(f"  {sym:<11}", GRAY)
                    stat_c   = color(status, DIM + GRAY)
            else:
                sym_c = f"  {sym:<11}"; stat_c = status
            long_c  = color(f"{r.get('long','-'):>7}",  NEON_GREEN) if (c and r.get('long','-') not in ('-','0')) else f"{r.get('long','-'):>7}"
            short_c = color(f"{r.get('short','-'):>8}", NEON_RED)   if (c and r.get('short','-') not in ('-','0')) else f"{r.get('short','-'):>8}"
            L.append(_row(f"{sym_c}{long_c}{short_c}   {stat_c}"))

    # ── Event log ─────────────────────────────────────────────────────────────
    ev = view.get("events") or []
    if ev:
        L.append(_mid())
        ev_title = color("📋 LOG TERAKHIR", BOLD + NEON_ORANGE) if c else "LOG TERAKHIR"
        L.append(_row(f"  {ev_title}"))
        L.append(_thin())
        for e in ev[-6:]:
            bullet = color("  › ", NEON_PURPLE) if c else "  > "
            L.append(_row(bullet + e))

    # ── Footer ────────────────────────────────────────────────────────────────
    L.append(_mid())
    footer = "github.com/wawiraje  |  Auto-Retrain: ✓  |  Press Ctrl+C to stop"
    footer_c = color(footer, DIM + GRAY) if c else footer
    L.append(_center(footer_c))
    L.append(_bot())
    return "\n".join(L)


def show(view: dict) -> None:
    clear_screen()
    print(render(view), flush=True)
