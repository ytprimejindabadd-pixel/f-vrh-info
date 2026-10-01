# app.py — FULL AUTO FINAL
import os, json, time, threading, hashlib
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

CONFIG = {
    "phone":        os.environ.get("NX_PHONE", "9612057455"),
    "token_file":   os.environ.get("TOKEN_FILE", "/tmp/tokens.json"),
    "user_id":      os.environ.get("NX_USER_ID", "78786"),
    "user_uuid":    os.environ.get("NX_USER_UUID", "7fbd669b-0d74-402a-937d-2bd4836bd613"),
    "otp":          os.environ.get("NX_OTP", ""),
    "auto_refresh": True,
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
        self.user_id = CONFIG["user_id"]
        self.user_uuid = CONFIG["user_uuid"]
        self.expires_at = 0
        self.lock = threading.Lock()
        self.load()

    def is_valid(self):
        return bool(self.auth_token) and time.time() < self.expires_at - 120

    def update(self, auth_token=None, cf_token=None, user_id=None, user_uuid=None, ttl=30*24*3600):
        with self.lock:
            if auth_token: self.auth_token = auth_token
            if cf_token: self.cf_token = cf_token
            if user_id: self.user_id = str(user_id)
            if user_uuid: self.user_uuid = str(user_uuid)
            self.expires_at = time.time() + ttl
            self.save()

    def snapshot(self):
        with self.lock:
            return {
                "auth_token": (self.auth_token[:40] + "...") if self.auth_token else None,
                "cf_token":   (self.cf_token[:40] + "...") if self.cf_token else None,
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
                    "auth_token": self.auth_token,
                    "cf_token": self.cf_token,
                    "user_id": self.user_id,
                    "user_uuid": self.user_uuid,
                    "expires_at": self.expires_at,
                }, f)
        except Exception as e:
            print("[SAVE]", e, flush=True)

    def load(self):
        try:
            if os.path.exists(CONFIG["token_file"]):
                with open(CONFIG["token_file"]) as f:
                    d = json.load(f)
                self.auth_token = d.get("auth_token")
                self.cf_token = d.get("cf_token")
                self.user_id = d.get("user_id", CONFIG["user_id"])
                self.user_uuid = d.get("user_uuid", CONFIG["user_uuid"])
                self.expires_at = d.get("expires_at", 0)
                print(f"[LOAD] valid={self.is_valid()}", flush=True)
        except Exception as e:
            print("[LOAD]", e, flush=True)

SESSION = Session()


# ============================================================
# HEADERS
# ============================================================
def headers_common(auth_token=None, referer="/"):
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
        "referer": f"{BASE_URL}{referer}",
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
        r = requests.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone},
            headers={"User-Agent": BASE_UA, "Content-Type": "application/json",
                     "origin": BASE_URL, "referer": f"{BASE_URL}/profile-edit"}, timeout=20)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def verify_otp(phone, otp):
    try:
        r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": otp},
            headers={"User-Agent": BASE_UA, "Content-Type": "application/json",
                     "origin": BASE_URL, "referer": f"{BASE_URL}/profile-edit"}, timeout=20)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def do_verify_and_store(phone, otp):
    res = verify_otp(phone, otp)
    if not isinstance(res, dict): return {"success": False, "error": "bad response", "raw": res}
    if "error" in res: return {"success": False, "error": res["error"], "raw": res}
    user = res.get("user", {}) if isinstance(res.get("user"), dict) else {}
    auth = res.get("token") or res.get("auth_token") or res.get("data", {}).get("token")
    if not auth: return {"success": False, "error": "No token", "raw": res}
    uid = user.get("nxcar_user_id") or CONFIG["user_id"]
    uuid = user.get("id") or CONFIG["user_uuid"]
    ttl = res.get("expires_at", 30*24*3600)
    try:
        ttl = int(ttl)
        if ttl > 1e9: ttl = max(300, ttl - int(time.time()))
    except: ttl = 30*24*3600
    SESSION.update(auth_token=auth, user_id=str(uid), user_uuid=str(uuid), ttl=ttl)
    return {"success": True, "session": SESSION.snapshot(), "user": user, "raw": res}


