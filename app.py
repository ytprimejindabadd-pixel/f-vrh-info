#!/usr/bin/env python3
"""
🚀 NXCar FULL AUTO — Render.com
OTP login + auto checksum + vehicle details
"""

import os
import json
import time
import base64
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
import requests

app = Flask(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/nxcar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = DATA_DIR / "session.json"
CACHE_FILE = DATA_DIR / "cache.json"
CACHE_TTL = 3600

NXCAR_BASE = "https://www.nxcar.in"
NXCAR_API = "https://api.nxcar.in/vehicle_details"

SEND_OTP_URL = f"{NXCAR_BASE}/api/auth/send-otp"
VERIFY_OTP_URL = f"{NXCAR_BASE}/api/auth/verify-otp"
AUTH_USER_URL = f"{NXCAR_BASE}/api/auth/user"
RC_QUERY_URL = f"{NXCAR_BASE}/api/nxcar/rc-query"


# ================== STORAGE ==================
def load_json(p, d=None):
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return d if d is not None else {}


def save_json(p, d):
    p.write_text(json.dumps(d, indent=2))


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


def is_token_valid(token):
    if not token:
        return False
    d = decode_jwt(token)
    return (int(time.time()) - d.get("API_TIME", 0)) < (25 * 24 * 3600)


def cookies_to_header(c):
    return "; ".join(f"{k}={v}" for k, v in c.items())


def get_headers(referer=None):
    h = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "accept-language": "en-US,en;q=0.6",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
    }
    h["referer"] = referer or f"{NXCAR_BASE}/profile-edit"
    return h


def safe_json(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}


# ================== OTP FLOW ==================
def send_otp(phone):
    """NXCar ko OTP bhejo"""
    try:
        r = requests.post(
            SEND_OTP_URL,
            json={"phone": phone},
            headers=get_headers(f"{NXCAR_BASE}/profile-edit"),
            timeout=15,
        )
        return r.status_code, safe_json(r)
    except Exception as e:
        return 500, {"error": str(e)}


def verify_otp(phone, otp):
    """OTP verify → token + cookies"""
    try:
        s = requests.Session()
        r = s.post(
            VERIFY_OTP_URL,
            json={"phone": phone, "otp": otp},
            headers=get_headers(f"{NXCAR_BASE}/profile-edit"),
            timeout=15,
        )
        data = safe_json(r)
        cookies_dict = {c.name: c.value for c in s.cookies}

        token = (data.get("token")
                 or data.get("auth_token")
                 or data.get("data", {}).get("token")
                 or cookies_dict.get("auth_token"))

        return r.status_code, data, token, cookies_dict
    except Exception as e:
        return 500, {"error": str(e)}, None, {}


# ================== CHECKSUM (AUTO) ==================
def get_checksum_auto(cookies_dict, vehicle_number, cf_token=""):
    """
    Checksum automatic nikaalo:
      1. rc-query call karo
      2. Response se checksum dhundho
      3. Nahi mile to empty return
    """
    headers = get_headers(f"{NXCAR_BASE}/rc-check")
    headers["Cookie"] = cookies_to_header(cookies_dict)

    # phone number from decoded token
    token = cookies_dict.get("auth_token", "")
    decoded = decode_jwt(token)
    phone = str(decoded.get("username", ""))

    payload = {
        "phone_number": phone,
        "vehicle_number": vehicle_number.upper(),
        "cf_token": cf_token,
    }

    try:
        r = requests.post(RC_QUERY_URL, json=payload, headers=headers, timeout=15)
        data = safe_json(r)

        # Response headers me bhi checksum ho sakta hai
        checksum = (
            data.get("checksum")
            or data.get("data", {}).get("checksum")
            or data.get("result", {}).get("checksum")
            or r.headers.get("X-Checksum")
            or r.headers.get("x-checksum")
        )

        return checksum, data
    except Exception as e:
        return None, {"error": str(e)}


