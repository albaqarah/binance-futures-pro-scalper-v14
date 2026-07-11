# Binance Futures PRO Scalper v14

Bot scalping **Binance USD-M Futures** (one-way mode, LONG & SHORT) + **AI Agent** pendamping.
Versi **v14** fokus ke **fix profit kemakan fee**, pair baru, sinyal lebih cerdas, dan laporan harian.

> ⚠️ **LIVE TRADING + LEVERAGE = RISIKO BESAR.** Tidak ada winrate yang dijamin.
> Selalu tes `DRY_RUN=true` dulu sebelum live. Matikan izin **withdraw** di API key.

---

## 🆕 Apa yang baru di v14

| # | Fitur | Ringkasan |
|---|-------|-----------|
| 10 | **Fee-Aware System** | Solusi utama bug “Telegram profit tapi Binance loss”. TP minimal otomatis nutup fee pulang-pergi + profit bersih minimal **0.15%**. Telegram lapor **PnL NET** (sudah dipotong fee). |
| - | **Pair baru** | Universe jadi **8 pair tanpa BTC/ETH**: `BNB, SOL, XRP, LINK, SUI, AVAX, APT, TIA`. |
| 7 | **High-Conviction Mode** | Saat sinyal kuat (15m align / conf tinggi), TP **diperpanjang** (x3.5 / x2.8) + partial close balik nyala + trailing dilonggarin. |
| 5 | **Screening 15m** | Konfirmasi tren timeframe lebih tinggi sebelum entry, sekaligus dipakai High-Conviction. |
| 9 | **Morning Briefing** | Ringkasan 24 jam tiap **07:00 WIB** ke Telegram: Net PnL, winrate, jumlah entry, long/short, profit/loss, durasi rata², pair terbaik/terburuk, saldo. |
| - | **Tuning** | `ML_PROBA_THRESHOLD=0.62`, `CONFLUENCE_MIN_SCORE=1.2`, Session-filter & News-bias **OFF**, partial default **OFF** (cuma nyala di High-Conviction). |

### 🔍 Detail fix fee (penting!)
Sebelumnya jalur **TP Paksa** melaporkan profit **GROSS** (belum dipotong fee penutup), makanya Telegram bilang profit padahal di Binance minus karena kemakan fee taker + partial dobel.
Di v14:
- Gate TP Paksa sekarang **harus NET positif**: `profit > fee_pulang_pergi + min_net(0.15%)` baru ditutup.
- Notif Telegram pakai label **`PnL net:`** dan ROI dihitung dari nilai bersih.
- **TP fee-aware**: TP minimal = `taker×2 + 0.15%` (default jadi ≈ **0.23%**), jadi tidak pernah TP di level yang habis kemakan fee.
- **Partial close OFF** secara default (biang dobel fee di size kecil); cuma aktif otomatis saat High-Conviction.

> 💡 **Catatan nilai fee = FRAKSI harga**, bukan persen: `0.0004` = 0.04% per sisi, `0.0015` = **0.15%** profit bersih minimal. Jangan ditulis `0.15` (itu jadi 15%).

---

## 📁 Struktur singkat

```
binance-futures-pro-scalper-v14/
├─ bot/                 # Inti bot (main.py, strategy.py, config.py, ml_signal.py, dll)
├─ ai_agent.py          # AI Agent: laporan, news-bias, Morning Briefing
├─ web_dashboard.py     # Dashboard web (opsional)
├─ setup_and_train.py   # 1 perintah: install + download data + train model
├─ download_data.py      # Download data historis Binance (tanpa API key)
├─ auto_retrain.py       # Retrain otomatis (cron mingguan)
├─ run_agent.sh / run_web.sh   # Kontrol agent / dashboard (mode nohup)
├─ deploy/              # systemd installer (bot + agent) untuk VPS
├─ requirements.txt
├─ .env.example         # Template config — SALIN jadi .env lalu isi key
└─ README.md
```