# ============================================================
# CAPTURE CF_TOKEN FROM BROWSER (Selenium)
# ============================================================
def capture_cf_token(vehicle_number):
    """
    Opens nxcar.in in headless Chrome, types vehicle number,
    captures the cf_token from the rc-query POST request.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("[SELENIUM] not installed", flush=True)
        return None

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=412,915")
    opts.add_argument(f"user-agent={BASE_UA}")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = None
    cf_token = None
    try:
        driver = webdriver.Chrome(options=opts)
        # Set cookies first
        driver.get(BASE_URL)
        time.sleep(1)
        driver.add_cookie({"name": "auth_token", "value": SESSION.auth_token, "domain": ".nxcar.in"})
        driver.add_cookie({"name": "nxcar_user_id", "value": SESSION.user_id, "domain": ".nxcar.in"})
        driver.add_cookie({"name": "user_id", "value": SESSION.user_uuid, "domain": ".nxcar.in"})
        driver.add_cookie({"name": "role_id", "value": "1", "domain": ".nxcar.in"})

        # Go to rc-check page
        driver.get(f"{BASE_URL}/rc-check")
        time.sleep(3)

        # Find input and type vehicle number
        try:
            inp = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
            )
            inp.clear()
            inp.send_keys(vehicle_number)
            time.sleep(1)

            # Click search button
            btns = driver.find_elements(By.TAG_NAME, "button")
            for b in btns:
                if "search" in b.text.lower() or "check" in b.text.lower() or "get" in b.text.lower():
                    b.click()
                    break
        except Exception as e:
            print(f"[SELENIUM] form: {e}", flush=True)

        # Wait for network
        time.sleep(6)

        # Read performance logs
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg["method"] == "Network.requestWillBeSent":
                    url = msg["params"]["request"]["url"]
                    if "rc-query" in url:
                        post_data = msg["params"]["request"].get("postData", "")
                        if post_data:
                            try:
                                body = json.loads(post_data)
                                if body.get("cf_token"):
                                    cf_token = body["cf_token"]
                                    print(f"[SELENIUM] ✅ cf_token captured", flush=True)
                                    break
                            except: pass
            except: continue
    except Exception as e:
        print(f"[SELENIUM] error: {e}", flush=True)
    finally:
        if driver: driver.quit()

    return cf_token


# ============================================================
# RC QUERY (main call — gets checksum from server)
# ============================================================
def call_rc_query(vehicle_number, cf_token):
    """POST rc-query → gets checksum from server"""
    url = f"{BASE_URL}/api/nxcar/rc-query"
    payload = {
        "phone_number": CONFIG["phone"],
        "vehicle_number": vehicle_number.upper(),
        "cf_token": cf_token,
    }
    headers = headers_common(referer="/rc-check")
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[RCQ] status={r.status_code} body={r.text[:300]}", flush=True)
        try:
            return {"status": r.status_code, "data": r.json()}
        except:
            return {"status": r.status_code, "data": r.text}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def extract_checksum(obj):
    """Recursively search for 32-char checksum"""
    if isinstance(obj, dict):
        for k in ["checksum", "hash", "signature"]:
            v = obj.get(k)
            if isinstance(v, str) and len(v) == 32: return v
        for v in obj.values():
            r = extract_checksum(v)
            if r: return r
    elif isinstance(obj, list):
        for i in obj:
            r = extract_checksum(i)
            if r: return r
    elif isinstance(obj, str):
        import re
        m = re.search(r'\b[a-f0-9]{32}\b', obj)
        if m: return m.group(0)
    return None


# ============================================================
# VEHICLE DETAILS
# ============================================================
def call_vehicle_details(vehicle_number, checksum):
    url = "https://api.nxcar.in/vehicle_details"
    params = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    headers = headers_common()
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        print(f"[VD] status={r.status_code} body={r.text[:300]}", flush=True)
        try:
            return {"status": r.status_code, "data": r.json()}
        except:
            return {"status": r.status_code, "data": r.text}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ============================================================
# FULL LOOKUP — Auto flow
# ============================================================
def full_lookup(vehicle_number):
    vn = vehicle_number.upper().strip()
    if not SESSION.is_valid():
        return {"success": False, "error": "Session expired. Login first.",
                "vehicle_number": vn, "session": SESSION.snapshot()}

    steps = []

    # STEP 1: get fresh cf_token via Selenium (if not cached)
    cf_token = SESSION.cf_token
    if not cf_token:
        steps.append("capturing cf_token via browser...")
        cf_token = capture_cf_token(vn)
        if cf_token:
            SESSION.update(cf_token=cf_token)
            steps.append("cf_token captured ✅")
        else:
            steps.append("cf_token capture failed ❌")
            return {
                "success": False,
                "error": "Could not capture cf_token. Chrome install karo ya manual mode use karo.",
                "steps": steps,
                "hint": "Manual mode: /manual-cf-token?token=...",
                "session": SESSION.snapshot(),
            }

    # STEP 2: rc-query with cf_token → get checksum
    steps.append("calling rc-query...")
    rcq = call_rc_query(vn, cf_token)
    checksum = extract_checksum(rcq.get("data"))

    if not checksum:
        steps.append("no checksum in rc-query response ❌")
        # cf_token may have expired — clear it and retry once
        SESSION.cf_token = None
        return {
            "success": False,
            "error": "rc-query did not return checksum. cf_token may be expired.",
            "rc_query_response": rcq.get("data"),
            "steps": steps,
            "session": SESSION.snapshot(),
        }

    steps.append(f"checksum from server: {checksum}")

    # STEP 3: vehicle_details
    steps.append("calling vehicle_details...")
    vd = call_vehicle_details(vn, checksum)

    vd_data = vd.get("data")
    is_success = False
    if isinstance(vd_data, dict) and vd_data:
        is_success = not (len(vd_data) == 1 and "message" in vd_data)
    elif isinstance(vd_data, list):
        is_success = not (len(vd_data) == 1 and isinstance(vd_data[0], str)
                          and "try again" in vd_data[0].lower())

    return {
        "success": is_success,
        "vehicle_number": vn,
        "checksum": checksum,
        "checksum_source": "server-rc-query",
        "steps": steps,
        "session": SESSION.snapshot(),
        "http_status": vd.get("status"),
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
def sess():
    return jsonify(SESSION.snapshot())


@app.route("/send-otp")
def api_send_otp():
    return jsonify(send_otp(request.args.get("phone", CONFIG["phone"])))


@app.route("/verify-otp")
def api_verify_otp():
    otp = request.args.get("otp", CONFIG["otp"])
    if not otp: return jsonify({"error": "otp required"}), 400
    return jsonify(do_verify_and_store(request.args.get("phone", CONFIG["phone"]), otp))


@app.route("/reset-session")
def reset_session():
    SESSION.update(auth_token=None, cf_token=None, ttl=0)
    try:
        if os.path.exists(CONFIG["token_file"]): os.remove(CONFIG["token_file"])
    except: pass
    return jsonify({"success": True, "message": "cleared"})


@app.route("/manual-cf-token")
def manual_cf_token():
    """Manually provide a cf_token from browser DevTools"""
    token = request.args.get("token")
    if not token: return jsonify({"error": "token required"}), 400
    SESSION.update(cf_token=token)
    return jsonify({"success": True, "cf_token": token[:40] + "..."})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


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
h1{text-align:center;font-size:2.2rem;margin-bottom:8px;
background:linear-gradient(90deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;
-webkit-text-fill-color:transparent}
.sub{text-align:center;color:#aaa;margin-bottom:20px;font-size:.85rem}
.status{text-align:center;font-size:.85rem;padding:12px;border-radius:12px;
background:rgba(255,255,255,.05);margin-bottom:15px;border:1px solid rgba(255,255,255,.1)}
.card{background:rgba(255,255,255,.05);border-radius:16px;padding:20px;margin-bottom:15px;
border:1px solid rgba(255,255,255,.1)}
.card h3{color:#00d4ff;margin-bottom:14px}
.search{display:flex;gap:10px;margin-bottom:20px}
input{flex:1;padding:14px;border-radius:12px;border:2px solid #444;
background:rgba(255,255,255,.05);color:#fff;font-size:1rem;text-transform:uppercase;outline:none}
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
.login-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.msg{font-size:.82rem;color:#aaa;margin-top:8px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
.kv{background:rgba(0,0,0,.3);padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.08)}
.kv .k{font-size:.7rem;color:#888;text-transform:uppercase}
.kv .v{font-size:.9rem;color:#fff;font-weight:600;margin-top:4px;word-break:break-all}
code{background:rgba(0,212,255,.12);padding:2px 6px;border-radius:4px;color:#7fff7f;font-size:.85rem}
.steps{background:rgba(0,0,0,.3);padding:12px;border-radius:10px;font-size:.8rem;color:#b8ffb8}
.steps li{margin:4px 0;margin-left:20px}
</style></head><body>
<div class="c">
<h1>🚗 nxcar Auto RC</h1>
<p class="sub">Auto Login • Auto cf_token • Auto Checksum</p>
<div class="status" id="status">Checking session...</div>

<div class="card">
<h3>🔐 Login</h3>
<div class="login-row">
<input id="phone" value="9612057455" style="max-width:220px">
<button onclick="sendOtp()">📩 Send OTP</button>
<input id="otp" placeholder="OTP" style="max-width:150px">
<button onclick="verifyOtp()">✅ Verify</button>
</div>
<div class="login-row">
<button style="background:linear-gradient(135deg,#ff5252,#b71c1c)" onclick="resetSession()">🗑️ Reset</button>
</div>
<div class="msg" id="loginMsg"></div>
</div>

<div class="card">
<h3>🔑 Manual cf_token (agar auto fail ho)</h3>
<p style="font-size:.8rem;color:#aaa;margin-bottom:8px">
Browser → F12 → Network → nxcar.in/rc-check search karo → <code>rc-query</code> request → Payload me <code>cf_token</code> copy karo
</p>
<input id="manualCf" placeholder="Paste cf_token here" style="width:100%;margin-bottom:8px">
<button onclick="setManualCf()">💾 Save cf_token</button>
</div>

<div class="search">
<input id="vnum" value="MH02FZ0555" onkeypress="if(event.key==='Enter')go()">
<button id="btn" onclick="go()">🔍 Search</button>
</div>

<div class="loader" id="loader"><div class="spin"></div>Fetching... (may take 15s for Selenium)</div>
<div id="result"></div>
</div>

<script>
async function checkSession(){
  try{
    const r = await fetch('/session');const d = await r.json();
    const el = document.getElementById('status');
    if(d.valid){
      el.innerHTML = `🟢 Session OK • User ${d.user_id} • cf_token: ${d.cf_token ? 'YES' : 'NO'} • Expires in ${d.expires_in}s`;
      el.style.background = 'rgba(0,200,83,.15)';
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
  if(!o) return alert('Enter OTP');
  document.getElementById('loginMsg').innerText = 'Verifying...';
  const r = await fetch('/verify-otp?phone=' + encodeURIComponent(p) + '&otp=' + encodeURIComponent(o));
  const d = await r.json();
  document.getElementById('loginMsg').innerText = (d.success ? '✅ ' : '❌ ') + JSON.stringify(d);
  checkSession();
}
async function resetSession(){
  if(!confirm('Reset session?')) return;
  await fetch('/reset-session');
  checkSession();
  document.getElementById('loginMsg').innerText = 'Reset done';
}
async function setManualCf(){
  const t = document.getElementById('manualCf').value.trim();
  if(!t) return alert('Paste cf_token');
  const r = await fetch('/manual-cf-token?token=' + encodeURIComponent(t));
  const d = await r.json();
  document.getElementById('loginMsg').innerText = 'cf_token: ' + JSON.stringify(d);
  checkSession();
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
    const okBadge = d.success ? '<span class="badge ok">SUCCESS</span>' : '<span class="badge err">FAILED</span>';
    h += `<div class="card"><h3>📋 Summary ${okBadge}</h3>
      <div class="grid">
        <div class="kv"><div class="k">Vehicle</div><div class="v">${d.vehicle_number||'-'}</div></div>
        <div class="kv"><div class="k">Checksum</div><div class="v"><code>${d.checksum||'-'}</code></div></div>
        <div class="kv"><div class="k">Source</div><div class="v">${d.checksum_source||'-'}</div></div>
        <div class="kv"><div class="k">HTTP</div><div class="v">${d.http_status||'-'}</div></div>
      </div>
      ${d.steps ? `<div class="steps"><b>Steps:</b><ul>${d.steps.map(s=>`<li>${s}</li>`).join('')}</ul></div>` : ''}
    </div>`;
    if(d.vehicle_details_response){
      h += `<div class="card"><h3>🚙 Vehicle Details</h3><pre>${JSON.stringify(d.vehicle_details_response,null,2)}</pre></div>`;
    }
    if(d.rc_query_response){
      h += `<div class="card"><h3>📡 rc-query Response</h3><pre>${JSON.stringify(d.rc_query_response,null,2)}</pre></div>`;
    }
    if(d.error){
      h += `<div class="card"><h3>⚠️ Error</h3><pre>${JSON.stringify(d.error,null,2)}</pre></div>`;
    }
    document.getElementById('result').innerHTML = h;
  }catch(e){
    document.getElementById('result').innerHTML = `<div class="card"><pre>${e.message}</pre></div>`;
  }finally{
    document.getElementById('btn').disabled = false;
    document.getElementById('loader').classList.remove('active');
    checkSession();
  }
}
setInterval(checkSession, 5000);checkSession();
</script></body></html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("="*60, flush=True)
    print("🚗 nxcar Auto RC — Selenium + rc-query edition", flush=True)
    print(f"🌐 Port {port}", flush=True)
    print("="*60, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