# ================== VEHICLE DETAILS ==================
def fetch_details_auto(vehicle_number, cookies_dict, cf_token=""):
    """
    Full auto:
      1. checksum lo (rc-query se)
      2. vehicle_details call
      3. checksum na mile to bina checksum try karo
    """
    token = cookies_dict.get("auth_token", "")

    # Step 1: checksum
    checksum, query_resp = get_checksum_auto(cookies_dict, vehicle_number, cf_token)

    # Step 2: vehicle_details
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "authorization": token,
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/",
        "accept-language": "en-US,en;q=0.6",
    }

    # Checksum ke saath
    if checksum:
        params = {
            "vehicle_number": vehicle_number.upper(),
            "backend": "yes",
            "checksum": checksum,
        }
        try:
            r = requests.get(NXCAR_API, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                return r.status_code, r.json(), "auto_checksum", checksum
        except Exception:
            pass

    # Bina checksum (server khud dhundega)
    params_no_cs = {
        "vehicle_number": vehicle_number.upper(),
        "backend": "yes",
    }
    try:
        r = requests.get(NXCAR_API, params=params_no_cs, headers=headers, timeout=20)
        return r.status_code, safe_json(r), "no_checksum", checksum
    except Exception as e:
        return 500, {"error": str(e)}, "error", checksum


# ================== MAIN FETCH ==================
def get_vehicle(vehicle_number):
    vehicle_number = vehicle_number.upper()
    cache = load_json(CACHE_FILE)

    if vehicle_number in cache:
        c = cache[vehicle_number]
        if time.time() - c.get("at", 0) < CACHE_TTL:
            return 200, c["data"], "cache", None

    session = load_session()
    cookies_dict = session.get("cookies_dict", {})
    token = cookies_dict.get("auth_token")
    cf_token = session.get("cf_token", "")

    if not token:
        return 401, {"error": "no_token", "action": "POST /send-otp then /verify-otp"}, "no_token", None

    if not is_token_valid(token):
        return 401, {"error": "token_expired", "action": "Re-login via OTP"}, "expired", None

    code, data, source, used_checksum = fetch_details_auto(vehicle_number, cookies_dict, cf_token)

    if code == 200:
        cache[vehicle_number] = {"at": int(time.time()), "data": data}
        save_json(CACHE_FILE, cache)
        if used_checksum:
            session["checksum"] = used_checksum
            save_session(session)

    return code, data, source, used_checksum


# ================== ROUTES ==================
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
    label { font-size: 12px; color: #888; display: block; margin-top: 6px; }
    input, button { padding: 10px; font-size: 15px; border-radius: 6px;
        border: 1px solid #333; background: #222; color: #fff;
        width: 100%; margin-top: 4px; }
    button { background: #00ff88; color: #000; font-weight: bold;
             cursor: pointer; margin-top: 8px; }
    button.alt { background: #333; color: #fff; }
    pre { background: #000; padding: 12px; overflow-x: auto;
          border-radius: 6px; font-size: 11px; max-height: 500px;
          line-height: 1.4; }
    .steps { font-size: 13px; color: #aaa; }
    .steps li { margin: 4px 0; }
  </style>
</head>
<body>
  <h1>🚗 NXCar FULL AUTO</h1>

  <div class="card">
    <label>Step 1: Phone Number</label>
    <input id="phone" value="9612057455">
    <button onclick="sendOtp()">Send OTP</button>
  </div>

  <div class="card">
    <label>Step 2: OTP (phone pe aaya)</label>
    <input id="otp" placeholder="123456">
    <button onclick="verifyOtp()">Verify & Login</button>
  </div>

  <div class="card">
    <label>Step 3: Vehicle Number</label>
    <input id="vnum" value="MH02FZ0555">
    <button onclick="fetchData()">Get Details</button>
  </div>

  <div class="card">
    <label>Optional: CF Token (browser se)</label>
    <input id="cf" placeholder="1.p_EZ_YuK3_...">
    <button class="alt" onclick="importCF()">Save CF</button>
  </div>

  <div class="card">
    <button class="alt" onclick="showSession()">Session Status</button>
    <button class="alt" onclick="importCookies()">Import Cookies</button>
  </div>

  <pre id="result">Ready</pre>

<script>
function show(o) {
  document.getElementById('result').textContent =
    typeof o === 'string' ? o : JSON.stringify(o, null, 2);
}

async function sendOtp() {
  const phone = document.getElementById('phone').value.trim();
  show('⏳ Sending OTP to ' + phone + '...');
  const r = await fetch('/send-otp', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({phone})
  });
  show(await r.json());
}

async function verifyOtp() {
  const otp = document.getElementById('otp').value.trim();
  show('⏳ Verifying OTP...');
  const r = await fetch('/verify-otp', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({otp})
  });
  show(await r.json());
}

async function fetchData() {
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  show('⏳ Fetching ' + v + ' (auto checksum)...');
  const r = await fetch('/vehicle/' + v);
  show(await r.json());
}

async function importCF() {
  const cf = document.getElementById('cf').value.trim();
  const r = await fetch('/import-cf', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({cf_token: cf})
  });
  show(await r.json());
}

async function showSession() {
  const r = await fetch('/session');
  show(await r.json());
}

async function importCookies() {
  const cookieStr = prompt("Paste JSON array of cookies:");
  if (!cookieStr) return;
  try {
    const j = JSON.parse(cookieStr);
    const r = await fetch('/import-cookies', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(j)
    });
    show(await r.json());
  } catch(e) { show('Err: ' + e.message); }
}