---

## 🚀 Instalasi lengkap (dari unzip → train → jalan)

### 0️⃣ Unzip & masuk folder
```bash
unzip binance-futures-pro-scalper-v14.zip
cd binance-futures-pro-scalper-v14
```

### 1️⃣ Bikin virtualenv + install dependency
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2️⃣ Siapkan config (.env)
```bash
cp .env.example .env
nano .env       # isi key, lalu Ctrl+O, Enter, Ctrl+X
```
Yang WAJIB diisi:
```ini
BINANCE_API_KEY=...          # API key Binance (matikan izin withdraw!)
BINANCE_API_SECRET=...
TELEGRAM_TOKEN=...           # token bot Telegram (dari @BotFather)
TELEGRAM_CHAT_ID=...         # chat/grup id tujuan notif
# AI Agent (opsional, untuk laporan & news-bias):
OPENAI_API_KEY=...           # mis. key Bluesminds
OPENAI_BASE_URL=https://api.bluesminds.com/v1
OPENAI_MODEL=openai/zai-org/GLM-4.7
```
> 🔐 **Mulai aman dulu:** set `DRY_RUN=true` (atau `USE_TESTNET=true`) untuk uji tanpa uang asli. Kalau yakin, ubah `DRY_RUN=false`.

Setting v12 sudah preset di `.env.example` (8 pair, fee-aware, High-Conviction, Morning Briefing) — tinggal pakai.

### 3️⃣ Train model ML (LightGBM)
Satu perintah otomatis (install lib yang kurang → download data → train → simpan ke `models/`):
```bash
python3 setup_and_train.py
```
Atau manual (2 langkah):
```bash
python3 download_data.py          # unduh data historis ke data_historis/
python3 -m bot.train              # latih model -> models/
```

> ℹ️ Model dilatih sebagai **combo** dari pair inti. Pair baru (**SUI/AVAX/APT/TIA**) otomatis pakai **model combo** sebagai fallback — tetap jalan. Untuk akurasi maksimal, retrain per-pair belakangan.

> ⚠️ **VPS RAM kecil (OOM / `Killed` saat train)?** Tambah swap 2GB dulu:
> ```bash
> sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
> sudo mkswap /swapfile && sudo swapon /swapfile
> echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
> free -h
> ```

### 4️⃣ Jalankan bot
```bash
source .venv/bin/activate
python3 -m bot.main
```
Background pakai screen:
```bash
screen -S scalper
python3 -m bot.main
# detach: CTRL+A lalu D   |   balik: screen -r scalper
```

### 5️⃣ Jalankan AI Agent (laporan + Morning Briefing)
```bash
bash run_agent.sh start      # jalan di background
bash run_agent.sh status     # cek status
bash run_agent.sh report     # paksa kirim laporan sekarang
bash run_agent.sh stop       # hentikan
```
Agent otomatis kirim **Morning Briefing 07:00 WIB** (atur via `MORNING_BRIEFING_HOUR`).

### 6️⃣ (Opsional) Dashboard web
```bash
bash run_web.sh start        # default port 8080 -> http://<IP-VPS>:8080
bash run_web.sh logs
bash run_web.sh stop
```

---

## 🖥️ Deploy permanen di VPS (systemd — auto-restart + auto-start reboot)

Cara paling anti-ribet, sekali jalan langsung pasang service **bot + agent**:
```bash
cd binance-futures-pro-scalper-v14
bash deploy/install_service.sh
```
Script ini otomatis: matiin proses lama → bikin venv + install deps → pasang `scalper-bot` & `scalper-agent` → enable auto-start.

> Kalau `.env` belum ada, script bikin dari template lalu berhenti — isi key dulu, baru jalankan ulang.

Perintah berguna:
```bash
sudo systemctl status scalper-bot scalper-agent
sudo systemctl restart scalper-bot scalper-agent
journalctl -u scalper-bot -f       # log live bot
journalctl -u scalper-agent -f     # log live agent
```

