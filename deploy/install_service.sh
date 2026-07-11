#!/usr/bin/env bash
# ============================================================
# Pro Scalper v14 - One-shot installer (systemd, anti-ribet)
# Sekali jalanin, semua beres:
#   1. Matiin proses nohup lama (biar gak dobel entry)
#   2. Setup venv + install dependencies (kalau belum ada)
#   3. Pasang systemd service (bot + agent)
#   4. Enable auto-start pas reboot + auto-restart kalau crash
#
# Pakai:  bash deploy/install_service.sh
# ============================================================
set -e

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"
PY="$APP_DIR/.venv/bin/python"

echo "============================================"
echo " Pro Scalper v14 - Installer systemd"
echo " App dir : $APP_DIR"
echo " User    : $RUN_USER"
echo "============================================"

# --- 1) Matiin proses nohup/manual lama biar gak dobel jalan ---
echo "==> [1/4] Matiin proses nohup/manual lama..."
pkill -f "python.*-m bot" 2>/dev/null && echo "    - bot lama dimatiin" || echo "    - tidak ada bot nohup jalan"
pkill -f "ai_agent.py" 2>/dev/null && echo "    - agent lama dimatiin" || echo "    - tidak ada agent nohup jalan"
sleep 2

# --- 2) Setup venv + dependencies kalau belum ada ---
echo "==> [2/4] Cek virtualenv & dependencies..."
if [ ! -x "$PY" ]; then
  echo "    - venv belum ada, bikin baru..."
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
if [ -f "$APP_DIR/requirements.txt" ]; then
  echo "    - install requirements.txt..."
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

# --- cek .env ---
if [ ! -f "$APP_DIR/.env" ]; then
  if [ -f "$APP_DIR/.env.example" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "!! PERHATIAN: .env baru dibuat dari template."
    echo "!! ISI dulu API key (Binance/Telegram/OpenAI) di: $APP_DIR/.env"
    echo "!! Lalu jalanin ulang: bash deploy/install_service.sh"
    exit 1
  else
    echo "!! ERROR: .env & .env.example tidak ada. Bikin .env dulu."
    exit 1
  fi
fi
mkdir -p "$APP_DIR/logs"

# --- 3) Generate systemd unit files ---
echo "==> [3/4] Pasang systemd service..."
sudo tee /etc/systemd/system/scalper-bot.service >/dev/null <<EOF
[Unit]
Description=Binance Futures Pro Scalper v14 - Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$PY -m bot
Restart=always
RestartSec=10
StandardOutput=append:$APP_DIR/logs/bot.out
StandardError=append:$APP_DIR/logs/bot.out

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/scalper-agent.service >/dev/null <<EOF
[Unit]
Description=Binance Futures Pro Scalper v14 - AI Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$PY ai_agent.py
Restart=always
RestartSec=15
StandardOutput=append:$APP_DIR/logs/agent.out
StandardError=append:$APP_DIR/logs/agent.out

[Install]
WantedBy=multi-user.target
EOF

# --- 4) Enable + start ---
echo "==> [4/4] Enable auto-start + jalanin..."
sudo systemctl daemon-reload
sudo systemctl enable scalper-bot.service scalper-agent.service
sudo systemctl restart scalper-bot.service scalper-agent.service
sleep 2

echo ""
echo "============================================"
echo " SELESAI! Bot + Agent jalan & auto-start reboot."
echo "============================================"
sudo systemctl status scalper-bot --no-pager -l | head -6 || true
echo ""
echo " Perintah berguna:"
echo "   Status : sudo systemctl status scalper-bot scalper-agent"
echo "   Log    : journalctl -u scalper-bot -f"
echo "   Restart: sudo systemctl restart scalper-bot scalper-agent"
