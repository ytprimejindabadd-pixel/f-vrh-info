#!/usr/bin/env python3
"""
🚀 NXCar ULTRA AUTO — Render.com
Full auto: OTP → token → checksum → vehicle details
"""

import os
import json
import time
import base64
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
import requests

app = Flask(__name__)

# ================== PATHS ==================
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/nxcar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = DATA_DIR / "session.json"
CACHE_FILE = DATA_DIR / "cache.json"
OTP_FILE = DATA_DIR / "otp.json"
CACHE_TTL = 600

# ================== CONFIG ==================
NXCAR_BASE = "https://www.nxcar.in"
NXCAR_API = "https://api.nxcar.in/vehicle_details"

SEND_OTP_URL = f"{NXCAR_BASE}/api/auth/send-otp"
VERIFY_OTP_URL = f"{NXCAR_BASE}/api/auth/verify-otp"

PHONE = os.environ.get("NXCAR_PHONE", "9612057455")
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


# ================== TOKEN HELPERS ==================
def decode_jwt(token):
    try:
        p = token.split('.')[1]
        p += '=' * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def is_token_valid(token):
    if not token:
        return False
    d = decode_jwt(token)
    age = int(time.time()) - d.get("API_TIME", 0)
    return age < (25 * 24 * 3600)


def cookies_to_header(cookies_dict):
    return "; ".join(f"{k}={v}" for k, v in cookies_dict.items())


# ================== STEP 1: SEND OTP ==================
def send_otp(phone=None):
    phone = phone or PHONE
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/profile-edit",
        "accept-language": "en-US,en;q=0.6",
    }
    try:
        r = requests.post(SEND_OTP_URL, json={"phone": phone},
                          headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:300]}
    except Exception as e:
        return 500, {"error": str(e)}


# ================== STEP 2: VERIFY OTP ==================
def verify_otp(otp, phone=None):
    """OTP verify → cookies + token"""
    phone = phone or PHONE
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/profile-edit",
        "accept-language": "en-US,en;q=0.6",
    }
    payload = {"phone": phone, "otp": otp}

    try:
        s = requests.Session()
        r = s.post(VERIFY_OTP_URL, json=payload, headers=headers, timeout=15)

        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:300]}

        # Cookies se token
        cookies_dict = {}
        for c in s.cookies:
            cookies_dict[c.name] = c.value

        # Response me bhi ho sakta hai
        token = (data.get("token")
                 or data.get("auth_token")
                 or data.get("data", {}).get("token")
                 or cookies_dict.get("auth_token"))

        return r.status_code, data, token, cookies_dict
    except Exception as e:
        return 500, {"error": str(e)}, None, {}


# ================== STEP 3: RC QUERY (CHECKSUM) ==================
def get_checksum(cookies_dict, vehicle_number, cf_token=""):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/rc-check",
        "Cookie": cookies_to_header(cookies_dict),
    }
    payload = {
        "phone_number": PHONE,
        "vehicle_number": vehicle_number.upper(),
        "cf_token": cf_token,
    }
    try:
        r = requests.post(f"{NXCAR_BASE}/api/nxcar/rc-query",
                          json=payload, headers=headers, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:300]}

        checksum = (data.get("checksum")
                    or data.get("data", {}).get("checksum")
                    or data.get("result", {}).get("checksum"))
        return checksum, data
    except Exception as e:
        return None, {"error": str(e)}


# ================== STEP 4: VEHICLE DETAILS ==================
def fetch_vehicle_details(vehicle_number, checksum, token):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "authorization": token,
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/",
        "accept-language": "en-US,en;q=0.6",
    }
    params = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
        "checksum": checksum,
    }
    try:
        r = requests.get(NXCAR_API, params=params, headers=headers, timeout=20)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:500]}
    except Exception as e:
        return 500, {"error": str(e)}


