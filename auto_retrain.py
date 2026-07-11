"""
auto_retrain.py — Auto retrain model ML secara otomatis

Jalankan sekali sebagai background scheduler:
  python3 auto_retrain.py &

Atau via cron (diatur otomatis oleh setup_cron.sh):
  0 2 * * 0  (setiap Minggu jam 02:00 WIB)

Yang dikerjakan:
  1. Download data historis terbaru dari Binance
  2. Retrain model LightGBM + RF
  3. Simpan model baru ke models/
  4. Bot otomatis pakai model baru di loop berikutnya
"""
import subprocess, sys, time, logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUTO-RETRAIN] %(message)s",
    handlers=[
        logging.FileHandler("logs/auto_retrain.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger()

RETRAIN_INTERVAL_DAYS = 7   # retrain setiap 7 hari
STATE_FILE = Path("logs/last_retrain.txt")


def last_retrain_days() -> float:
    """Berapa hari sejak retrain terakhir."""
    if not STATE_FILE.exists():
        return 999.0
    try:
        ts = float(STATE_FILE.read_text().strip())
        return (time.time() - ts) / 86400
    except Exception:
        return 999.0


def run_retrain():
    log.info("Mulai retrain otomatis...")
    try:
        result = subprocess.run(
            [sys.executable, "setup_and_train.py"],
            capture_output=True, text=True, timeout=1800  # max 30 menit
        )
        if result.returncode == 0:
            STATE_FILE.write_text(str(time.time()))
            log.info("Retrain DONE! New model saved.")
            log.info(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        else:
            log.error(f"Retrain FAILED!\n{result.stderr[-1000:]}")
    except subprocess.TimeoutExpired:
        log.error("Retrain timeout (>30 minutes)")
    except Exception as e:
        log.error(f"Retrain error: {e}")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    log.info(f"Auto-retrain scheduler active. Interval: {RETRAIN_INTERVAL_DAYS} days")
    days = last_retrain_days()
    log.info(f"Last retrain: {days:.1f} days ago")

    # Langsung retrain kalau belum pernah atau sudah waktunya
    if days >= RETRAIN_INTERVAL_DAYS:
        run_retrain()
    else:
        next_days = RETRAIN_INTERVAL_DAYS - days
        log.info(f"Next retrain in {next_days:.1f} days")

    # Loop scheduler
    while True:
        time.sleep(3600)  # cek setiap 1 jam
        if last_retrain_days() >= RETRAIN_INTERVAL_DAYS:
            run_retrain()
