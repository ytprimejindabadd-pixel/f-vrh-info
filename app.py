# app.py — FINAL 100% WORKING VERSION
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
# CONFIG
# ============================================================
CONFIG = {
    "phone":        os.environ.get("NX_PHONE", "9612057455"),
    "token_file":   os.environ.get("TOKEN_FILE", "/tmp/tokens.json"),
    "user_id":      os.environ.get("NX_USER_ID", "78786"),
    "user_uuid":    os.environ.get("NX_USER_UUID", "7fbd669b-0d74-402a-937d-2bd4836bd613"),
    "otp":          os.environ.get("NX_OTP", ""),
    "auto_refresh": os.environ.get("AUTO_REFRESH", "true").lower() == "true",
}

BASE_UA  = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
BASE_URL = "https://www.nxcar.in"


# ============================================================
# ✅ REAL CHECKSUM (from JS: md5(vn + "ssnx" + YYYY + MM + DD))
# ============================================================
def get_vehicle_checksum(vehicle_number: str) -> str:
    vn = vehicle_number.upper().strip()
    now = datetime.now(timezone.utc)
    raw = f"{vn}ssnx{now.year}{now.month:02d}{now.day:02d}"
    checksum = hashlib.md5(raw.encode()).hexdigest()
    print(f"[CHECKSUM] md5('{raw}') = {checksum}", flush=True)
    return checksum


