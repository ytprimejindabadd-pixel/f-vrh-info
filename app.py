#!/usr/bin/env python3
"""
🚀 NXCar ULTRA PRO — Render.com
Full auto: OTP login + Playwright checksum + vehicle details
100% automatic after setup
"""

import os
import json
import time
import base64
import asyncio
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
import requests

app = Flask(__name__)

# ================== CONFIG ==================
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/nxcar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = DATA_DIR / "session.json"
CACHE_FILE = DATA_DIR / "cache.json"
BROWSER_DATA = DATA_DIR / "browser"
CACHE_TTL = 1800  # 30 min

NXCAR_BASE = "https://www.nxcar.in"
NXCAR_API = "https://api.nxcar.in/vehicle_details"

SEND_OTP_URL = f"{NXCAR_BASE}/api/auth/send-otp"
VERIFY_OTP_URL = f"{NXCAR_BASE}/api/auth/verify-otp"
AUTH_USER_URL = f"{NXCAR_BASE}/api/auth/user"
RC_QUERY_URL = f"{NXCAR_BASE}/api/nxcar/rc-query"

API_KEY = os.environ.get("API_KEY", "changeme-secret")


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


def base_headers(referer=None):
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
    try:
        r = requests.post(SEND_OTP_URL, json={"phone": phone},
                          headers=base_headers(), timeout=15)
        return r.status_code, safe_json(r)
    except Exception as e:
        return 500, {"error": str(e)}


def verify_otp(phone, otp):
    try:
        s = requests.Session()
        r = s.post(VERIFY_OTP_URL, json={"phone": phone, "otp": otp},
                   headers=base_headers(), timeout=15)
        data = safe_json(r)
        cookies_dict = {c.name: c.value for c in s.cookies}

        token = (data.get("token") or data.get("auth_token")
                 or data.get("data", {}).get("token")
                 or cookies_dict.get("auth_token"))

        return r.status_code, data, token, cookies_dict
    except Exception as e:
        return 500, {"error": str(e)}, None, {}


