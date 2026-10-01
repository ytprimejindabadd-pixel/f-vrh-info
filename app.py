#!/usr/bin/env python3
"""
🚀 NXCar ULTRA ADVANCED — Render.com
Multi-mode: cookies / OTP / auto-refresh
"""

import os
import json
import time
import base64
import random
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
import requests

app = Flask(__name__)

# ================== PATHS ==================
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/nxcar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = DATA_DIR / "session.json"
CACHE_FILE = DATA_DIR / "cache.json"
CACHE_TTL = 300

# ================== CONFIG ==================
NXCAR_BASE = "https://www.nxcar.in"
NXCAR_API = "https://api.nxcar.in/vehicle_details"

SEND_OTP_URL = f"{NXCAR_BASE}/api/auth/send-otp"
VERIFY_OTP_URL = f"{NXCAR_BASE}/api/auth/verify-otp"
AUTH_USER_URL = f"{NXCAR_BASE}/api/auth/user"
RC_QUERY_URL = f"{NXCAR_BASE}/api/nxcar/rc-query"

# Multiple numbers try karne ke liye
PHONE_NUMBERS = [
    "9612057455",   # registered
    "8638152584",   # tumhara
    "7874800000",   # fallback
]

API_KEY = os.environ.get("API_KEY", "changeme")


# ================== STORAGE ==================
def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def load_session():
    return load_json(SESSION_FILE)


def save_session(d):
    save_json(SESSION_FILE, d)


# ================== HELPERS ==================
def decode_jwt(token):
    try:
        p = token.split('.')[1]
        p += '=' * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def token_age_days(token):
    d = decode_jwt(token)
    return (int(time.time()) - d.get("API_TIME", 0)) / 86400


def is_token_valid(token):
    if not token:
        return False
    return token_age_days(token) < 25


def cookies_to_header(c):
    return "; ".join(f"{k}={v}" for k, v in c.items())


def random_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/rc-check",
        "accept-language": "en-US,en;q=0.6",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
    }


def safe_json(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}


# ================== TOKEN CHECK ==================
def check_token_alive(token, cookies_dict):
    """Server pe token live hai?"""
    headers = random_headers()
    headers["Cookie"] = cookies_to_header(cookies_dict)
    try:
        r = requests.get(AUTH_USER_URL, headers=headers, timeout=10)
        return r.status_code == 200, safe_json(r)
    except Exception as e:
        return False, {"error": str(e)}


# ================== OTP FLOW (Multi Number) ==================
def try_send_otp():
    """Multiple numbers try karo OTP ke liye"""
    results = []
    for phone in PHONE_NUMBERS:
        headers = random_headers()
        headers["referer"] = f"{NXCAR_BASE}/profile-edit"
        payload = {"phone": phone}

        try:
            r = requests.post(SEND_OTP_URL, json=payload,
                              headers=headers, timeout=15)
            data = safe_json(r)
            results.append({
                "phone": phone,
                "code": r.status_code,
                "response": data,
                "ok": r.status_code == 200,
            })
            # First success → return
            if r.status_code == 200:
                return True, results
        except Exception as e:
            results.append({"phone": phone, "error": str(e)})

    return False, results


def verify_otp(otp, phone):
    """OTP verify → token + cookies"""
    headers = random_headers()
    headers["referer"] = f"{NXCAR_BASE}/profile-edit"
    payload = {"phone": phone, "otp": otp}

    try:
        s = requests.Session()
        r = s.post(VERIFY_OTP_URL, json=payload, headers=headers, timeout=15)
        data = safe_json(r)

        cookies_dict = {c.name: c.value for c in s.cookies}

        token = (data.get("token")
                 or data.get("auth_token")
                 or data.get("data", {}).get("token")
                 or cookies_dict.get("auth_token"))

        return r.status_code, data, token, cookies_dict
    except Exception as e:
        return 500, {"error": str(e)}, None, {}


# ================== RC QUERY (CHECKSUM) ==================
def get_checksum(cookies_dict, vehicle_number, cf_token=""):
    headers = random_headers()
    headers["Cookie"] = cookies_to_header(cookies_dict)
    payload = {
        "phone_number": PHONE_NUMBERS[0],
        "vehicle_number": vehicle_number.upper(),
        "cf_token": cf_token,
    }
    try:
        r = requests.post(RC_QUERY_URL, json=payload,
                          headers=headers, timeout=15)
        data = safe_json(r)
        checksum = (data.get("checksum")
                    or data.get("data", {}).get("checksum")
                    or data.get("result", {}).get("checksum"))
        return checksum, data
    except Exception as e:
        return None, {"error": str(e)}


# ================== VEHICLE DETAILS ==================
def fetch_vehicle_details(vehicle_number, checksum, token):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "authorization": token,
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/",
    }
    params = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    try:
        r = requests.get(NXCAR_API, params=params,
                         headers=headers, timeout=20)
        return r.status_code, safe_json(r)
    except Exception as e:
        return 500, {"error": str(e)}


