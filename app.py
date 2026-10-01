# app.py — SIMPLE CHECKSUM LIST VERSION
import os, json, time, threading
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ============================================================
# CONFIG — Sirf auth_token chahiye (browser se copy)
# ============================================================
BASE_UA  = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
BASE_URL = "https://www.nxcar.in"
CFG_FILE = "/tmp/nxcar_config.json"


# ============================================================
# STATE (memory + file)
# ============================================================
class State:
    def __init__(self):
        self.auth_token = None
        self.checksums = []          # list of checksums to try
        self.lock = threading.Lock()
        self.load()

    def save(self):
        try:
            with open(CFG_FILE, "w") as f:
                json.dump({
                    "auth_token": self.auth_token,
                    "checksums": self.checksums,
                }, f)
        except: pass

    def load(self):
        try:
            if os.path.exists(CFG_FILE):
                with open(CFG_FILE) as f:
                    d = json.load(f)
                self.auth_token = d.get("auth_token")
                self.checksums = d.get("checksums", [])
        except: pass

    def set_auth(self, token):
        with self.lock:
            self.auth_token = token
            self.save()

    def set_checksums(self, lst):
        with self.lock:
            # clean + dedupe
            seen, clean = set(), []
            for c in lst:
                c = c.strip().lower()
                if c and len(c) == 32 and c not in seen:
                    seen.add(c)
                    clean.append(c)
            self.checksums = clean
            self.save()
            return self.checksums

    def snapshot(self):
        return {
            "auth_token": (self.auth_token[:40] + "...") if self.auth_token else None,
            "has_token": bool(self.auth_token),
            "checksums_count": len(self.checksums),
            "checksums_preview": [c[:10] + "..." for c in self.checksums[:5]],
        }


STATE = State()