# ================== PLAYWRIGHT CHECKSUM ==================
async def playwright_checksum(vehicle_number, cookies_dict):
    """
    Playwright browser kholo, NXCar pe jao,
    vehicle search karo, checksum capture karo
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        return None, f"playwright_not_installed: {e}"

    BROWSER_DATA.mkdir(exist_ok=True)

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_DATA),
                headless=True,
                user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
                viewport={"width": 390, "height": 844},
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except Exception as e:
            return None, f"browser_launch: {e}"

        # Cookies inject
        nxcar_cookies = []
        for name, value in cookies_dict.items():
            nxcar_cookies.append({
                "name": name, "value": value,
                "domain": ".nxcar.in", "path": "/",
                "secure": True, "sameSite": "Lax",
            })
        try:
            await ctx.add_cookies(nxcar_cookies)
        except Exception as e:
            print(f"Cookie inject err: {e}")

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        captured = {"checksum": None, "result": None}

        async def on_request(req):
            url = req.url
            if "vehicle_details" in url and "checksum=" in url:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(url).query)
                c = q.get("checksum", [None])[0]
                if c and not captured["checksum"]:
                    captured["checksum"] = c

        async def on_response(resp):
            if "api.nxcar.in/vehicle_details" in resp.url:
                try:
                    captured["result"] = await resp.json()
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            # rc-check page kholo
            await page.goto(f"{NXCAR_BASE}/rc-check",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)

            # Vehicle number type karo
            try:
                inp = await page.query_selector(
                    'input[placeholder*="number" i], input[type="text"], input[inputmode="text"]'
                )
                if inp:
                    await inp.click()
                    await inp.fill(vehicle_number.upper())
                    await page.wait_for_timeout(500)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(8000)
            except Exception as e:
                print(f"Search err: {e}")

            # Agar checksum mila but result nahi, direct fetch karo
            if captured["checksum"] and not captured["result"]:
                try:
                    token = cookies_dict.get("auth_token", "")
                    result = await page.evaluate(f"""
                        async () => {{
                            const r = await fetch(
                                "https://api.nxcar.in/vehicle_details?vehicle_number={vehicle_number.upper()}&backend=yes&checksum={captured['checksum']}",
                                {{ headers: {{ "authorization": "{token}" }} }}
                            );
                            return await r.json();
                        }}
                    """)
                    captured["result"] = result
                except Exception as e:
                    print(f"Direct fetch err: {e}")

            await ctx.close()

            # Save checksum
            if captured["checksum"]:
                s = load_session()
                s["checksum"] = captured["checksum"]
                s["checksum_at"] = int(time.time())
                save_session(s)

            return {
                "checksum": captured["checksum"],
                "result": captured["result"],
            }, None

        except Exception as e:
            try:
                await ctx.close()
            except Exception:
                pass
            return None, str(e)


def get_checksum_via_playwright(vehicle_number, cookies_dict):
    """Sync wrapper"""
    try:
        result, err = asyncio.run(playwright_checksum(vehicle_number, cookies_dict))
        if err:
            return None, None, err
        return result.get("checksum"), result.get("result"), None
    except Exception as e:
        return None, None, str(e)


# ================== RC QUERY (Fallback) ==================
def rc_query_http(cookies_dict, vehicle_number, cf_token=""):
    """HTTP fallback for rc-query"""
    headers = base_headers(f"{NXCAR_BASE}/rc-check")
    headers["Cookie"] = cookies_to_header(cookies_dict)

    token = cookies_dict.get("auth_token", "")
    phone = str(decode_jwt(token).get("username", ""))

    payload = {
        "phone_number": phone,
        "vehicle_number": vehicle_number.upper(),
        "cf_token": cf_token,
    }
    try:
        r = requests.post(RC_QUERY_URL, json=payload, headers=headers, timeout=15)
        data = safe_json(r)
        checksum = (data.get("checksum")
                    or data.get("data", {}).get("checksum")
                    or data.get("result", {}).get("checksum"))
        return checksum, data
    except Exception as e:
        return None, {"error": str(e)}


# ================== VEHICLE DETAILS HTTP ==================
def fetch_details_http(vehicle_number, checksum, token):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
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
        return r.status_code, safe_json(r)
    except Exception as e:
        return 500, {"error": str(e)}


# ================== MAIN FLOW ==================
def get_vehicle(vehicle_number):
    """
    Full auto flow:
      1. Cache check
      2. Try HTTP with saved checksum
      3. Playwright browser (auto checksum)
      4. rc-query HTTP fallback
    """
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
        return 401, {
            "error": "no_token",
            "action": "POST /send-otp → /verify-otp",
        }, "no_token", None

    if not is_token_valid(token):
        return 401, {
            "error": "token_expired",
            "action": "Re-login: /send-otp → /verify-otp",
        }, "expired", None

    # Step 1: Try HTTP with saved checksum
    saved_checksum = session.get("checksum")
    if saved_checksum:
        code, data = fetch_details_http(vehicle_number, saved_checksum, token)
        if code == 200 and not data.get("error"):
            cache[vehicle_number] = {"at": int(time.time()), "data": data}
            save_json(CACHE_FILE, cache)
            return 200, data, "http_saved", saved_checksum

    # Step 2: Playwright (auto checksum)
    print(f"🤖 Playwright: {vehicle_number}")
    checksum, result, err = get_checksum_via_playwright(vehicle_number, cookies_dict)

    if result and not result.get("error"):
        cache[vehicle_number] = {"at": int(time.time()), "data": result}
        save_json(CACHE_FILE, cache)
        return 200, result, "playwright", checksum

    # Step 3: rc-query HTTP + saved checksum
    new_checksum, query_resp = rc_query_http(cookies_dict, vehicle_number, cf_token)
    if new_checksum:
        session["checksum"] = new_checksum
        save_session(session)
        code, data = fetch_details_http(vehicle_number, new_checksum, token)
        if code == 200 and not data.get("error"):
            cache[vehicle_number] = {"at": int(time.time()), "data": data}
            save_json(CACHE_FILE, cache)
            return 200, data, "http_new", new_checksum

    return 500, {
        "error": "all_methods_failed",
        "playwright_err": err,
        "rc_query": query_resp,
        "hint": "Cookies fresh karo ya cf_token daalo",
    }, "failed", None


# ================== ROUTES ==================
HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>NXCar ULTRA PRO</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; padding: 16px;
           background: #0a0a0a; color: #fff; margin: 0; }
    h1 { color: #00ff88; font-size: 20px; }
    .card { background: #1a1a1a; padding: 14px; border-radius: 10px;
            margin: 10px 0; }
    label { font-size: 12px; color: #888; display: block; margin-top: 6px; }
    input, button, textarea { padding: 10px; font-size: 15px;
        border-radius: 6px; border: 1px solid #333;
        background: #222; color: #fff; width: 100%; margin-top: 4px;
        font-family: inherit; }
    button { background: #00ff88; color: #000; font-weight: bold;
             cursor: pointer; margin-top: 8px; }
    button.alt { background: #333; color: #fff; }
    pre { background: #000; padding: 12px; overflow-x: auto;
          border-radius: 6px; font-size: 11px; max-height: 500px;
          line-height: 1.4; }
    .info { font-size: 12px; color: #00ff88; }
  </style>
</head>
<body>
  <h1>🚗 NXCar ULTRA PRO</h1>
  <p class="info">Pehli request slow (30s), baad me cache se fast.</p>

  <div class="card">
    <label>1. Phone</label>
    <input id="phone" value="9612057455">
    <button onclick="sendOtp()">Send OTP</button>
  </div>

  <div class="card">
    <label>2. OTP</label>
    <input id="otp" placeholder="123456">
    <button onclick="verifyOtp()">Verify & Login</button>
  </div>

  <div class="card">
    <label>3. Vehicle Number</label>
    <input id="vnum" value="MH02FZ0555">
    <button onclick="fetchData()">Get Details</button>
    <button class="alt" onclick="showSession()">Session</button>
  </div>

  <div class="card">
    <label>CF Token (optional)</label>
    <input id="cf" placeholder="1.p_EZ...">
    <button class="alt" onclick="importCF()">Save CF</button>
  </div>

  <div class="card">
    <label>Import Cookies (JSON array)</label>
    <textarea id="cookieData" rows="3"></textarea>
    <button class="alt" onclick="importCookies()">Import</button>
  </div>

  <pre id="result">Ready</pre>

<script>
function show(o) {
  document.getElementById('result').textContent =
    typeof o === 'string' ? o : JSON.stringify(o, null, 2);
}
async function sendOtp() {
  const phone = document.getElementById('phone').value.trim();
  show('⏳ Sending OTP to ' + phone);
  const r = await fetch('/send-otp', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone})
  });
  show(await r.json());
}
async function verifyOtp() {
  const otp = document.getElementById('otp').value.trim();
  show('⏳ Verifying...');
  const r = await fetch('/verify-otp', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({otp})
  });
  show(await r.json());
}
async function fetchData() {
  const v = document.getElementById('vnum').value.trim().toUpperCase();
  show('⏳ Fetching ' + v + '... Playwright me 20-30s lag sakta hai');
  const r = await fetch('/vehicle/' + v);
  show(await r.json());
}
async function showSession() {
  const r = await fetch('/session');
  show(await r.json());
}
async function importCF() {
  const cf = document.getElementById('cf').value.trim();
  const r = await fetch('/import-cf', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({cf_token: cf})
  });
  show(await r.json());
}
async function importCookies() {
  try {
    const j = JSON.parse(document.getElementById('cookieData').value);
    const r = await fetch('/import-cookies', {
      method:'POST', headers:{'Content-Type':'application/json'},
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
        "time": int(time.time()),
    })


@app.route("/send-otp", methods=["POST", "GET"])
def route_send_otp():
    if request.method == "GET":
        phone = request.args.get("phone", "")
    else:
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


@app.route("/import-checksum", methods=["POST"])
def route_import_checksum():
    data = request.get_json(silent=True) or {}
    c = data.get("checksum", "")
    if not c:
        return jsonify({"error": "checksum required"}), 400
    session = load_session()
    session["checksum"] = c
    save_session(session)
    return jsonify({"status": "ok", "checksum": c})


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
    print("=" * 60)
    print("  🚀 NXCar ULTRA PRO")
    print("=" * 60)
    print(f"  Port: {port}")
    print(f"  Data: {DATA_DIR}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