showSession();
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/health")
def health():
    s = load_session()
    return jsonify({
        "status": "ok",
        "has_token": bool(s.get("cookies_dict", {}).get("auth_token")),
        "has_cf": bool(s.get("cf_token")),
        "has_checksum": bool(s.get("checksum")),
    })


@app.route("/send-otp", methods=["POST"])
def route_send_otp():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    code, resp = send_otp(phone)

    session = load_session()
    session["phone"] = phone
    save_session(session)

    return jsonify({
        "status": "ok" if code == 200 else "error",
        "code": code,
        "response": resp,
    }), code


@app.route("/verify-otp", methods=["POST"])
def route_verify_otp():
    data = request.get_json(silent=True) or {}
    otp = data.get("otp", "").strip()

    session = load_session()
    phone = data.get("phone") or session.get("phone", "")

    if not otp or not phone:
        return jsonify({"error": "otp and phone required"}), 400

    code, resp, token, cookies = verify_otp(phone, otp)

    if token:
        if not cookies.get("auth_token"):
            cookies["auth_token"] = token
        session["cookies_dict"] = cookies
        session["phone"] = phone
        session["updated_at"] = int(time.time())
        save_session(session)

        return jsonify({
            "status": "ok",
            "message": "Login successful",
            "token_valid": is_token_valid(token),
            "cookies_count": len(cookies),
            "phone": phone,
        })

    return jsonify({
        "status": "error",
        "response": resp,
        "code": code,
    }), code


@app.route("/vehicle/<vehicle_number>")
def route_vehicle(vehicle_number):
    code, data, source, checksum = get_vehicle(vehicle_number)
    resp = jsonify(data)
    resp.headers["X-Source"] = source
    if checksum:
        resp.headers["X-Checksum"] = checksum
    return resp, code


@app.route("/rc=<vehicle_number>")
def route_rc_shortcut(vehicle_number):
    """Shortcut: /rc=MH02FZ0555"""
    code, data, source, checksum = get_vehicle(vehicle_number)
    resp = jsonify(data)
    resp.headers["X-Source"] = source
    if checksum:
        resp.headers["X-Checksum"] = checksum
    return resp, code


@app.route("/import-cf", methods=["POST"])
def route_import_cf():
    data = request.get_json(silent=True) or {}
    cf = data.get("cf_token", "")
    if not cf:
        return jsonify({"error": "cf_token required"}), 400
    session = load_session()
    session["cf_token"] = cf
    save_session(session)
    return jsonify({"status": "ok", "cf_length": len(cf)})


@app.route("/import-cookies", methods=["POST"])
def route_import_cookies():
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


@app.route("/session")
def route_session():
    s = load_session()
    token = s.get("cookies_dict", {}).get("auth_token", "")
    return jsonify({
        "has_token": bool(token),
        "valid_local": is_token_valid(token) if token else False,
        "decoded": decode_jwt(token) if token else {},
        "cookies_count": len(s.get("cookies_dict", {})),
        "phone": s.get("phone", ""),
        "has_cf": bool(s.get("cf_token")),
        "checksum": s.get("checksum", ""),
    })


@app.route("/clear-cache")
def route_clear_cache():
    save_json(CACHE_FILE, {})
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