### Update dari versi lama ke v14 di VPS
```bash
sudo systemctl stop scalper-bot scalper-agent     # stop dulu
# upload & unzip v12, salin .env lama ke folder v12 (JANGAN pakai .env contoh):
cp /path/lama/.env binance-futures-pro-scalper-v14/.env
# tambahkan baris v12 yang baru (lihat blok v12 di .env.example) ke .env kamu
cd binance-futures-pro-scalper-v14
bash deploy/install_service.sh
```
> Pastikan `WorkingDirectory` di service nunjuk ke folder v14. Installer regenerate unit otomatis sesuai folder tempat dijalankan.

---

## 🔁 Retrain otomatis (opsional)
```bash
bash setup_cron.sh        # pasang cron retrain mingguan (Minggu 02:00)
# atau scheduler manual:
python3 auto_retrain.py &
```

---

## ⚙️ Referensi setting v12 (di .env)

```ini
# Pair (8, tanpa BTC/ETH)
SYMBOLS=BNBUSDT,SOLUSDT,XRPUSDT,LINKUSDT,SUIUSDT,AVAXUSDT,APTUSDT,TIAUSDT
TIMEFRAMES=5m

# Sinyal
ML_PROBA_THRESHOLD=0.62
CONFLUENCE_MIN_SCORE=1.2
SESSION_FILTER_ENABLE=false
NEWS_BIAS_ENABLE=false

# Fee-Aware (fix profit kemakan fee) — nilai = FRAKSI harga
TAKER_FEE_PCT=0.0004
MAKER_FEE_PCT=0.0002
REPORT_NET_PNL=true
FEE_AWARE_TP=true
MIN_NET_PROFIT_PCT=0.0015      # = 0.15% profit bersih minimal
PREFER_MAKER_EXIT=false        # exit tetap market demi keamanan eksekusi

# Screening 15m
SCREEN_15M_ENABLE=true
SCREEN_15M_TF=15m

# High-Conviction Mode
HIGH_CONVICTION_ENABLE=true
HIGH_CONVICTION_CONF1=0.80     # tier-1 (15m align) -> TP x3.5, partial 30%
HIGH_CONVICTION_CONF2=0.80     # tier-2 (conf tinggi) -> TP x2.8, partial 40%

# Partial (default OFF; auto-ON saat High-Conviction)
PARTIAL_CLOSE_ENABLE=false

# Morning Briefing
MORNING_BRIEFING_ENABLE=true
MORNING_BRIEFING_HOUR=7
```

---

## 🔒 Keamanan & catatan
- **Regenerate API key** apa pun yang pernah ke-share/paste publik (Binance, Telegram, OpenAI/Bluesminds).
- API key Binance: aktifkan **Futures**, **matikan Withdraw**, batasi IP kalau bisa.
- `.env` **tidak** ikut di-zip (sengaja, biar key nggak bocor). Selalu bikin/sertakan `.env` sendiri di server.
- `PREFER_MAKER_EXIT` ada sebagai flag, tapi default `false`: exit SL/TP tetap **market** supaya pasti ke-fill saat market gerak cepat (limit exit berisiko nggak ke-eksekusi).
- SL/TP dipasang via **Binance Algo Order** (`STOP_MARKET` / `TAKE_PROFIT_MARKET`), trigger dibulatkan ke `tickSize`. Verifikasi di tab **TP/SL / Conditional** app Binance setelah entry live.

---

## ✅ Quick start (ringkas)
```bash
unzip binance-futures-pro-scalper-v14.zip && cd binance-futures-pro-scalper-v14
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # isi key (DRY_RUN=true dulu)
python3 setup_and_train.py             # download data + train model
python3 -m bot.main                    # jalankan bot
bash run_agent.sh start                # jalankan AI agent + Morning Briefing
```
