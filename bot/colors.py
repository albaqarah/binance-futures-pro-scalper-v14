from __future__ import annotations
import os

# Standard
GREEN    = "\033[92m"
RED      = "\033[91m"
YELLOW   = "\033[93m"
BLUE     = "\033[94m"
CYAN     = "\033[96m"
MAGENTA  = "\033[95m"
GRAY     = "\033[90m"
WHITE    = "\033[97m"
BOLD     = "\033[1m"
DIM      = "\033[2m"
BLINK    = "\033[5m"
RESET    = "\033[0m"

# Neon / bright extras (256-color)
NEON_GREEN  = "\033[38;5;118m"
NEON_CYAN   = "\033[38;5;51m"
NEON_PINK   = "\033[38;5;213m"
NEON_ORANGE = "\033[38;5;214m"
NEON_PURPLE = "\033[38;5;141m"
NEON_YELLOW = "\033[38;5;226m"
NEON_RED    = "\033[38;5;196m"
NEON_BLUE   = "\033[38;5;33m"

# Backgrounds
BG_BLACK    = "\033[40m"
BG_DARKBLUE = "\033[48;5;17m"
BG_GREEN    = "\033[48;5;22m"
BG_RED      = "\033[48;5;52m"


def use_color() -> bool:
    return os.getenv("NO_COLOR", "false").strip().lower() not in {"1", "true", "yes", "y"}


def color(text: str, code: str) -> str:
    if not use_color():
        return text
    return f"{code}{text}{RESET}"


def pnl(value: float, text: str | None = None) -> str:
    text = text if text is not None else f"{value:+.4f}"
    if value > 0:
        return color(text, BOLD + NEON_GREEN)
    if value < 0:
        return color(text, BOLD + NEON_RED)
    return color(text, GRAY)


def side(side_text: str) -> str:
    s = side_text.upper()
    if s == "LONG":
        return color(f"▲ {s}", BOLD + NEON_GREEN)
    if s == "SHORT":
        return color(f"▼ {s}", BOLD + NEON_RED)
    return color(s, GRAY)
