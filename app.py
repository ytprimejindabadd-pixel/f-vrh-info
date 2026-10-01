# app.py — FINAL WORKING
import os, json, time, threading, re
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

CONFIG = {
    "phone":     os.environ.get("NX_PHONE", "9612057455"),
    "user_id":   "78786",
    "user_uuid": "7fbd669b-0d74-402a-937d-2bd4836bd613",
    "token_file":"/tmp/tokens.json",
}
BASE_UA  = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
BASE_URL = "https://www.nxcar.in"


# ============================================================
# SESSION
# ============================================================
class Session:
    def __init__(self):
        self.auth_token = None
        self.cf_token = None
        self.cf_token_at = 0
        self.expires_at = 0
        self.lock = threading.Lock()
        self.load()

    def is_valid(self):
        return bool(self.auth_token) and time.time() < self.expires_at - 120

    def cf_valid(self):
        # cf_token valid for 90 sec max
        return bool(self.cf_token) and (time.time() - self.cf_token_at) < 90

    def update(self, auth_token=None, cf_token=None, ttl=30*24*3600):
        with self.lock:
            if auth_token: self.auth_token = auth_token
            if cf_token:
                self.cf_token = cf_token
                self.cf_token_at = time.time()
            if auth_token:
                self.expires_at = time.time() + ttl
            self.save()

    def snapshot(self):
        with self.lock:
            return {
                "auth_token": self.auth_token[:40]+"..." if self.auth_token else None,
                "cf_token":   self.cf_token[:40]+"..." if self.cf_token else None,
                "cf_valid":   self.cf_valid(),
                "cf_age":     int(time.time() - self.cf_token_at) if self.cf_token else None,
                "expires_in": max(0, int(self.expires_at - time.time())),
                "valid":      self.is_valid(),
                "user_id":    CONFIG["user_id"],
            }

    def save(self):
        try:
            with open(CONFIG["token_file"], "w") as f:
                json.dump({"auth_token": self.auth_token,
                           "expires_at": self.expires_at}, f)
        except: pass

    def load(self):
        try:
            if os.path.exists(CONFIG["token_file"]):
                with open(CONFIG["token_file"]) as f:
                    d = json.load(f)
                self.auth_token = d.get("auth_token")
                self.expires_at = d.get("expires_at", 0)
        except: pass


SESSION = Session()


# ============================================================
# HEADERS — EXACT BROWSER REPLICA
# ============================================================
def h(auth_token=None, referer="/rc-check"):
    token = auth_token or SESSION.auth_token or ""
    return {
        "User-Agent": BASE_UA,
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Not=A?Brand";v="99", "Brave";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?1",
        "sec-gpc": "1",
        "origin": BASE_URL,
        "sec-fetch-site": "same-origin",   # ✅ same-origin (not same-site)
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": f"{BASE_URL}{referer}",
        "accept-language": "en-US,en;q=0.6",
        "priority": "u=1, i",
        "authorization": token,
        # ✅ user_id = 78786 (numeric, not UUID)
        "Cookie": f"user_id={CONFIG['user_id']}; auth_token={token}; nxcar_user_id={CONFIG['user_id']}; role_id=1",
    }


# ============================================================
# LOGIN
# ============================================================
def send_otp(phone):
    try:
        return requests.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone},
            headers={"User-Agent": BASE_UA, "Content-Type": "application/json",
                     "origin": BASE_URL, "referer": f"{BASE_URL}/profile-edit"},
            timeout=20).json()
    except Exception as e:
        return {"error": str(e)}


def verify_otp(phone, otp):
    try:
        return requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": otp},
            headers={"User-Agent": BASE_UA, "Content-Type": "application/json",
                     "origin": BASE_URL, "referer": f"{BASE_URL}/profile-edit"},
            timeout=20).json()
    except Exception as e:
        return {"error": str(e)}


def do_verify_and_store(phone, otp):
    res = verify_otp(phone, otp)
    if "error" in res: return {"success": False, "error": res["error"], "raw": res}
    user = res.get("user", {}) if isinstance(res.get("user"), dict) else {}
    auth = res.get("token") or res.get("auth_token")
    if not auth: return {"success": False, "error": "No token", "raw": res}
    ttl = res.get("expires_at", 30*24*3600)
    try:
        ttl = int(ttl)
        if ttl > 1e9: ttl = max(300, ttl - int(time.time()))
    except: ttl = 30*24*3600
    SESSION.update(auth_token=auth, ttl=ttl)
    # clear old cf_token
    SESSION.cf_token = None
    return {"success": True, "session": SESSION.snapshot(), "user": user, "raw": res}


