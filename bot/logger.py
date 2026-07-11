from __future__ import annotations
import logging
from pathlib import Path
from .config import Settings


def setup_logger(settings: Settings) -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)
    logger = logging.getLogger("pro-scalper")
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    # Selalu tulis ke file supaya histori tidak hilang.
    fh = logging.FileHandler("logs/bot.log")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Tampilkan di terminal hanya kalau dashboard mati (agar tidak bentrok).
    if not settings.dashboard:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    return logger
