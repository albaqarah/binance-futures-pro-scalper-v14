#!/bin/bash
# run_agent.sh — Jalankan AI Agent di background
cd "$(dirname "$0")"
PYTHON=".venv/bin/python3"
[ -f "$PYTHON" ] || PYTHON="python3"
mkdir -p logs   # v12 FIX: folder logs wajib ada sebelum nohup nulis pid/log

case "$1" in
  start)
    echo "Starting AI Agent..."
    nohup $PYTHON ai_agent.py >> logs/agent.log 2>&1 &
    echo $! > logs/agent.pid
    echo "AI Agent berjalan! PID: $(cat logs/agent.pid)"
    echo "Log: tail -f logs/agent.log"
    ;;
  stop)
    if [ -f logs/agent.pid ]; then
      kill $(cat logs/agent.pid) 2>/dev/null
      rm logs/agent.pid
      echo "AI Agent dihentikan."
    else
      echo "Agent tidak sedang berjalan."
    fi
    ;;
  report)
    echo "Meminta laporan sekarang..."
    $PYTHON ai_agent.py --report
    ;;
  status)
    if [ -f logs/agent.pid ] && kill -0 $(cat logs/agent.pid) 2>/dev/null; then
      echo "AI Agent: RUNNING (PID $(cat logs/agent.pid))"
    else
      echo "AI Agent: STOPPED"
    fi
    ;;
  *)
    echo "Usage: bash run_agent.sh [start|stop|report|status]"
    echo ""
    echo "  start   — Jalankan AI Agent di background"
    echo "  stop    — Hentikan AI Agent"
    echo "  report  — Kirim laporan sekarang ke Telegram"
    echo "  status  — Cek apakah AI Agent sedang jalan"
    ;;
esac
