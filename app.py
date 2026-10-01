# app.py — FINAL PRODUCTION (Render.com ready)
import os
import json
import time
import hashlib
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ============================================================
# CONFIG — Environment variables se override kar sakte ho
# ============================================================
CONFIG = {
    "phone":        os.environ.get("NX_PHONE", "9612057455"),
    "token_file":   os.environ.get("TOKEN_FILE", "/tmp/tokens.json"),
    "user_id":      os.environ.get("NX_USER_ID", "78786"),
    "otp":          os.environ.get("NX_OTP", ""),           # optional fixed OTP
    "auto_refresh": os.environ.get("AUTO_REFRESH", "true").lower() == "true",
}

BASE_UA  = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
BASE_URL = "https://www.nxcar.in"


# ============================================================
# ✅ REAL CHECKSUM ALGORITHM (reverse-engineered from JS)
#    md5(vehicle_number + "ssnx" + YYYY + MM + DD)   [UTC]
# ============================================================
def get_vehicle_checksum(vehicle_number: str) -> str:
    vn = vehicle_number.upper().strip()
    now = datetime.now(timezone.utc)
    raw = f"{vn}ssnx{now.year}{now.month:02d}{now.day:02d}"
    checksum = hashlib.md5(raw.encode()).hexdigest()
    print(f"[CHECKSUM] md5('{raw}') = {checksum}", flush=True)
    return checksum


# ============================================================
# SESSION — auto save/load tokens from file
# ============================================================
class Session:
    def __init__(self):
        self.cf_token   = None
        self.auth_token = None
        self.user_id    = CONFIG["user_id"]
        self.expires_at = 0
        self.lock       = threading.Lock()
        self.load()

    def is_valid(self):
        return bool(self.auth_token) and time.time() < self.expires_at - 120

    def update(self, cf_token=None, auth_token=None, user_id=None, ttl=7 * 24 * 3600):
        with self.lock:
            if cf_token:   self.cf_token   = cf_token
            if auth_token: self.auth_token = auth_token
            if user_id:    self.user_id    = str(user_id)
            self.expires_at = time.time() + ttl
            self.save()

    def snapshot(self):
        with self.lock:
            return {
                "cf_token":    (self.cf_token[:40] + "...") if self.cf_token else None,
                "auth_token":  (self.auth_token[:40] + "...") if self.auth_token else None,
                "user_id":     self.user_id,
                "expires_in":  max(0, int(self.expires_at - time.time())),
                "valid":       self.is_valid(),
            }

    def save(self):
        try:
            os.makedirs(os.path.dirname(CONFIG["token_file"]), exist_ok=True)
            with open(CONFIG["token_file"], "w") as f:
                json.dump({
                    "cf_token":   self.cf_token,
                    "auth_token": self.auth_token,
                    "user_id":    self.user_id,
                    "expires_at": self.expires_at,
                }, f)
        except Exception as e:
            print("[SESSION] save failed:", e, flush=True)

    def load(self):
        try:
            if os.path.exists(CONFIG["token_file"]):
                with open(CONFIG["token_file"]) as f:
                    d = json.load(f)
                self.cf_token   = d.get("cf_token")
                self.auth_token = d.get("auth_token")
                self.user_id    = d.get("user_id", CONFIG["user_id"])
                self.expires_at = d.get("expires_at", 0)
                print(f"[SESSION] Loaded. valid={self.is_valid()}", flush=True)
        except Exception as e:
            print("[SESSION] load failed:", e, flush=True)


SESSION = Session()