# ================== MAIN FLOW ==================
def fetch_vehicle(vehicle_number):
    vehicle_number = vehicle_number.upper()
    cache = load_json(CACHE_FILE)

    if vehicle_number in cache:
        c = cache[vehicle_number]
        if time.time() - c.get("at", 0) < CACHE_TTL:
            return 200, c["data"], "cache"

    session = load_session()
    cookies_dict = session.get("cookies_dict", {})
    token = cookies_dict.get("auth_token")

    if not token:
        return 401, {
            "error": "no_token",
            "action": "POST /import-cookies with your auth cookies",
        }, "no_token"

    # Token validity check — server pe
    alive, user_info = check_token_alive(token, cookies_dict)
    if not alive:
        return 401, {
            "error": "token_dead",
            "user_info": user_info,
            "action": "Token expire. New cookies import karo.",
        }, "token_dead"

    # Checksum
    cf_token = session.get("cf_token", "")
    checksum, query_resp = get_checksum(cookies_dict, vehicle_number, cf_token)

    if not checksum:
        checksum = session.get("checksum", "")

    if not checksum:
        return 400, {
            "error": "no_checksum",
            "rc_query": query_resp,
            "hint": "cf_token fresh chahiye browser se",
        }, "no_checksum"

    # Final
    code, data = fetch_vehicle_details(vehicle_number, checksum, token)

    if code == 200:
        cache[vehicle_number] = {"at": int(time.time()), "data": data}
        save_json(CACHE_FILE, cache)
        session["checksum"] = checksum
        save_session(session)
        return 200, data, "api"

    return code, data, "error"


# ================== ROUTES ==================
@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/health")
def health():
    s = load_session()
    token = s.get("cookies_dict", {}).get("auth_token", "")
    return jsonify({
        "status": "ok",
        "has_token": bool(token),
        "token_valid": is_token_valid(token) if token else False,
        "token_age_days": round(token_age_days(token), 2) if token else 0,
        "time": int(time.time()),
    })


@app.route("/send-otp", methods=["POST", "GET"])
def route_send_otp():
    ok, results = try_send_otp()
    return jsonify({
        "status": "ok" if ok else "all_failed",
        "tried_numbers": [r.get("phone") for r in results],
        "results": results,
        "hint": "Agar sab fail — number registered hai, cookies import karo",
    })


@app.route("/verify-otp", methods=["POST"])
def route_verify_otp():
    data = request.get_json(silent=True) or {}
    otp = data.get("otp")
    phone = data.get("phone", PHONE_NUMBERS[0])

    if not otp:
        return jsonify({"error": "otp required"}), 400

    code, resp, token, cookies = verify_otp(otp, phone)

    if token:
        session = load_session()
        if not cookies.get("auth_token"):
            cookies["auth_token"] = token
        session["cookies_dict"] = cookies
        session["phone"] = phone
        session["updated_at"] = int(time.time())
        save_session(session)

        return jsonify({
            "status": "ok",
            "token_valid": is_token_valid(token),
            "token_preview": token[:40] + "...",
            "cookies_count": len(cookies),
            "phone": phone,
        })

    return jsonify({
        "status": "error",
        "response": resp,
        "code": code,
    }), code


@app.route("/submit-otp", methods=["POST"])
def route_submit_otp():
    """Termux call karega OTP aane pe"""
    data = request.get_json(silent=True) or {}
    if data.get("api_key") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    otp = data.get("otp")
    if not otp:
        return jsonify({"error": "otp required"}), 400

    # Try each phone
    for phone in PHONE_NUMBERS:
        code, resp, token, cookies = verify_otp(otp, phone)
        if token:
            session = load_session()
            if not cookies.get("auth_token"):
                cookies["auth_token"] = token
            session["cookies_dict"] = cookies
            session["phone"] = phone
            session["updated_at"] = int(time.time())
            save_session(session)
            return jsonify({
                "status": "ok",
                "phone": phone,
                "token_valid": is_token_valid(token),
            })

    return jsonify({"status": "error", "message": "OTP verification failed"}), 400


