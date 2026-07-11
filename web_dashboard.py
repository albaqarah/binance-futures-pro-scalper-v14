#!/usr/bin/env python3
"""
web_dashboard.py — 🔥 GANAS Web Dashboard untuk Binance Futures PRO Scalper v14

Fitur:
  - Live equity / PnL chart (Chart.js)
  - Tabel posisi real-time
  - Tombol START / STOP bot dari browser
  - Mobile responsive (neon dark theme)
  - Pure Python stdlib — TIDAK perlu install apa-apa!

Jalankan:
  python3 web_dashboard.py            → http://0.0.0.0:8080
  WEB_PORT=9000 python3 web_dashboard.py

Keamanan:
  Set WEB_TOKEN di .env untuk proteksi tombol start/stop.
"""
import json
import os
import subprocess
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE      = Path(__file__).resolve().parent
LOG_FILE  = BASE / "logs" / "bot.log"
DASH_FILE = BASE / "logs" / "dashboard_state.json"
EQ_FILE   = BASE / "logs" / "equity_history.json"


def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val:
        return val
    envf = BASE / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return default


PORT      = int(_env("WEB_PORT", "8080"))
WEB_TOKEN = _env("WEB_TOKEN", "")


def read_dashboard_state() -> dict:
    if DASH_FILE.exists():
        try:
            return json.loads(DASH_FILE.read_text())
        except Exception:
            pass
    return {}


def read_equity() -> list:
    if EQ_FILE.exists():
        try:
            return json.loads(EQ_FILE.read_text())
        except Exception:
            pass
    return []


def read_logs(n: int = 40) -> list:
    if LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(errors="ignore").splitlines()
            return lines[-n:]
        except Exception:
            pass
    return []


def bot_is_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "bot.main"],
                           capture_output=True, text=True)
        return bool(r.stdout.strip())
    except Exception:
        return False


def start_bot() -> bool:
    if bot_is_running():
        return True
    try:
        py = str(BASE / ".venv" / "bin" / "python3")
        if not Path(py).exists():
            py = "python3"
        logf = open(BASE / "logs" / "bot.log", "a")
        subprocess.Popen([py, "-m", "bot.main"], cwd=str(BASE),
                         stdout=logf, stderr=subprocess.STDOUT,
                         start_new_session=True)
        time.sleep(2)
        return bot_is_running()
    except Exception:
        return False


def stop_bot() -> bool:
    try:
        subprocess.run(["pkill", "-f", "bot.main"], capture_output=True)
        time.sleep(1)
        return not bot_is_running()
    except Exception:
        return False