# ============================================================
# LOGIN FLOW
# ============================================================
def send_otp(phone):
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/send-otp",
            json={"phone": phone},
            headers={
                "User-Agent": BASE_UA,
                "Content-Type": "application/json",
                "origin": BASE_URL,
                "referer": f"{BASE_URL}/profile-edit",
            },
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def verify_otp(phone, otp):
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/verify-otp",
            json={"phone": phone, "otp": otp},
            headers={
                "User-Agent": BASE_UA,
                "Content-Type": "application/json",
                "origin": BASE_URL,
                "referer": f"{BASE_URL}/profile-edit",
            },
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_user_profile(auth_token, user_id):
    try:
        r = requests.get(
            f"{BASE_URL}/api/auth/user",
            headers={
                "User-Agent": BASE_UA,
                "referer": f"{BASE_URL}/profile-edit",
                "Cookie": f"auth_token={auth_token}; nxcar_user_id={user_id}; role_id=1",
            },
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def do_verify_and_store(phone, otp):
    res = verify_otp(phone, otp)
    print("[VERIFY]", res, flush=True)

    if "error" in res:
        return {"success": False, "error": res["error"], "raw": res}

    data = res.get("data", res) if isinstance(res, dict) else {}
    auth = (data.get("auth_token") or data.get("token") or
            data.get("access_token") or res.get("auth_token"))
    cf   = (data.get("cf_token") or data.get("cfToken") or res.get("cf_token"))
    uid  = (data.get("user_id") or data.get("id") or
            res.get("user_id") or CONFIG["user_id"])

    if not auth:
        return {"success": False, "error": "No auth_token in response", "raw": res}

    # If cf_token missing, try user profile
    if not cf:
        prof = fetch_user_profile(auth, str(uid))
        print("[PROFILE]", prof, flush=True)
        pd = prof.get("data", prof) if isinstance(prof, dict) else {}
        cf = pd.get("cf_token") or prof.get("cf_token")

    SESSION.update(cf_token=cf, auth_token=auth, user_id=str(uid))
    return {"success": True, "session": SESSION.snapshot(), "raw": res}


# ============================================================
# VEHICLE LOOKUP — clean flow, no rc-query needed
# ============================================================
def call_vehicle_details(vehicle_number, checksum):
    s = SESSION.snapshot()
    url = "https://api.nxcar.in/vehicle_details"
    params = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    headers = {
        "User-Agent": BASE_UA,
        "authorization": SESSION.auth_token or "",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        print(f"[VD] status={r.status_code} body={r.text[:200]}", flush=True)
        try:
            return r.json()
        except Exception:
            return {"_raw": r.text, "_status": r.status_code}
    except Exception as e:
        return {"error": str(e)}


def full_lookup(vehicle_number):
    vn = vehicle_number.upper().strip()

    if not SESSION.is_valid():
        return {
            "success": False,
            "error": "Session expired or not logged in. Open / to login.",
            "vehicle_number": vn,
            "session": SESSION.snapshot(),
        }

    checksum = get_vehicle_checksum(vn)
    vd = call_vehicle_details(vn, checksum)

    # Detect failure
    is_error = (
        isinstance(vd, dict) and "error" in vd and not vd.get("vehicle_number")
    ) or (
        isinstance(vd, list) and len(vd) == 1 and isinstance(vd[0], str)
        and "try again" in vd[0].lower()
    )

    return {
        "success": not is_error,
        "vehicle_number": vn,
        "auto_checksum": checksum,
        "algorithm": "md5(vn + 'ssnx' + YYYY + MM + DD) [UTC]",
        "checksum_source": "generated-locally",
        "session": SESSION.snapshot(),
        "vehicle_details_response": vd,
    }


# ============================================================
# AUTO REFRESH THREAD
# ============================================================
def auto_refresh_worker():
    while True:
        try:
            s = SESSION.snapshot()
            print(f"[AUTO] valid={s['valid']} expires_in={s['expires_in']}s", flush=True)
        except Exception as e:
            print("[AUTO] error:", e, flush=True)
        time.sleep(600)


if CONFIG["auto_refresh"]:
    threading.Thread(target=auto_refresh_worker, daemon=True).start()


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
def sess():
    return jsonify(SESSION.snapshot())


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "time": datetime.now(timezone.utc).isoformat()})


@app.route("/send-otp")
def api_send_otp():
    phone = request.args.get("phone", CONFIG["phone"])
    return jsonify(send_otp(phone))


@app.route("/verify-otp")
def api_verify_otp():
    phone = request.args.get("phone", CONFIG["phone"])
    otp   = request.args.get("otp", CONFIG["otp"])
    if not otp:
        return jsonify({"error": "otp required"}), 400
    return jsonify(do_verify_and_store(phone, otp))


@app.route("/checksum/<vehicle_number>")
def checksum_preview(vehicle_number):
    vn = vehicle_number.upper().strip()
    now = datetime.now(timezone.utc)
    raw = f"{vn}ssnx{now.year}{now.month:02d}{now.day:02d}"
    return jsonify({
        "vehicle_number": vn,
        "raw_string": raw,
        "checksum": hashlib.md5(raw.encode()).hexdigest(),
        "utc_time": now.isoformat(),
    })


