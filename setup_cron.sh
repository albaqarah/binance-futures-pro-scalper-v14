#!/bin/bash
# setup_cron.sh - Pasang cron job auto-retrain setiap Minggu jam 02:00
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
LOG="$SCRIPT_DIR/logs/auto_retrain.log"

# Pastikan folder logs ada
mkdir -p "$SCRIPT_DIR/logs"

# Tambah cron job (hapus duplikat dulu)
(crontab -l 2>/dev/null | grep -v "auto_retrain\|setup_and_train"; \
 echo "0 2 * * 0 cd $SCRIPT_DIR && $PYTHON setup_and_train.py >> $LOG 2>&1") | crontab -

echo "Cron job terpasang!"
echo "Jadwal: Setiap Minggu jam 02:00 WIB"
echo ""
crontab -l | grep auto_retrain || crontab -l | grep setup_and_train