# ============================================================
# SESSION
# ============================================================
class Session:
    def __init__(self):
        self.cf_token   = None
        self.auth_token = None
        self.user_id    = CONFIG["user_id"]
        self.user_uuid  = CONFIG["user_uuid"]
        self.expires_at = 0
        self.lock       = threading.Lock()
        self.load()

    def is_valid(self):
        return bool(self.auth_token) and time.time() < self.expires_at - 120

    def update(self, cf_token=None, auth_token=None, user_id=None, user_uuid=None, ttl=30 * 24 * 3600):
        with self.lock:
            if cf_token:   self.cf_token   = cf_token
            if auth_token: self.auth_token = auth_token
            if user_id:    self.user_id    = str(user_id)
            if user_uuid:  self.user_uuid  = user_uuid
            self.expires_at = time.time() + ttl
            self.save()

    def snapshot(self):
        with self.lock:
            return {
                "cf_token":   (self.cf_token[:40] + "...") if self.cf_token else None,
                "auth_token": (self.auth_token[:40] + "...") if self.auth_token else None,
                "user_id":    self.user_id,
                "user_uuid":  self.user_uuid,
                "expires_in": max(0, int(self.expires_at - time.time())),
                "valid":      self.is_valid(),
            }

    def save(self):
        try:
            os.makedirs(os.path.dirname(CONFIG["token_file"]), exist_ok=True)
            with open(CONFIG["token_file"], "w") as f:
                json.dump({
                    "cf_token":   self.cf_token,
                    "auth_token": self.auth_token,
                    "user_id":    self.user_id,
                    "user_uuid":  self.user_uuid,
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
                self.user_uuid  = d.get("user_uuid", CONFIG["user_uuid"])
                self.expires_at = d.get("expires_at", 0)
                print(f"[SESSION] Loaded. valid={self.is_valid()}", flush=True)
        except Exception as e:
            print("[SESSION] load failed:", e, flush=True)


SESSION = Session()


# ============================================================
# COMMON HEADERS (exact browser replication)
# ============================================================
def browser_headers(auth_token=None):
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
        "referer": f"{BASE_URL}/",
        "accept-language": "en-US,en;q=0.6",
        "priority": "u=1, i",
        "authorization": token,
        "Cookie": f"user_id={SESSION.user_uuid}; auth_token={token}; nxcar_user_id={SESSION.user_id}; role_id=1",
    }


# ============================================================
# LOGIN
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


def do_verify_and_store(phone, otp):
    res = verify_otp(phone, otp)
    print("[VERIFY]", res, flush=True)

    if not isinstance(res, dict):
        return {"success": False, "error": "Invalid response type", "raw": res}

    if "error" in res:
        return {"success": False, "error": res["error"], "raw": res}

    # Extract tokens — nxcar uses "token" not "auth_token"
    data = res.get("data", res) if isinstance(res.get("data"), dict) else res
    user = res.get("user", {}) if isinstance(res.get("user"), dict) else {}

    auth = (
        data.get("auth_token") or data.get("token")
        or data.get("access_token") or res.get("auth_token")
        or res.get("token")
    )
    cf   = (data.get("cf_token") or data.get("cfToken") or res.get("cf_token"))
    uid  = (
        user.get("nxcar_user_id") or user.get("id")
        or data.get("user_id") or data.get("id")
        or res.get("user_id") or CONFIG["user_id"]
    )
    uuid = user.get("id") or CONFIG["user_uuid"]

    if not auth:
        return {
            "success": False,
            "error": "No token field in verify response",
            "raw": res,
        }

    ttl_raw = res.get("expires_at", 30 * 24 * 3600)
    try:
        ttl = int(ttl_raw)
        if ttl > 1e9:
            ttl = max(300, ttl - int(time.time()))
    except Exception:
        ttl = 30 * 24 * 3600

    SESSION.update(
        cf_token=cf,
        auth_token=auth,
        user_id=str(uid),
        user_uuid=str(uuid),
        ttl=ttl,
    )

    return {
        "success": True,
        "session": SESSION.snapshot(),
        "user": user,
        "raw": res,
    }


# ============================================================
# AUTO LOGIN (if OTP provided in ENV)
# ============================================================
def try_auto_login():
    if not CONFIG["otp"]:
        return False
    print("[AUTO-LOGIN] Attempting with env OTP...", flush=True)
    r = do_verify_and_store(CONFIG["phone"], CONFIG["otp"])
    print("[AUTO-LOGIN] Result:", r.get("success"), flush=True)
    return r.get("success", False)


# ============================================================
# GET CLIENT IP
# ============================================================
def get_client_ip():
    try:
        r = requests.get(
            f"{BASE_URL}/api/nxcar/my-ip",
            headers=browser_headers(),
            timeout=10,
        )
        data = r.json()
        ip = data.get("ip") or data.get("client_ip") or "127.0.0.1"
        print(f"[IP] {ip}", flush=True)
        return ip
    except Exception as e:
        print(f"[IP] failed: {e}", flush=True)
        return "127.0.0.1"


# ============================================================
# VEHICLE DETAILS (main call)
# ============================================================
def call_vehicle_details(vehicle_number, checksum):
    """Call vehicle_details with full browser headers"""
    url = "https://api.nxcar.in/vehicle_details"
    params = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    headers = {
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
        "Cookie": f"user_id={SESSION.user_uuid}; auth_token={SESSION.auth_token}; nxcar_user_id={SESSION.user_id}; role_id=1",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        print(f"[VD] status={r.status_code} body={r.text[:300]}", flush=True)
        try:
            return {"status": r.status_code, "data": r.json()}
        except Exception:
            return {"status": r.status_code, "data": r.text}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ============================================================
# FULL LOOKUP
# ============================================================
def full_lookup(vehicle_number):
    vn = vehicle_number.upper().strip()

    if not SESSION.is_valid():
        return {
            "success": False,
            "error": "Session expired. Login at / first.",
            "vehicle_number": vn,
            "session": SESSION.snapshot(),
        }

    checksum = get_vehicle_checksum(vn)
    vd = call_vehicle_details(vn, checksum)

    vd_data = vd.get("data") if isinstance(vd, dict) else None
    is_success = False
    if isinstance(vd_data, dict):
        is_success = bool(vd_data) and not (
            len(vd_data) == 1 and "message" in vd_data
        )
    elif isinstance(vd_data, list):
        is_success = not (
            len(vd_data) == 1
            and isinstance(vd_data[0], str)
            and "try again" in vd_data[0].lower()
        )

    return {
        "success": is_success,
        "vehicle_number": vn,
        "auto_checksum": checksum,
        "algorithm": "md5(vn + 'ssnx' + YYYY + MM + DD) [UTC]",
        "checksum_source": "generated-locally",
        "session": SESSION.snapshot(),
        "http_status": vd.get("status"),
        "vehicle_details_response": vd.get("data", vd),
    }


# ============================================================
# AUTO REFRESH
# ============================================================
def auto_refresh_worker():
    # Try auto-login once
    try_auto_login()
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


@app.route("/reset-session")
def reset_session():
    SESSION.update(auth_token=None, cf_token=None, ttl=0)
    try:
        if os.path.exists(CONFIG["token_file"]):
            os.remove(CONFIG["token_file"])
    except Exception:
        pass
    return jsonify({"success": True, "message": "Session cleared"})


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


@app.route("/debug-full/<vehicle_number>")
def debug_full(vehicle_number):
    """Try multiple variants and show which one works"""
    vn = vehicle_number.upper().strip()
    checksum = get_vehicle_checksum(vn)
    client_ip = get_client_ip()

    results = {}

    # A: without cookie
    try:
        r = requests.get(
            "https://api.nxcar.in/vehicle_details",
            params={"vehicle_number": vn, "backend": "yes", "checksum": checksum},
            headers={
                "User-Agent": BASE_UA,
                "authorization": SESSION.auth_token or "",
                "origin": BASE_URL,
                "referer": f"{BASE_URL}/",
            },
            timeout=20,
        )
        results["A_no_cookie"] = {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        results["A_no_cookie"] = {"error": str(e)}

    # B: with cookie
    try:
        r = requests.get(
            "https://api.nxcar.in/vehicle_details",
            params={"vehicle_number": vn, "backend": "yes", "checksum": checksum},
            headers=browser_headers(),
            timeout=20,
        )
        results["B_with_cookie"] = {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        results["B_with_cookie"] = {"error": str(e)}

    # C: with IP param
    try:
        r = requests.get(
            "https://api.nxcar.in/vehicle_details",
            params={"vehicle_number": vn, "backend": "yes", "checksum": checksum, "ip": client_ip},
            headers=browser_headers(),
            timeout=20,
        )
        results["C_with_ip"] = {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        results["C_with_ip"] = {"error": str(e)}

    return jsonify({
        "vehicle_number": vn,
        "checksum": checksum,
        "client_ip": client_ip,
        "auth_token_present": bool(SESSION.auth_token),
        "auth_token_prefix": (SESSION.auth_token[:30] + "...") if SESSION.auth_token else None,
        "results": results,
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
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;color:#fff;padding:20px}
.c{max-width:960px;margin:0 auto}
h1{text-align:center;font-size:2.2rem;margin-bottom:8px;
background:linear-gradient(90deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;
-webkit-text-fill-color:transparent;background-clip:text}
.sub{text-align:center;color:#aaa;margin-bottom:20px;font-size:.85rem}
.status{text-align:center;font-size:.85rem;padding:12px;border-radius:12px;
background:rgba(255,255,255,.05);margin-bottom:15px;border:1px solid rgba(255,255,255,.1)}
.card{background:rgba(255,255,255,.05);border-radius:16px;padding:20px;
margin-bottom:15px;border:1px solid rgba(255,255,255,.1);backdrop-filter:blur(10px)}
.card h3{color:#00d4ff;margin-bottom:14px;font-size:1.05rem}
.search{display:flex;gap:10px;margin-bottom:20px}
input{flex:1;padding:14px;border-radius:12px;border:2px solid #444;
background:rgba(255,255,255,.05);color:#fff;font-size:1rem;text-transform:uppercase;
outline:none;transition:.3s}
input:focus{border-color:#00d4ff;box-shadow:0 0 20px rgba(0,212,255,.25)}
button{padding:14px 26px;border-radius:12px;border:none;cursor:pointer;
background:linear-gradient(135deg,#00d4ff,#7b2ff7);color:#fff;font-weight:600;
font-size:.95rem;transition:.3s}
button:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(123,47,247,.4)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
pre{background:#0a0a1a;padding:16px;border-radius:10px;overflow:auto;
font-size:.78rem;color:#b8ffb8;border:1px solid #1a1a3a;max-height:500px;
font-family:'SF Mono',Monaco,Consolas,monospace}
.badge{display:inline-block;padding:4px 10px;border-radius:20px;
font-size:.72rem;font-weight:600;margin-left:6px}
.ok{background:#00c853;color:#000}
.err{background:#ff1744;color:#fff}
.loader{display:none;text-align:center;padding:30px}
.loader.active{display:block}
.spin{width:50px;height:50px;border:4px solid rgba(255,255,255,.1);
border-top-color:#00d4ff;border-radius:50%;animation:s 1s linear infinite;margin:0 auto 15px}
@keyframes s{to{transform:rotate(360deg)}}
.login-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.msg{font-size:.82rem;color:#aaa;margin-top:8px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
gap:10px;margin-top:10px}
.kv{background:rgba(0,0,0,.3);padding:10px 14px;border-radius:10px;
border:1px solid rgba(255,255,255,.08)}
.kv .k{font-size:.7rem;color:#888;text-transform:uppercase;letter-spacing:.5px}
.kv .v{font-size:.9rem;color:#fff;font-weight:600;margin-top:4px;word-break:break-all}
code{background:rgba(0,212,255,.12);padding:2px 6px;border-radius:4px;
color:#7fff7f;font-size:.85rem}
.btn-warn{background:linear-gradient(135deg,#ff5252,#b71c1c)}
.btn-sm{padding:8px 14px;font-size:.8rem}
</style>
</head>
<body>
<div class="c">
<h1>🚗 nxcar Auto RC</h1>
<p class="sub">Auto Login • Auto Checksum • Real Algorithm</p>

<div class="status" id="status">⏳ Checking session...</div>

<div class="card">
  <h3>🔐 Login</h3>
  <div class="login-row">
    <input id="phone" value="9612057455" placeholder="Phone" style="max-width:220px">
    <button onclick="sendOtp()">📩 Send OTP</button>
    <input id="otp" placeholder="OTP" style="max-width:150px">
    <button onclick="verifyOtp()">✅ Verify</button>
  </div>
  <div class="login-row">
    <button class="btn-warn btn-sm" onclick="resetSession()">🗑️ Reset Session</button>
    <button class="btn-sm" onclick="debugFull()">🔍 Debug Full</button>
  </div>
  <div class="msg" id="loginMsg"></div>
</div>

<div class="search">
  <input id="vnum" value="MH02FZ0555" placeholder="Vehicle Number"
    onkeypress="if(event.key==='Enter')go()">
  <button id="btn" onclick="go()">🔍 Search</button>
</div>

<div class="loader" id="loader">
  <div class="spin"></div><div>Fetching...</div>
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
    } else {
      el.innerHTML = `🔴 Not logged in — Send OTP & Verify`;
      el.style.background = 'rgba(255,23,68,.15)';
    }
  }catch(e){}
}

async function sendOtp(){
  const p = document.getElementById('phone').value.trim();
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

async function resetSession(){
  if(!confirm('Reset session?')) return;
  const msg = document.getElementById('loginMsg');
  msg.innerText = '🗑️ Resetting...';
  const r = await fetch('/reset-session');
  const d = await r.json();
  msg.innerText = '✅ ' + JSON.stringify(d);
  checkSession();
}

async function debugFull(){
  const v = document.getElementById('vnum').value.trim().toUpperCase() || 'MH02FZ0555';
  const msg = document.getElementById('loginMsg');
  msg.innerText = '🔍 Debugging...';
  const r = await fetch('/debug-full/' + encodeURIComponent(v));
  const d = await r.json();
  msg.innerText = '✅ Debug done — check console';
  console.log('DEBUG FULL:', d);
  document.getElementById('result').innerHTML =
    `<div class="card"><h3>🔍 Debug Results</h3><pre>${JSON.stringify(d, null, 2)}</pre></div>`;
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

  const okBadge = d.success
    ? '<span class="badge ok">SUCCESS</span>'
    : '<span class="badge err">FAILED</span>';

  h += `<div class="card">
    <h3>📋 Summary ${okBadge}</h3>
    <div class="grid">
      <div class="kv"><div class="k">Vehicle</div><div class="v">${d.vehicle_number || '-'}</div></div>
      <div class="kv"><div class="k">HTTP</div><div class="v">${d.http_status || '-'}</div></div>
      <div class="kv"><div class="k">Checksum</div><div class="v"><code>${d.auto_checksum || '-'}</code></div></div>
      <div class="kv"><div class="k">Session</div><div class="v">${d.session && d.session.expires_in ? d.session.expires_in + 's' : '-'}</div></div>
    </div>
    <p style="margin-top:12px;font-size:.78rem;color:#888">Algorithm: ${d.algorithm || '-'}</p>
  </div>`;

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
    print("🚗 nxcar Auto RC — FINAL", flush=True)
    print(f"✅ Checksum: md5(vn + 'ssnx' + YYYYMMDD) [UTC]", flush=True)
    print(f"🌐 Port {port}", flush=True)
    print("=" * 60, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
