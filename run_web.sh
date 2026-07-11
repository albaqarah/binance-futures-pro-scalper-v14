#!/bin/bash
# run_web.sh — 🔥 GANAS Web Dashboard control
# Usage: bash run_web.sh [start|stop|status|logs]
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
[ ! -f "$PYTHON" ] && PYTHON=$(which python3)
PIDFILE="$SCRIPT_DIR/logs/web.pid"
LOGFILE="$SCRIPT_DIR/logs/web_dashboard.log"
mkdir -p "$SCRIPT_DIR/logs"
PORT="${WEB_PORT:-8080}"

case "${1:-start}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
      echo "[WEB] Sudah jalan (PID=$(cat $PIDFILE))"; exit 0; fi
    cd "$SCRIPT_DIR"
    nohup $PYTHON web_dashboard.py >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "[WEB] ✅ Dashboard start! PID=$!"
    echo "[WEB] 🌐 Buka: http://${IP:-<IP-VPS>}:${PORT}"
    ;;
  stop)
    [ -f "$PIDFILE" ] && kill $(cat "$PIDFILE") 2>/dev/null && echo "[WEB] ✅ Stopped" || echo "[WEB] Tidak jalan"
    rm -f "$PIDFILE" ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
      echo "[WEB] ✅ RUNNING (PID=$(cat $PIDFILE)) port ${PORT}"
    else echo "[WEB] ❌ TIDAK JALAN"; fi ;;
  logs) tail -40 "$LOGFILE" ;;
  *) echo "Usage: bash run_web.sh [start|stop|status|logs]" ;;
esac