# ================== MAIN FETCH ==================
def fetch_vehicle(vehicle_number):
    vehicle_number = vehicle_number.upper()
    cache = load_json(CACHE_FILE)

    # Cache
    if vehicle_number in cache:
        c = cache[vehicle_number]
        if time.time() - c.get("at", 0) < CACHE_TTL:
            return 200, c["data"], "cache"

    session = load_session()
    cookies_dict = session.get("cookies_dict", {})
    token = cookies_dict.get("auth_token")

    if not token or not is_token_valid(token):
        return 401, {
            "error": "token_expired",
            "action": "POST /send-otp, phir /verify-otp",
            "hint": "Auto-refresh ke liye Termux script chalao",
        }, "expired"

    # Checksum
    cf_token = session.get("cf_token", "")
    checksum, query_resp = get_checksum(cookies_dict, vehicle_number, cf_token)

    if not checksum:
        checksum = session.get("checksum", "")

    if not checksum:
        return 400, {
            "error": "no_checksum",
            "rc_query_response": query_resp,
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
HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>NXCar ULTRA</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body { font-family: -apple-system, sans-serif; padding: 16px;
           background: #0a0a0a; color: #fff; margin: 0; }
    h1 { color: #00ff88; font-size: 22px; }
    .card { background: #1a1a1a; padding: 16px; border-radius: 10px;
            margin: 12px 0; }
    input, button { padding: 12px; font-size: 16px; border-radius: 6px;
                    border: 1px solid #333; background: #222; color: #fff;
                    width: 100%; }
    button { background: #00ff88; color: #000; font-weight: bold;
             cursor: pointer; margin-top: 8px; }
    pre { background: #000; padding: 12px; overflow-x: auto;
          border-radius: 6px; font-size: 11px; }
    .ok { color: #00ff88; }
    .bad { color: #ff4444; }
  </style>
</head>
<body>
  <h1>🚗 NXCar ULTRA</h1>
  <div class="card">
    <label>Vehicle Number</label>
    <input id="vnum" value="MH02FZ0555">
    <button onclick="fetchData()">Get Details</button>
  </div>
  <div class="card">
    <button onclick="sendOtp()">📱 Send OTP</button>
    <input id="otp" placeholder="Enter OTP" style="margin-top:8px">
    <button onclick="verifyOtp()">✅ Verify OTP</button>
  </div>
  <pre id="result">Ready</pre>
<script>
async function fetchData() {
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  const r = document.getElementById('result');
  r.textContent = '⏳ ' + v;
  try {
    const resp = await fetch('/vehicle/' + v);
    const data = await resp.json();
    r.textContent = JSON.stringify(data, null, 2);
  } catch(e) { r.textContent = 'Error: ' + e.message; }
}
async function sendOtp() {
  const r = document.getElementById('result');
  r.textContent = '⏳ Sending OTP...';
  try {
    const resp = await fetch('/send-otp', {method: 'POST'});
    const data = await resp.json();
    r.textContent = JSON.stringify(data, null, 2);
  } catch(e) { r.textContent = 'Error: ' + e.message; }
}
async function verifyOtp() {
  const otp = document.getElementById('otp').value.trim();
  const r = document.getElementById('result');
  r.textContent = '⏳ Verifying...';
  try {
    const resp = await fetch('/verify-otp', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({otp})
    });
    const data = await resp.json();
    r.textContent = JSON.stringify(data, null, 2);
  } catch(e) { r.textContent = 'Error: ' + e.message; }
}
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": int(time.time())})


@app.route("/send-otp", methods=["POST", "GET"])
def route_send_otp():
    code, data = send_otp()
    return jsonify({
        "status": "ok" if code == 200 else "error",
        "code": code,
        "response": data,
    }), code


@app.route("/verify-otp", methods=["POST"])
def route_verify_otp():
    data = request.get_json(silent=True) or {}
    otp = data.get("otp")
    if not otp:
        return jsonify({"error": "otp required"}), 400

    code, resp, token, cookies = verify_otp(otp)

    if token:
        session = load_session()
        if not cookies.get("auth_token"):
            cookies["auth_token"] = token
        session["cookies_dict"] = cookies
        session["updated_at"] = int(time.time())
        save_session(session)

        return jsonify({
            "status": "ok",
            "token_valid": is_token_valid(token),
            "token_preview": token[:40] + "...",
            "cookies_count": len(cookies),
        })

    return jsonify({
        "status": "error",
        "response": resp,
        "code": code,
    }), code


@app.route("/submit-otp", methods=["POST"])
def route_submit_otp():
    """Termux ye call karega OTP aane pe"""
    data = request.get_json(silent=True) or {}
    if data.get("api_key") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    otp = data.get("otp")
    if not otp:
        return jsonify({"error": "otp required"}), 400

    save_json(OTP_FILE, {"otp": otp, "at": int(time.time())})

    code, resp, token, cookies = verify_otp(otp)

    if token:
        session = load_session()
        if not cookies.get("auth_token"):
            cookies["auth_token"] = token
        session["cookies_dict"] = cookies
        session["updated_at"] = int(time.time())
        save_session(session)
        return jsonify({"status": "ok", "message": "Auto login success"})

    return jsonify({"status": "error", "response": resp}), 400


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
        "valid": is_token_valid(token),
        "decoded": decode_jwt(token) if token else {},
        "cookies_count": len(s.get("cookies_dict", {})),
        "checksum": s.get("checksum", ""),
        "updated_at": s.get("updated_at", 0),
    })


@app.route("/import-cookies", methods=["POST"])
def route_import_cookies():
    data = request.get_json(silent=True) or {}

    if isinstance(data, list):
        cookies_dict = {c["name"]: c["value"] for c in data}
    elif data.get("cookie"):
        cookies_dict = {}
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

    return jsonify({
        "status": "ok",
        "cookies_count": len(cookies_dict),
        "token_valid": is_token_valid(cookies_dict["auth_token"]),
    })


@app.route("/clear-cache")
def route_clear_cache():
    save_json(CACHE_FILE, {})
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 NXCar ULTRA — port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