# ============================================================
# HTML UI
# ============================================================
HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🚗 nxcar Auto RC</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
  min-height:100vh;color:#fff;padding:20px;
}
.c{max-width:960px;margin:0 auto}
h1{
  text-align:center;font-size:2.2rem;margin-bottom:8px;
  background:linear-gradient(90deg,#00d4ff,#7b2ff7);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}
.sub{text-align:center;color:#aaa;margin-bottom:20px;font-size:.85rem}
.status{
  text-align:center;font-size:.85rem;padding:12px;border-radius:12px;
  background:rgba(255,255,255,.05);margin-bottom:15px;
  border:1px solid rgba(255,255,255,.1);transition:.3s;
}
.card{
  background:rgba(255,255,255,.05);border-radius:16px;padding:20px;
  margin-bottom:15px;border:1px solid rgba(255,255,255,.1);
  backdrop-filter:blur(10px);
}
.card h3{color:#00d4ff;margin-bottom:14px;font-size:1.05rem}
.search{display:flex;gap:10px;margin-bottom:20px}
input{
  flex:1;padding:14px;border-radius:12px;border:2px solid #444;
  background:rgba(255,255,255,.05);color:#fff;font-size:1rem;
  text-transform:uppercase;outline:none;transition:.3s;
}
input:focus{border-color:#00d4ff;box-shadow:0 0 20px rgba(0,212,255,.25)}
button{
  padding:14px 26px;border-radius:12px;border:none;cursor:pointer;
  background:linear-gradient(135deg,#00d4ff,#7b2ff7);color:#fff;
  font-weight:600;font-size:.95rem;transition:.3s;
}
button:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(123,47,247,.4)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
pre{
  background:#0a0a1a;padding:16px;border-radius:10px;overflow:auto;
  font-size:.78rem;color:#b8ffb8;border:1px solid #1a1a3a;
  max-height:420px;font-family:'SF Mono',Monaco,Consolas,monospace;
}
.badge{
  display:inline-block;padding:4px 10px;border-radius:20px;
  font-size:.72rem;font-weight:600;margin-left:6px;
}
.ok{background:#00c853;color:#000}
.err{background:#ff1744;color:#fff}
.warn{background:#ffab00;color:#000}
.loader{display:none;text-align:center;padding:30px}
.loader.active{display:block}
.spin{
  width:50px;height:50px;border:4px solid rgba(255,255,255,.1);
  border-top-color:#00d4ff;border-radius:50%;
  animation:s 1s linear infinite;margin:0 auto 15px;
}
@keyframes s{to{transform:rotate(360deg)}}
.login-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.msg{font-size:.82rem;color:#aaa;margin-top:8px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
.kv{background:rgba(0,0,0,.3);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.08)}
.kv .k{font-size:.7rem;color:#888;text-transform:uppercase;letter-spacing:.5px}
.kv .v{font-size:.9rem;color:#fff;font-weight:600;margin-top:4px;word-break:break-all}
code{background:rgba(0,212,255,.12);padding:2px 6px;border-radius:4px;color:#7fff7f;font-size:.85rem}
</style>
</head>
<body>
<div class="c">
  <h1>🚗 nxcar Auto RC</h1>
  <p class="sub">Auto Login • Auto Checksum • Real Algorithm Decoded</p>

  <div class="status" id="status">⏳ Checking session...</div>

  <div class="card">
    <h3>🔐 Login</h3>
    <div class="login-row">
      <input id="phone" value="9612057455" placeholder="Phone number" style="max-width:220px">
      <button onclick="sendOtp()">📩 Send OTP</button>
      <input id="otp" placeholder="Enter OTP" style="max-width:150px">
      <button onclick="verifyOtp()">✅ Verify</button>
    </div>
    <div class="msg" id="loginMsg"></div>
  </div>

  <div class="search">
    <input id="vnum" value="MH02FZ0555" placeholder="Vehicle Number (e.g. MH02FZ0555)"
           onkeypress="if(event.key==='Enter')go()">
    <button id="btn" onclick="go()">🔍 Search</button>
  </div>

  <div class="loader" id="loader">
    <div class="spin"></div>
    <div>Fetching vehicle details...</div>
  </div>

  <div id="result"></div>
</div>

<script>
async function checkSession(){
  try{
    const r = await fetch('/session');
    const d = await r.json();
    const el = document.getElementById('status');
    if(d.valid){
      el.innerHTML = `🟢 Session OK • User ${d.user_id} • Expires in ${d.expires_in}s`;
      el.style.background = 'rgba(0,200,83,.15)';
      el.style.borderColor = 'rgba(0,200,83,.3)';
    } else {
      el.innerHTML = `🔴 Not logged in — Send OTP & Verify above`;
      el.style.background = 'rgba(255,23,68,.15)';
      el.style.borderColor = 'rgba(255,23,68,.3)';
    }
  }catch(e){}
}

async function sendOtp(){
  const p = document.getElementById('phone').value.trim();
  if(!p) return alert('Enter phone');
  const msg = document.getElementById('loginMsg');
  msg.innerText = '📤 Sending OTP...';
  try{
    const r = await fetch('/send-otp?phone=' + encodeURIComponent(p));
    const d = await r.json();
    msg.innerText = '📩 ' + JSON.stringify(d);
  }catch(e){ msg.innerText = '❌ ' + e.message; }
}

async function verifyOtp(){
  const p = document.getElementById('phone').value.trim();
  const o = document.getElementById('otp').value.trim();
  if(!o) return alert('Enter OTP');
  const msg = document.getElementById('loginMsg');
  msg.innerText = '🔐 Verifying...';
  try{
    const r = await fetch('/verify-otp?phone=' + encodeURIComponent(p) + '&otp=' + encodeURIComponent(o));
    const d = await r.json();
    msg.innerText = (d.success ? '✅ ' : '❌ ') + JSON.stringify(d);
    checkSession();
  }catch(e){ msg.innerText = '❌ ' + e.message; }
}

async function go(){
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  if(!v) return alert('Enter vehicle number');
  const btn = document.getElementById('btn');
  const loader = document.getElementById('loader');
  btn.disabled = true;
  loader.classList.add('active');
  document.getElementById('result').innerHTML = '';
  try{
    const r = await fetch('/rc=' + encodeURIComponent(v));
    const d = await r.json();
    render(d);
  }catch(e){
    document.getElementById('result').innerHTML =
      `<div class="card"><h3>❌ Network Error</h3><pre>${e.message}</pre></div>`;
  }finally{
    btn.disabled = false;
    loader.classList.remove('active');
  }
}

function render(d){
  const r = document.getElementById('result');
  let h = '';

  // Summary
  const okBadge = d.success
    ? '<span class="badge ok">SUCCESS</span>'
    : '<span class="badge err">FAILED</span>';

  h += `<div class="card">
    <h3>📋 Summary ${okBadge}</h3>
    <div class="grid">
      <div class="kv"><div class="k">Vehicle</div><div class="v">${d.vehicle_number || '-'}</div></div>
      <div class="kv"><div class="k">Checksum</div><div class="v"><code>${d.auto_checksum || '-'}</code></div></div>
      <div class="kv"><div class="k">Source</div><div class="v">${d.checksum_source || '-'}</div></div>
      <div class="kv"><div class="k">Session</div><div class="v">${d.session && d.session.expires_in ? d.session.expires_in + 's' : '-'}</div></div>
    </div>
    <p style="margin-top:12px;font-size:.78rem;color:#888">Algorithm: ${d.algorithm || '-'}</p>
  </div>`;

  // Vehicle details — try to extract clean
  const vd = d.vehicle_details_response;
  if(vd){
    h += `<div class="card"><h3>🚙 Vehicle Details</h3>
      <pre>${JSON.stringify(vd, null, 2)}</pre></div>`;
  }

  if(d.error){
    h += `<div class="card"><h3>⚠️ Error</h3>
      <pre>${JSON.stringify(d.error, null, 2)}</pre></div>`;
  }

  r.innerHTML = h;
}

setInterval(checkSession, 5000);
checkSession();
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60, flush=True)
    print("🚗 nxcar Auto RC — FINAL BUILD", flush=True)
    print(f"✅ Checksum: md5(vn + 'ssnx' + YYYYMMDD) [UTC]", flush=True)
    print(f"🌐 Listening on port {port}", flush=True)
    print("=" * 60, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