def build_state_payload() -> dict:
    st = read_dashboard_state()
    st["bot_running"] = bot_is_running()
    st["server_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st["logs"]        = read_logs(40)
    st["equity"]      = read_equity()
    return st


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # silent

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, HTML_PAGE, "text/html; charset=utf-8")
        elif u.path == "/api/state":
            self._send(200, json.dumps(build_state_payload()))
        elif u.path == "/api/control":
            q = parse_qs(u.query)
            action = (q.get("action") or [""])[0]
            token  = (q.get("token")  or [""])[0]
            if WEB_TOKEN and token != WEB_TOKEN:
                self._send(403, json.dumps({"ok": False, "error": "token salah"}))
                return
            if action == "start":
                ok = start_bot()
            elif action == "stop":
                ok = stop_bot()
            else:
                ok = False
            self._send(200, json.dumps({"ok": ok, "running": bot_is_running()}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    (BASE / "logs").mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🔥 GANAS Web Dashboard running at http://0.0.0.0:{PORT}")
    print(f"   Open from phone/laptop: http://<VPS-IP>:{PORT}")
    if WEB_TOKEN:
        print("   🔒 Token protection: ON")
    else:
        print("   ⚠️  Token protection: OFF (set WEB_TOKEN in .env to secure it)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stop.")
        srv.shutdown()


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ PRO Scalper v14 — GANAS Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{
    --neon-green:#39ff14; --neon-cyan:#00f0ff; --neon-pink:#ff2bd6;
    --neon-orange:#ff9e00; --neon-purple:#b14aed; --neon-red:#ff2b4e;
    --neon-yellow:#fff200; --bg:#05060a; --card:#0d1018; --card2:#11151f;
    --border:#1d2333; --txt:#e6edf3; --dim:#7d8aa0;
  }
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  body{background:var(--bg);color:var(--txt);font-family:'SF Mono',ui-monospace,Menlo,Consolas,monospace;
    background-image:radial-gradient(circle at 20% 10%,rgba(177,74,237,.08),transparent 40%),
      radial-gradient(circle at 80% 0%,rgba(0,240,255,.08),transparent 40%);
    min-height:100vh;padding:14px;max-width:1200px;margin:0 auto}
  .hdr{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;
    padding:16px 18px;border:1px solid var(--border);border-radius:16px;
    background:linear-gradient(135deg,rgba(0,240,255,.06),rgba(177,74,237,.06));
    box-shadow:0 0 24px rgba(0,240,255,.12),inset 0 0 24px rgba(177,74,237,.05);margin-bottom:14px}
  .logo{font-size:19px;font-weight:800;letter-spacing:.5px;
    background:linear-gradient(90deg,var(--neon-cyan),var(--neon-pink),var(--neon-purple));
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
    text-shadow:0 0 18px rgba(0,240,255,.4)}
  .logo small{display:block;font-size:10px;font-weight:500;color:var(--dim);-webkit-text-fill-color:var(--dim);letter-spacing:1px;margin-top:3px}
  .status-wrap{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .pill{font-size:11px;font-weight:700;padding:5px 11px;border-radius:20px;border:1px solid;white-space:nowrap}
  .pill.run{color:var(--neon-green);border-color:var(--neon-green);box-shadow:0 0 12px rgba(57,255,20,.4);animation:pulse 2s infinite}
  .pill.stop{color:var(--neon-red);border-color:var(--neon-red);box-shadow:0 0 12px rgba(255,43,78,.3)}
  .pill.mode{color:var(--neon-yellow);border-color:var(--neon-yellow)}
  .pill.clock{color:var(--neon-cyan);border-color:var(--border)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:11px;margin-bottom:14px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;
    position:relative;overflow:hidden}
  .card::before{content:'';position:absolute;top:0;left:0;width:100%;height:2px;
    background:linear-gradient(90deg,transparent,var(--accent,var(--neon-cyan)),transparent);opacity:.7}
  .card .lbl{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:7px}
  .card .val{font-size:22px;font-weight:800;color:var(--accent,var(--txt));text-shadow:0 0 14px var(--glow,transparent)}
  .card .sub{font-size:11px;color:var(--dim);margin-top:5px}
  .green{--accent:var(--neon-green);--glow:rgba(57,255,20,.35)}
  .red{--accent:var(--neon-red);--glow:rgba(255,43,78,.35)}
  .cyan{--accent:var(--neon-cyan);--glow:rgba(0,240,255,.35)}
  .orange{--accent:var(--neon-orange);--glow:rgba(255,158,0,.35)}
  .purple{--accent:var(--neon-purple);--glow:rgba(177,74,237,.35)}
  .yellow{--accent:var(--neon-yellow);--glow:rgba(255,242,0,.3)}
  .panel{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:14px}
  .panel h2{font-size:13px;letter-spacing:1px;text-transform:uppercase;margin-bottom:13px;color:var(--neon-cyan);
    display:flex;align-items:center;gap:7px}
  .ctrl{display:flex;gap:10px;flex-wrap:wrap}
  button{font-family:inherit;font-weight:800;font-size:13px;padding:12px 22px;border-radius:11px;border:1px solid;
    cursor:pointer;transition:.15s;flex:1;min-width:120px;background:transparent}
  .btn-start{color:var(--neon-green);border-color:var(--neon-green)}
  .btn-start:active{background:var(--neon-green);color:#000;box-shadow:0 0 22px rgba(57,255,20,.6)}
  .btn-stop{color:var(--neon-red);border-color:var(--neon-red)}
  .btn-stop:active{background:var(--neon-red);color:#000;box-shadow:0 0 22px rgba(255,43,78,.6)}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1px;
    padding:8px 9px;border-bottom:1px solid var(--border)}
  td{padding:10px 9px;border-bottom:1px solid rgba(29,35,51,.5)}
  tr:last-child td{border-bottom:none}
  .tag{font-size:10px;font-weight:800;padding:3px 9px;border-radius:6px}
  .tag.long{color:var(--neon-green);background:rgba(57,255,20,.12)}
  .tag.short{color:var(--neon-red);background:rgba(255,43,78,.12)}
  .pos{color:var(--neon-green);font-weight:700}
  .neg{color:var(--neon-red);font-weight:700}
  .empty{text-align:center;color:var(--dim);padding:26px;font-size:13px}
  .logbox{background:#04050a;border:1px solid var(--border);border-radius:10px;padding:12px;
    font-size:11px;line-height:1.65;max-height:220px;overflow-y:auto;color:#9fb0c8}
  .logbox div{white-space:pre-wrap;word-break:break-word}
  .chartwrap{position:relative;height:230px}
  .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--card2);
    border:1px solid var(--neon-cyan);color:var(--txt);padding:13px 22px;border-radius:11px;font-size:13px;
    box-shadow:0 0 24px rgba(0,240,255,.3);opacity:0;transition:.3s;pointer-events:none;z-index:99}
  .toast.show{opacity:1}
  .foot{text-align:center;color:var(--dim);font-size:11px;padding:14px 0 4px}
  @media(max-width:560px){.logo{font-size:16px}.card .val{font-size:19px}.hdr{padding:13px}}
</style>
</head>
<body>
  <div class="hdr">
    <div class="logo">⚡ BINANCE FUTURES PRO SCALPER v14
      <small>ML ENSEMBLE + AI AGENT + NEWS-BIAS + HYBRID FALLBACK</small></div>
    <div class="status-wrap" id="statusWrap">
      <span class="pill clock" id="clock">--:--:--</span>
      <span class="pill stop" id="botStatus">○ OFFLINE</span>
    </div>
  </div>

  <div class="grid" id="statGrid"></div>

  <div class="panel">
    <h2>📈 EQUITY / PnL CURVE</h2>
    <div class="chartwrap"><canvas id="eqChart"></canvas></div>
  </div>

  <div class="panel">
    <h2>🎮 KONTROL BOT</h2>
    <div class="ctrl">
      <button class="btn-start" onclick="ctrl('start')">▶ START BOT</button>
      <button class="btn-stop" onclick="ctrl('stop')">■ STOP BOT</button>
    </div>
    <div class="sub" style="font-size:11px;color:var(--dim);margin-top:10px">
      ⚡ Tombol mengontrol proses bot di VPS secara langsung</div>
  </div>

  <div class="panel">
    <h2>📊 POSISI TERBUKA <span id="posCount" style="color:var(--dim);font-size:11px"></span></h2>
    <div id="posTable"></div>
  </div>

  <div class="panel">
    <h2>🔍 SCREENING PAIRS</h2>
    <div id="screenTable"></div>
  </div>

  <div class="panel">
    <h2>📋 LOG TERAKHIR</h2>
    <div class="logbox" id="logBox"></div>
  </div>

  <div class="foot">🔥 GANAS Dashboard — auto-refresh 3s — github.com/wawiraje</div>
  <div class="toast" id="toast"></div>

<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
let chart;

function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2600);}

function fmt(n,d=2){return (n==null||isNaN(n))?'-':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
function cls(n){return n>0?'pos':(n<0?'neg':'');}
function sign(n,d=2){return (n>=0?'+':'')+fmt(n,d);}

async function ctrl(action){
  toast(action==='start'?'⚡ Menyalakan bot...':'🛑 Menghentikan bot...');
  try{const r=await fetch('/api/control?action='+action+'&token='+encodeURIComponent(TOKEN));
    const j=await r.json();
    if(j.error){toast('❌ '+j.error);return;}
    toast(j.running?'✅ Bot RUNNING':'✅ Bot STOPPED');
    setTimeout(refresh,800);
  }catch(e){toast('❌ Gagal konek server');}
}

function statCard(lbl,val,sub,cls){return `<div class="card ${cls}"><div class="lbl">${lbl}</div>`+
  `<div class="val">${val}</div><div class="sub">${sub||''}</div></div>`;}

function render(s){
  document.getElementById('clock').textContent = s.server_time ? s.server_time.split(' ')[1] : '--';
  const bs=document.getElementById('botStatus');
  if(s.bot_running){bs.className='pill run';bs.textContent='● LIVE RUNNING';}
  else{bs.className='pill stop';bs.textContent='○ OFFLINE';}

  const d=s.daily||{}, wr=d.win_rate||0;
  const net=d.net||0;
  const grid=document.getElementById('statGrid');
  grid.innerHTML =
    statCard('💰 Wallet', fmt(s.wallet)+'', 'USDT total','cyan')+
    statCard('💵 Available', fmt(s.available)+'', 'USDT bebas','green')+
    statCard('⚡ uPnL', sign(s.upnl_acct)+'', 'unrealized', s.upnl_acct>=0?'green':'red')+
    statCard('📊 PnL Hari Ini', sign(net)+'', d.trades+' trade', net>=0?'green':'red')+
    statCard('🎯 Winrate', fmt(wr,1)+'%', (d.wins||0)+'W / '+(d.losses||0)+'L', wr>=60?'green':(wr>=40?'orange':'red'))+
    statCard('🚀 Leverage', (s.leverage||'-')+'x', (s.dry_run?'DRY-RUN':'LIVE')+' · '+(s.testnet?'TESTNET':'REAL'),'purple');

  // positions
  const pos=s.positions||[];
  document.getElementById('posCount').textContent='('+pos.length+'/'+(s.max_positions||1)+')';
  if(pos.length){
    let h='<table><tr><th>PAIR</th><th>SIDE</th><th>QTY</th><th>ENTRY</th><th>MARK</th><th>uPnL</th><th>ROI</th></tr>';
    pos.forEach(p=>{const roi=(p.roi!=null?p.roi:(p.profit_pct||0))*100;
      h+=`<tr><td><b>${p.symbol}</b></td>`+
        `<td><span class="tag ${p.side=='LONG'?'long':'short'}">${p.side}</span></td>`+
        `<td>${fmt(p.qty,3)}</td><td>${fmt(p.entry,4)}</td><td>${fmt(p.mark,4)}</td>`+
        `<td class="${cls(p.upnl)}">${sign(p.upnl,4)}</td>`+
        `<td class="${cls(roi)}">${sign(roi)}%</td></tr>`;});
    document.getElementById('posTable').innerHTML=h+'</table>';
  }else document.getElementById('posTable').innerHTML='<div class="empty">◌ Tidak ada posisi — screening pasar...</div>';

  // screening
  const sc=s.screen||[];
  if(sc.length){
    let h='<table><tr><th>PAIR</th><th>LONG</th><th>SHORT</th><th>STATUS</th></tr>';
    sc.forEach(r=>{const sd=r.side||'NONE';const tag=sd=='LONG'?'long':(sd=='SHORT'?'short':'');
      h+=`<tr><td><b>${r.symbol||''}</b></td><td class="pos">${r.long||'-'}</td>`+
        `<td class="neg">${r.short||'-'}</td>`+
        `<td>${tag?'<span class="tag '+tag+'">'+sd+'</span> ':''}${r.status||''}</td></tr>`;});
    document.getElementById('screenTable').innerHTML=h+'</table>';
  }else document.getElementById('screenTable').innerHTML='<div class="empty">—</div>';

  // logs
  const lg=s.logs||[];
  document.getElementById('logBox').innerHTML = lg.length?
    lg.map(l=>{let c='#9fb0c8';if(/ERROR|GAGAL|❌/.test(l))c='#ff2b4e';
      else if(/WIN|✅|profit|TP/i.test(l))c='#39ff14';
      else if(/SHORT|SL|loss/i.test(l))c='#ff9e00';
      return `<div style="color:${c}">${l.replace(/</g,'&lt;')}</div>`;}).join(''):
    '<div class="empty">Belum ada log</div>';
  const lb=document.getElementById('logBox');lb.scrollTop=lb.scrollHeight;

  // chart
  const eq=s.equity||[];
  const labels=eq.map(e=>e.t||'');
  const data=eq.map(e=>e.equity!=null?e.equity:e.v);
  if(!chart){
    const ctx=document.getElementById('eqChart');
    const g=ctx.getContext('2d').createLinearGradient(0,0,0,230);
    g.addColorStop(0,'rgba(0,240,255,.35)');g.addColorStop(1,'rgba(0,240,255,0)');
    chart=new Chart(ctx,{type:'line',data:{labels,datasets:[{data,borderColor:'#00f0ff',
      backgroundColor:g,borderWidth:2,fill:true,tension:.35,pointRadius:0,pointHoverRadius:5,
      pointHoverBackgroundColor:'#ff2bd6'}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},
        tooltip:{backgroundColor:'#11151f',borderColor:'#1d2333',borderWidth:1,titleColor:'#00f0ff',
          bodyColor:'#e6edf3',callbacks:{label:c=>' '+fmt(c.parsed.y,4)+' USDT'}}},
        scales:{x:{ticks:{color:'#7d8aa0',maxTicksLimit:6,font:{size:9}},grid:{color:'rgba(29,35,51,.4)'}},
          y:{ticks:{color:'#7d8aa0',font:{size:9},callback:v=>fmt(v,2)},grid:{color:'rgba(29,35,51,.4)'}}}}});
  }else{chart.data.labels=labels;chart.data.datasets[0].data=data;chart.update('none');}
}

async function refresh(){
  try{const r=await fetch('/api/state');render(await r.json());}
  catch(e){document.getElementById('botStatus').textContent='⚠ NO CONNECTION';}
}
refresh();setInterval(refresh,3000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