# ============================================================
# CORE CALL
# ============================================================
def call_vehicle_details(vn, checksum):
    url = "https://api.nxcar.in/vehicle_details"
    params = {
        "vehicle_number": vn.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    headers = {
        "User-Agent": BASE_UA,
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-ua-platform": '"Android"',
        "authorization": STATE.auth_token or "",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Brave";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?1",
        "sec-gpc": "1",
        "origin": BASE_URL,
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": f"{BASE_URL}/",
        "accept-language": "en-US,en;q=0.6",
        "priority": "u=1, i",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        try: data = r.json()
        except: data = r.text
        return {"status": r.status_code, "data": data}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def is_success(vd_data):
    """Return True if response looks like real vehicle data"""
    if isinstance(vd_data, dict):
        if not vd_data: return False
        if len(vd_data) == 1 and ("message" in vd_data or "error" in vd_data):
            return False
        return True
    if isinstance(vd_data, list):
        if len(vd_data) == 1 and isinstance(vd_data[0], str):
            low = vd_data[0].lower()
            if "try again" in low or "invalid" in low or "error" in low:
                return False
        return len(vd_data) > 0
    return False


# ============================================================
# MAIN — Try all checksums until success
# ============================================================
def try_all_checksums(vn):
    vn = vn.upper().strip()

    if not STATE.auth_token:
        return {
            "success": False,
            "error": "auth_token missing. Paste token first.",
            "vehicle_number": vn,
        }
    if not STATE.checksums:
        return {
            "success": False,
            "error": "No checksums. Paste list first.",
            "vehicle_number": vn,
        }

    attempts = []
    for idx, cs in enumerate(STATE.checksums, 1):
        result = call_vehicle_details(vn, cs)
        ok = is_success(result.get("data"))
        attempts.append({
            "try": idx,
            "checksum": cs,
            "status": result.get("status"),
            "success": ok,
            "response_preview": str(result.get("data"))[:200],
        })
        print(f"[TRY {idx}/{len(STATE.checksums)}] {cs[:12]}... → {result.get('status')} ok={ok}", flush=True)
        if ok:
            return {
                "success": True,
                "vehicle_number": vn,
                "winning_checksum": cs,
                "winning_try": idx,
                "total_tries": len(STATE.checksums),
                "http_status": result.get("status"),
                "vehicle_details_response": result.get("data"),
                "attempts": attempts,
            }

    return {
        "success": False,
        "vehicle_number": vn,
        "error": f"None of {len(STATE.checksums)} checksums worked.",
        "attempts": attempts,
    }


# ============================================================
# ROUTES
# ============================================================
@app.route("/rc=<vehicle_number>")
def rc_api(vehicle_number):
    try:
        return jsonify(try_all_checksums(vehicle_number))
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/rc/<vehicle_number>")
def rc_api2(vehicle_number):
    return rc_api(vehicle_number)


@app.route("/state")
def get_state():
    return jsonify(STATE.snapshot())


@app.route("/set-token")
def set_token():
    t = request.args.get("token", "").strip()
    if not t:
        return jsonify({"error": "token required"}), 400
    STATE.set_auth(t)
    return jsonify({"success": True, "message": "Token saved", **STATE.snapshot()})


@app.route("/add-checksums")
def add_checksums():
    """Add checksums from query params or POST body"""
    # from query: ?c=abc&c=def
    cs_list = request.args.getlist("c")
    # from POST body: {"checksums": [...]}
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        cs_list += body.get("checksums", [])
    # from comma-separated: ?list=abc,def,ghi
    raw = request.args.get("list", "")
    if raw:
        cs_list += [x.strip() for x in raw.split(",") if x.strip()]

    if not cs_list:
        return jsonify({"error": "No checksums provided. Use ?c=... or ?list=...,..."}), 400

    saved = STATE.set_checksums(cs_list)
    return jsonify({
        "success": True,
        "saved_count": len(saved),
        "checksums": saved,
        **STATE.snapshot(),
    })
@app.route("/add-checksums", methods=["POST"])
def add_checksums_post():
    return add_checksums()


@app.route("/clear-checksums")
def clear_checksums():
    STATE.set_checksums([])
    return jsonify({"success": True, "message": "Cleared", **STATE.snapshot()})


@app.route("/clear-all")
def clear_all():
    STATE.auth_token = None
    STATE.checksums = []
    STATE.save()
    return jsonify({"success": True})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


# ============================================================
# HTML UI
# ============================================================
HTML = r"""
<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🚗 nxcar Simple RC</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
min-height:100vh;color:#fff;padding:20px}
.c{max-width:960px;margin:0 auto}
h1{text-align:center;font-size:2rem;margin-bottom:8px;
background:linear-gradient(90deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;
-webkit-text-fill-color:transparent}
.sub{text-align:center;color:#aaa;margin-bottom:15px;font-size:.85rem}
.status{text-align:center;font-size:.85rem;padding:12px;border-radius:12px;
background:rgba(255,255,255,.05);margin-bottom:15px;border:1px solid rgba(255,255,255,.1)}
.card{background:rgba(255,255,255,.05);border-radius:16px;padding:20px;margin-bottom:15px;
border:1px solid rgba(255,255,255,.1)}
.card h3{color:#00d4ff;margin-bottom:12px;font-size:1.05rem}
textarea,input{width:100%;padding:12px;border-radius:10px;border:2px solid #444;
background:rgba(255,255,255,.05);color:#fff;font-size:.9rem;outline:none;
font-family:monospace;resize:vertical;margin-bottom:8px}
input:focus,textarea:focus{border-color:#00d4ff}
button{padding:12px 22px;border-radius:10px;border:none;cursor:pointer;
background:linear-gradient(135deg,#00d4ff,#7b2ff7);color:#fff;font-weight:600;
margin-right:6px;margin-top:6px}
button:hover{transform:translateY(-2px)}
button:disabled{opacity:.6}
.search{display:flex;gap:10px;margin-bottom:15px}
pre{background:#0a0a1a;padding:16px;border-radius:10px;overflow:auto;
font-size:.78rem;color:#b8ffb8;border:1px solid #1a1a3a;max-height:500px}
.badge{padding:4px 10px;border-radius:20px;font-size:.72rem;font-weight:600;margin-left:6px}
.ok{background:#00c853;color:#000}
.err{background:#ff1744;color:#fff}
.loader{display:none;text-align:center;padding:30px}
.loader.active{display:block}
.spin{width:50px;height:50px;border:4px solid rgba(255,255,255,.1);
border-top-color:#00d4ff;border-radius:50%;animation:s 1s linear infinite;margin:0 auto 15px}
@keyframes s{to{transform:rotate(360deg)}}
.msg{font-size:.82rem;color:#aaa;margin-top:8px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
.kv{background:rgba(0,0,0,.3);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.08)}
.kv .k{font-size:.7rem;color:#888;text-transform:uppercase}
.kv .v{font-size:.9rem;color:#fff;font-weight:600;margin-top:4px;word-break:break-all}
.try-row{display:grid;grid-template-columns:40px 1fr 60px 60px;gap:8px;
padding:8px;border-radius:8px;margin-bottom:6px;font-size:.8rem;font-family:monospace}
.try-ok{background:rgba(0,200,83,.15);border:1px solid rgba(0,200,83,.3)}
.try-fail{background:rgba(255,23,68,.08);border:1px solid rgba(255,23,68,.2)}
code{background:rgba(0,212,255,.12);padding:2px 6px;border-radius:4px;color:#7fff7f;font-size:.85rem}
.warn{background:rgba(255,171,0,.1);border:1px solid rgba(255,171,0,.4);
padding:12px;border-radius:10px;font-size:.82rem;color:#ffd54f;margin-bottom:12px}
</style></head><body>
<div class="c">
<h1>🚗 nxcar Simple RC</h1>
<p class="sub">Token + Checksums List → Auto Try → Success ✅</p>
<div class="status" id="status">Loading...</div>

<div class="warn">
<b>Kaise use karo:</b><br>
1️⃣ Browser me nxcar.in login karo → F12 → Network → koi bhi request → <code>authorization</code> header copy karo<br>
2️⃣ Multiple checksums paste karo (comma ya newline separated)<br>
3️⃣ Vehicle number daalo → Search → Auto try karega jab tak success na mile
</div>

<div class="card">
<h3>1️⃣ Auth Token (browser se copy)</h3>
<textarea id="token" rows="3" placeholder="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."></textarea>
<button onclick="saveToken()">💾 Save Token</button>
<div class="msg" id="tokenMsg"></div>
</div>

<div class="card">
<h3>2️⃣ Checksums List (ek per line, ya comma separated)</h3>
<textarea id="checksums" rows="8" placeholder="27ca4c231bb8b41514fb08d5a413862b
abc123def456...
..."></textarea>
<button onclick="saveChecksums()">💾 Save Checksums</button>
<button style="background:linear-gradient(135deg,#ff5252,#b71c1c)" onclick="clearAll()">🗑️ Clear All</button>
<div class="msg" id="csMsg"></div>
</div>

<div class="card">
<h3>3️⃣ Vehicle Search</h3>
<div class="search">
<input id="vnum" value="MH02FZ0555" placeholder="Vehicle Number"
       onkeypress="if(event.key==='Enter')go()">
<button id="btn" onclick="go()">🔍 Search (Try All)</button>
</div>
</div>

<div class="loader" id="loader"><div class="spin"></div>Testing checksums...</div>
<div id="result"></div>
</div>

<script>
async function loadState(){
  try{
    const r = await fetch('/state');const d = await r.json();
    const el = document.getElementById('status');
    if(d.has_token && d.checksums_count > 0){
      el.innerHTML = `🟢 Token OK • ${d.checksums_count} checksums saved`;
      el.style.background = 'rgba(0,200,83,.15)';
    } else {
      el.innerHTML = `🔴 Token: ${d.has_token?'✅':'❌'} • Checksums: ${d.checksums_count}`;
      el.style.background = 'rgba(255,171,0,.15)';
    }
  }catch(e){}
}

async function saveToken(){
  const t = document.getElementById('token').value.trim();
  if(!t) return alert('Token paste karo');
  const r = await fetch('/set-token?token=' + encodeURIComponent(t));
  const d = await r.json();
  document.getElementById('tokenMsg').innerText = JSON.stringify(d);
  loadState();
}

async function saveChecksums(){
  const raw = document.getElementById('checksums').value;
  // split by newline, comma, space
  const list = raw.split(/[\n,\s]+/).map(x=>x.trim()).filter(x=>x.length===32);
  if(list.length === 0){
    return alert('Kam se kam ek 32-char checksum daalo');
  }
  const r = await fetch('/add-checksums?list=' + encodeURIComponent(list.join(',')));
  const d = await r.json();
  document.getElementById('csMsg').innerText = `✅ Saved ${d.saved_count} checksums`;
  loadState();
}

async function clearAll(){
  if(!confirm('Sab clear karein?')) return;
  await fetch('/clear-all');
  document.getElementById('token').value = '';
  document.getElementById('checksums').value = '';
  document.getElementById('tokenMsg').innerText = 'Cleared';
  document.getElementById('csMsg').innerText = '';
  loadState();
}

async function go(){
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  if(!v) return;
  document.getElementById('btn').disabled = true;
  document.getElementById('loader').classList.add('active');
  document.getElementById('result').innerHTML = '';
  try{
    const r = await fetch('/rc=' + encodeURIComponent(v));
    const d = await r.json();
    render(d);
  }catch(e){
    document.getElementById('result').innerHTML = `<div class="card"><pre>${e.message}</pre></div>`;
  }finally{
    document.getElementById('btn').disabled = false;
    document.getElementById('loader').classList.remove('active');
    loadState();
  }
}

function render(d){
  const r = document.getElementById('result');
  let h = '';
  const b = d.success ? '<span class="badge ok">✅ SUCCESS</span>' : '<span class="badge err">❌ FAILED</span>';

  h += `<div class="card"><h3>📋 Summary ${b}</h3>
    <div class="grid">
      <div class="kv"><div class="k">Vehicle</div><div class="v">${d.vehicle_number||'-'}</div></div>
      <div class="kv"><div class="k">Winning Checksum</div><div class="v"><code>${d.winning_checksum||'-'}</code></div></div>
      <div class="kv"><div class="k">Try #</div><div class="v">${d.winning_try||'-'} / ${d.total_tries||'-'}</div></div>
      <div class="kv"><div class="k">HTTP</div><div class="v">${d.http_status||'-'}</div></div>
    </div>
    ${d.error?`<div style="margin-top:12px;color:#ff6b6b">⚠️ ${d.error}</div>`:''}
  </div>`;

  // Attempts list
  if(d.attempts && d.attempts.length){
    h += `<div class="card"><h3>🔬 All Attempts</h3>`;
    d.attempts.forEach(a=>{
      h += `<div class="try-row ${a.success?'try-ok':'try-fail'}">
        <div>#${a.try}</div>
        <div>${a.checksum}</div>
        <div>${a.status}</div>
        <div>${a.success?'✅':'❌'}</div>
      </div>`;
    });
    h += `</div>`;
  }

  // Vehicle details
  if(d.vehicle_details_response){
    h += `<div class="card"><h3>🚙 Vehicle Details</h3>
      <pre>${JSON.stringify(d.vehicle_details_response, null, 2)}</pre></div>`;
  }

  r.innerHTML = h;
}

loadState();
</script></body></html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("="*60, flush=True)
    print("🚗 nxcar Simple RC", flush=True)
    print(f"🌐 Port {port}", flush=True)
    print("="*60, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