# ============================================================
# RC QUERY — get checksum from server
# ============================================================
def call_rc_query(vn, cf_token):
    try:
        r = requests.post(f"{BASE_URL}/api/nxcar/rc-query",
            json={"phone_number": CONFIG["phone"],
                  "vehicle_number": vn.upper(),
                  "cf_token": cf_token},
            headers=h(),
            timeout=30)
        print(f"[RCQ] {r.status_code}: {r.text[:300]}", flush=True)
        try: return {"status": r.status_code, "data": r.json()}
        except: return {"status": r.status_code, "data": r.text}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def find_checksum(obj):
    if isinstance(obj, dict):
        for k in ["checksum","hash","signature"]:
            v = obj.get(k)
            if isinstance(v, str) and len(v) == 32: return v
        for v in obj.values():
            r = find_checksum(v)
            if r: return r
    elif isinstance(obj, list):
        for i in obj:
            r = find_checksum(i)
            if r: return r
    elif isinstance(obj, str):
        m = re.search(r'\b[a-f0-9]{32}\b', obj)
        if m: return m.group(0)
    return None


# ============================================================
# VEHICLE DETAILS
# ============================================================
def call_vehicle_details(vn, checksum):
    try:
        r = requests.get("https://api.nxcar.in/vehicle_details",
            params={"vehicle_number": vn.upper(), "backend": "yes", "checksum": checksum},
            headers={
                "User-Agent": BASE_UA,
                "Accept-Encoding": "gzip, deflate, br",
                "sec-ch-ua-platform": '"Android"',
                "authorization": SESSION.auth_token or "",
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
            },
            timeout=30)
        print(f"[VD] {r.status_code}: {r.text[:300]}", flush=True)
        try: return {"status": r.status_code, "data": r.json()}
        except: return {"status": r.status_code, "data": r.text}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ============================================================
# FULL LOOKUP
# ============================================================
def full_lookup(vn):
    vn = vn.upper().strip()
    steps = []

    if not SESSION.is_valid():
        return {"success": False, "error": "Login karo pehle", "steps": steps}

    if not SESSION.cf_valid():
        steps.append("❌ cf_token missing or expired (max 90 sec valid)")
        steps.append("👉 Browser se fresh cf_token paste karo")
        return {
            "success": False,
            "error": "cf_token expired. Browser se fresh copy karo, 30 sec ke andar search karo.",
            "steps": steps,
            "session": SESSION.snapshot(),
        }

    age = int(time.time() - SESSION.cf_token_at)
    steps.append(f"✅ cf_token valid ({age}s old)")

    # rc-query
    steps.append("calling rc-query...")
    rcq = call_rc_query(vn, SESSION.cf_token)
    checksum = find_checksum(rcq.get("data"))

    if not checksum:
        steps.append("❌ No checksum in rc-query response")
        SESSION.cf_token = None  # invalidate
        return {
            "success": False,
            "error": "rc-query did not return checksum. cf_token expired or invalid.",
            "rc_query_response": rcq.get("data"),
            "steps": steps,
        }

    steps.append(f"✅ checksum from server: {checksum}")

    # vehicle_details
    steps.append("calling vehicle_details...")
    vd = call_vehicle_details(vn, checksum)

    vd_data = vd.get("data")
    is_ok = False
    if isinstance(vd_data, dict) and vd_data:
        is_ok = not (len(vd_data) == 1 and "message" in vd_data)
    elif isinstance(vd_data, list):
        is_ok = not (len(vd_data) == 1 and isinstance(vd_data[0], str)
                     and "try again" in vd_data[0].lower())

    if is_ok:
        steps.append("✅ vehicle details received")

    return {
        "success": is_ok,
        "vehicle_number": vn,
        "checksum": checksum,
        "checksum_source": "server-rc-query",
        "http_status": vd.get("status"),
        "steps": steps,
        "session": SESSION.snapshot(),
        "vehicle_details_response": vd_data,
        "rc_query_response": rcq.get("data"),
    }


