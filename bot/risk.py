from __future__ import annotations
from dataclasses import dataclass
from .config import Settings


@dataclass
class PositionPlan:
    symbol: str
    side: str
    free_margin_usdt: float
    entry_margin: float
    notional: float
    leverage: int


def calc_entry_from_free_margin(symbol: str, side: str, free_margin_usdt: float, settings: Settings, size_mult: float = 1.0) -> PositionPlan:
    pct = settings.entry_margin_pct * max(0.1, float(size_mult))
    entry_margin = free_margin_usdt * pct
    return PositionPlan(symbol, side, free_margin_usdt, entry_margin, entry_margin * settings.leverage, settings.leverage)


def calc_sl_tp(side: str, entry: float, sl_pct: float, tp_pct: float) -> tuple[float, float]:
    if side.upper() == "LONG":
        return entry * (1 - sl_pct), entry * (1 + tp_pct)
    if side.upper() == "SHORT":
        return entry * (1 + sl_pct), entry * (1 - tp_pct)
    raise ValueError("side must be LONG or SHORT")


def profit_pct(side: str, entry: float, mark: float) -> float:
    """Gerakan harga searah posisi, dalam pecahan (0.01 = +1%)."""
    if entry <= 0:
        return 0.0
    if side.upper() == "LONG":
        return (mark - entry) / entry
    return (entry - mark) / entry


def calc_breakeven_sl(side: str, entry: float, offset_pct: float) -> float:
    """SL baru yang mengunci sedikit profit di sekitar harga entry."""
    if side.upper() == "LONG":
        return entry * (1 + offset_pct)
    if side.upper() == "SHORT":
        return entry * (1 - offset_pct)
    raise ValueError("side must be LONG or SHORT")