@app.route("/import-cookies", methods=["POST"])
def route_import_cookies():
    """Cookies import — JSON array, string, ya dict"""
    data = request.get_json(silent=True) or {}

    cookies_dict = {}

    if isinstance(data, list):
        cookies_dict = {c["name"]: c["value"] for c in data if "name" in c}
    elif isinstance(data.get("cookies"), list):
        cookies_dict = {c["name"]: c["value"] for c in data["cookies"]}
    elif isinstance(data.get("cookies"), dict):
        cookies_dict = data["cookies"]
    elif data.get("cookie"):
        for item in data["cookie"].split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies_dict[k] = v
    else:
        return jsonify({"error": "invalid format"}), 400

    if not cookies_dict.get("auth_token"):
        return jsonify({"error": "auth_token missing"}), 400

    session = load_session()
    session["cookies_dict"] = cookies_dict
    session["updated_at"] = int(time.time())
    save_session(session)

    # Verify with /api/auth/user
    alive, user_info = check_token_alive(
        cookies_dict["auth_token"], cookies_dict)

    return jsonify({
        "status": "ok",
        "cookies_count": len(cookies_dict),
        "cookie_names": list(cookies_dict.keys()),
        "token_valid": is_token_valid(cookies_dict["auth_token"]),
        "server_alive": alive,
        "user": user_info.get("user", {}) if alive else None,
    })


@app.route("/vehicle/<vehicle_number>")
def route_vehicle(vehicle_number):
    code, data, source = fetch_vehicle(vehicle_number)
    resp = jsonify(data)
    resp.headers["X-Source"] = source
    return resp, code


@app.route("/session")
def route_session():
    s = load_session()
    token = s.get("cookies_dict", {}).get("auth_token", "")
    return jsonify({
        "has_token": bool(token),
        "valid_local": is_token_valid(token) if token else False,
        "token_age_days": round(token_age_days(token), 2) if token else 0,
        "decoded": decode_jwt(token) if token else {},
        "cookies_count": len(s.get("cookies_dict", {})),
        "checksum": s.get("checksum", ""),
        "phone": s.get("phone", ""),
        "updated_at": s.get("updated_at", 0),
    })


@app.route("/clear-cache")
def route_clear_cache():
    save_json(CACHE_FILE, {})
    return jsonify({"status": "ok"})


HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>NXCar ULTRA</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; padding: 16px;
           background: #0a0a0a; color: #fff; margin: 0; }
    h1 { color: #00ff88; font-size: 20px; }
    .card { background: #1a1a1a; padding: 14px; border-radius: 10px;
            margin: 10px 0; }
    label { font-size: 13px; color: #888; }
    input, button, textarea { padding: 10px; font-size: 15px;
        border-radius: 6px; border: 1px solid #333;
        background: #222; color: #fff; width: 100%; margin-top: 6px; }
    button { background: #00ff88; color: #000; font-weight: bold;
             cursor: pointer; }
    button.alt { background: #333; color: #fff; }
    pre { background: #000; padding: 12px; overflow-x: auto;
          border-radius: 6px; font-size: 11px; max-height: 400px;
          line-height: 1.4; }
    .status { display: inline-block; padding: 3px 8px; border-radius: 4px;
              font-size: 11px; }
    .ok { background: #00ff88; color: #000; }
    .bad { background: #ff4444; }
  </style>
</head>
<body>
  <h1>🚗 NXCar ULTRA <span id="badge" class="status">...</span></h1>

  <div class="card">
    <label>Vehicle Number</label>
    <input id="vnum" value="MH02FZ0555">
    <button onclick="fetchData()">Get Details</button>
    <button class="alt" onclick="showSession()">Session Status</button>
  </div>

  <div class="card">
    <label>Import Cookies (JSON array from browser)</label>
    <textarea id="cookieData" rows="4" placeholder='[{"name":"auth_token","value":"..."}]'></textarea>
    <button onclick="importCookies()">Import</button>
  </div>

  <div class="card">
    <label>OTP Flow</label>
    <button class="alt" onclick="sendOtp()">Send OTP</button>
    <input id="otp" placeholder="OTP">
    <button onclick="verifyOtp()">Verify</button>
  </div>

  <pre id="result">Ready</pre>

<script>
function show(o) {
  document.getElementById('result').textContent =
    typeof o === 'string' ? o : JSON.stringify(o, null, 2);
}

async function fetchData() {
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  show('⏳ Fetching ' + v);
  const r = await fetch('/vehicle/' + v);
  show(await r.json());
}

async function showSession() {
  const r = await fetch('/session');
  const d = await r.json();
  show(d);
  const b = document.getElementById('badge');
  b.textContent = d.valid_local ? 'TOKEN OK' : 'NO TOKEN';
  b.className = 'status ' + (d.valid_local ? 'ok' : 'bad');
}

async function importCookies() {
  try {
    const j = JSON.parse(document.getElementById('cookieData').value);
    const r = await fetch('/import-cookies', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(j)
    });
    show(await r.json());
  } catch(e) { show('Error: ' + e.message); }
}

async function sendOtp() {
  show('⏳ Sending...');
  const r = await fetch('/send-otp', {method:'POST'});
  show(await r.json());
}

async function verifyOtp() {
  const otp = document.getElementById('otp').value;
  show('⏳ Verifying...');
  const r = await fetch('/verify-otp', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({otp})
  });
  show(await r.json());
}

showSession();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 NXCar ULTRA — port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