# ============================================================
# ROUTES
# ============================================================
@app.route("/rc=<vehicle_number>")
def rc_api(vehicle_number):
    try:
        return jsonify(full_lookup(vehicle_number))
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/rc/<vehicle_number>")
def rc_api2(vehicle_number):
    return rc_api(vehicle_number)

@app.route("/session")
def sess(): return jsonify(SESSION.snapshot())

@app.route("/send-otp")
def api_send_otp():
    return jsonify(send_otp(request.args.get("phone", CONFIG["phone"])))

@app.route("/verify-otp")
def api_verify_otp():
    otp = request.args.get("otp")
    if not otp: return jsonify({"error": "otp required"}), 400
    return jsonify(do_verify_and_store(request.args.get("phone", CONFIG["phone"]), otp))

@app.route("/set-cf-token")
def set_cf():
    t = request.args.get("token")
    if not t: return jsonify({"error": "token required"}), 400
    SESSION.update(cf_token=t)
    return jsonify({
        "success": True,
        "cf_token": t[:40] + "...",
        "message": "✅ cf_token saved. Ab 90 sec ke andar /rc=<vehicle> kholo!",
        "expires_in": 90,
    })

@app.route("/reset-session")
def reset_session():
    SESSION.auth_token = None
    SESSION.cf_token = None
    SESSION.expires_at = 0
    try:
        if os.path.exists(CONFIG["token_file"]): os.remove(CONFIG["token_file"])
    except: pass
    return jsonify({"success": True})

@app.route("/healthz")
def healthz(): return jsonify({"ok": True})


# ============================================================
# HTML UI
# ============================================================
HTML = r"""
<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🚗 nxcar Auto RC</title>
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
.card h3{color:#00d4ff;margin-bottom:12px}
.warn{background:rgba(255,171,0,.1);border:1px solid rgba(255,171,0,.4);
padding:14px;border-radius:10px;margin-bottom:12px;font-size:.85rem;color:#ffd54f}
.search{display:flex;gap:10px;margin-bottom:20px}
input{flex:1;padding:14px;border-radius:12px;border:2px solid #444;
background:rgba(255,255,255,.05);color:#fff;font-size:1rem;outline:none}
input:focus{border-color:#00d4ff}
button{padding:14px 26px;border-radius:12px;border:none;cursor:pointer;
background:linear-gradient(135deg,#00d4ff,#7b2ff7);color:#fff;font-weight:600}
button:disabled{opacity:.6}
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
.steps{background:rgba(0,0,0,.3);padding:12px;border-radius:10px;font-size:.82rem;color:#b8ffb8}
.steps li{margin:4px 0;margin-left:20px}
code{background:rgba(0,212,255,.12);padding:2px 6px;border-radius:4px;color:#7fff7f}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
.kv{background:rgba(0,0,0,.3);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.08)}
.kv .k{font-size:.7rem;color:#888;text-transform:uppercase}
.kv .v{font-size:.9rem;color:#fff;font-weight:600;margin-top:4px;word-break:break-all}
</style></head><body>
<div class="c">
<h1>🚗 nxcar Auto RC</h1>
<p class="sub">cf_token 90 sec me expire hota hai — JALDI karo!</p>
<div class="status" id="status">Loading...</div>

<div class="warn">
⏱️ <b>IMPORTANT:</b> <code>cf_token</code> sirf <b>90 sec</b> valid hai. Browser se copy karke <b>turant</b> paste karo, phir vehicle search karo.
</div>

<div class="card">
<h3>1️⃣ Login</h3>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
<input id="phone" value="9612057455" style="max-width:200px">
<button onclick="sendOtp()">📩 Send OTP</button>
<input id="otp" placeholder="OTP" style="max-width:150px">
<button onclick="verifyOtp()">✅ Verify</button>
</div>
<div class="msg" id="loginMsg"></div>
</div>

<div class="card">
<h3>2️⃣ cf_token Paste Karo (turant!)</h3>
<p style="font-size:.8rem;color:#aaa;margin-bottom:8px">
nxcar.in/rc-check → F12 → Network → search → <code>rc-query</code> request → Payload → <code>cf_token</code> copy
</p>
<input id="cfToken" placeholder="Paste cf_token here" style="width:100%;margin-bottom:8px">
<button onclick="setCf()">💾 Save cf_token</button>
<div class="msg" id="cfMsg"></div>
</div>

<div class="card">
<h3>3️⃣ Vehicle Search (turant!)</h3>
<div class="search">
<input id="vnum" value="MH02FZ0555" onkeypress="if(event.key==='Enter')go()">
<button id="btn" onclick="go()">🔍 Search</button>
</div>
</div>

<div class="loader" id="loader"><div class="spin"></div>Fetching...</div>
<div id="result"></div>
</div>

<script>
async function checkSession(){
  try{
    const r = await fetch('/session');const d = await r.json();
    const el = document.getElementById('status');
    if(d.valid){
      let cfInfo = d.cf_valid ? `🟢 cf_token valid (${d.cf_age}s old)` : `🔴 cf_token expired/missing`;
      el.innerHTML = `Session OK • User ${d.user_id} • ${cfInfo}`;
      el.style.background = d.cf_valid ? 'rgba(0,200,83,.15)' : 'rgba(255,171,0,.15)';
    } else {
      el.innerHTML = `🔴 Not logged in`;
      el.style.background = 'rgba(255,23,68,.15)';
    }
  }catch(e){}
}
async function sendOtp(){
  const p = document.getElementById('phone').value.trim();
  document.getElementById('loginMsg').innerText = 'Sending...';
  const r = await fetch('/send-otp?phone=' + encodeURIComponent(p));
  const d = await r.json();
  document.getElementById('loginMsg').innerText = '📩 ' + JSON.stringify(d);
}
async function verifyOtp(){
  const p = document.getElementById('phone').value.trim();
  const o = document.getElementById('otp').value.trim();
  if(!o) return alert('OTP daalo');
  document.getElementById('loginMsg').innerText = 'Verifying...';
  const r = await fetch('/verify-otp?phone=' + encodeURIComponent(p) + '&otp=' + encodeURIComponent(o));
  const d = await r.json();
  document.getElementById('loginMsg').innerText = (d.success ? '✅ ' : '❌ ') + JSON.stringify(d);
  checkSession();
}
async function setCf(){
  const t = document.getElementById('cfToken').value.trim();
  if(!t) return alert('cf_token paste karo');
  const r = await fetch('/set-cf-token?token=' + encodeURIComponent(t));
  const d = await r.json();
  document.getElementById('cfMsg').innerText = JSON.stringify(d);
  checkSession();
  // auto-search after 1 sec
  setTimeout(go, 1000);
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
    let h = '';
    const b = d.success ? '<span class="badge ok">SUCCESS</span>' : '<span class="badge err">FAILED</span>';
    h += `<div class="card"><h3>📋 Summary ${b}</h3>
      <div class="grid">
        <div class="kv"><div class="k">Vehicle</div><div class="v">${d.vehicle_number||'-'}</div></div>
        <div class="kv"><div class="k">Checksum</div><div class="v"><code>${d.checksum||'-'}</code></div></div>
        <div class="kv"><div class="k">Source</div><div class="v">${d.checksum_source||'-'}</div></div>
        <div class="kv"><div class="k">HTTP</div><div class="v">${d.http_status||'-'}</div></div>
      </div>
      ${d.steps ? `<div class="steps" style="margin-top:12px"><b>Steps:</b><ul>${d.steps.map(s=>`<li>${s}</li>`).join('')}</ul></div>` : ''}
    </div>`;
    if(d.vehicle_details_response)
      h += `<div class="card"><h3>🚙 Vehicle Details</h3><pre>${JSON.stringify(d.vehicle_details_response,null,2)}</pre></div>`;
    if(d.rc_query_response)
      h += `<div class="card"><h3>📡 rc-query Response</h3><pre>${JSON.stringify(d.rc_query_response,null,2)}</pre></div>`;
    if(d.error)
      h += `<div class="card"><h3>⚠️ Error</h3><pre>${JSON.stringify(d.error,null,2)}</pre></div>`;
    document.getElementById('result').innerHTML = h;
  }catch(e){
    document.getElementById('result').innerHTML = `<div class="card"><pre>${e.message}</pre></div>`;
  }finally{
    document.getElementById('btn').disabled = false;
    document.getElementById('loader').classList.remove('active');
    checkSession();
  }
}
setInterval(checkSession, 3000);checkSession();
</script></body></html>
"""

@app.route("/")
def home(): return render_template_string(HTML)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
