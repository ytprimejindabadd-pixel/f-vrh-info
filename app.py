#!/usr/bin/env python3
"""
🚀 NXCar ULTRA Auto — Render.com Deploy
- Persistent browser profile
- Auto token from cookies
- Auto checksum
- Result cache
"""

import os
import json
import time
import asyncio
import base64
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ================== PATHS (Render me /tmp use karo) ==================
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/nxcar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

BROWSER_PROFILE = DATA_DIR / "browser_profile"
SESSION_FILE = DATA_DIR / "session.json"
CACHE_FILE = DATA_DIR / "cache.json"

CACHE_TTL = 600  # 10 min

# ================== CONFIG ==================
PHONE = os.environ.get("NXCAR_PHONE", "9816072037")
USER_ID = os.environ.get("NXCAR_USER_ID", "d5f32474-9310-4cef-b0ef-3c618112b588")
NXCAR_USER_ID = os.environ.get("NXCAR_NUMERIC_ID", "78625")
ROLE_ID = os.environ.get("NXCAR_ROLE_ID", "1")

NXCAR_BASE = "https://www.nxcar.in"
NXCAR_API = "https://api.nxcar.in/vehicle_details"


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


def save_session(data):
    save_json(SESSION_FILE, data)


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
    data = decode_jwt(token)
    age = int(time.time()) - data.get("API_TIME", 0)
    return age < (25 * 24 * 3600)


# ================== BROWSER AUTO ==================
async def browser_fetch(vehicle_number):
    """
    Persistent browser se auto token + vehicle fetch
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "playwright_not_installed"}

    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            headless=True,
            user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
            viewport={"width": 390, "height": 844},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        # Imported cookies inject karo
        session = load_session()
        imported = session.get("imported_cookies")
        if imported:
            try:
                await ctx.add_cookies(imported)
            except Exception:
                pass

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        captured = {"result": None, "checksum": None, "token": None}

        async def on_response(resp):
            if "api.nxcar.in/vehicle_details" in resp.url:
                try:
                    captured["result"] = await resp.json()
                except Exception:
                    pass
            if "vehicle_details" in resp.url and "checksum=" in resp.url:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(resp.url).query)
                c = q.get("checksum", [None])[0]
                if c:
                    captured["checksum"] = c

        page.on("response", on_response)

        try:
            await page.goto(f"{NXCAR_BASE}/rc-check",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)

            # Cookies se token
            cookies = await ctx.cookies()
            for c in cookies:
                if c["name"] == "auth_token":
                    captured["token"] = c["value"]
                    break

            if not captured["token"]:
                # Imported cookies se try
                if imported:
                    for c in imported:
                        if c.get("name") == "auth_token":
                            captured["token"] = c["value"]
                            break

            if not captured["token"]:
                await ctx.close()
                return {"error": "not_logged_in",
                        "hint": "Use /import-cookies to set session"}

            # Vehicle search
            try:
                inp = await page.query_selector(
                    'input[placeholder*="number" i], input[type="text"]'
                )
                if inp:
                    await inp.click()
                    await inp.fill(vehicle_number)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(8000)
            except Exception as e:
                print(f"Search error: {e}")

            # Direct API fallback
            if not captured["result"] and captured["checksum"]:
                try:
                    captured["result"] = await page.evaluate(f"""
                        async () => {{
                            const r = await fetch(
                                "https://api.nxcar.in/vehicle_details?vehicle_number={vehicle_number}&backend=yes&checksum={captured['checksum']}",
                                {{ headers: {{ "authorization": "{captured['token']}" }} }}
                            );
                            return await r.json();
                        }}
                    """)
                except Exception as e:
                    print(f"Fetch error: {e}")

            # Save token
            if captured["token"]:
                session = load_session()
                session["auth_token"] = captured["token"]
                session["auth_token_at"] = int(time.time())
                session["cookies"] = [
                    {"name": c["name"], "value": c["value"],
                     "domain": ".nxcar.in", "path": "/"}
                    for c in cookies
                ]
                if captured["checksum"]:
                    session["checksum"] = captured["checksum"]
                save_session(session)

            await ctx.close()
            return {
                "token": captured["token"],
                "checksum": captured["checksum"],
                "result": captured["result"],
            }

        except Exception as e:
            try:
                await ctx.close()
            except Exception:
                pass
            return {"error": str(e)}


# ================== SIMPLE HTTP FALLBACK ==================
def http_fetch(vehicle_number):
    """
    Bina browser ke — cookies use karke direct API
    """
    import requests

    session = load_session()
    token = session.get("auth_token")

    if not token or not is_token_valid(token):
        return None  # Browser chahiye

    # Cookies string
    cookies_raw = session.get("cookies_raw", "")
    if not cookies_raw:
        cookies_raw = (f"user_id={USER_ID}; auth_token={token}; "
                       f"nxcar_user_id={NXCAR_USER_ID}; role_id={ROLE_ID}")

    # Step 1: rc-query se checksum
    headers1 = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/rc-check",
        "Cookie": cookies_raw,
    }
    payload = {
        "phone_number": PHONE,
        "vehicle_number": vehicle_number.upper(),
        "cf_token": session.get("cf_token", ""),
    }

    try:
        r1 = requests.post(f"{NXCAR_BASE}/api/nxcar/rc-query",
                           json=payload, headers=headers1, timeout=15)
        query_data = r1.json()
        checksum = (query_data.get("checksum")
                    or query_data.get("data", {}).get("checksum")
                    or session.get("checksum", ""))
    except Exception:
        checksum = session.get("checksum", "")

    if not checksum:
        return None  # Browser chahiye

    # Step 2: vehicle_details
    headers2 = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "authorization": token,
        "origin": NXCAR_BASE,
        "referer": f"{NXCAR_BASE}/",
    }
    try:
        r2 = requests.get(NXCAR_API, params={
            "vehicle_number": vehicle_number.upper(),
            "backend": "yes",
            "checksum": checksum,
        }, headers=headers2, timeout=20)

        if r2.status_code == 200:
            return r2.json()
        return None
    except Exception:
        return None


# ================== MAIN FLOW ==================
def ultra_fetch(vehicle_number):
    vehicle_number = vehicle_number.upper()
    cache = load_json(CACHE_FILE)

    # Cache
    if vehicle_number in cache:
        c = cache[vehicle_number]
        if time.time() - c.get("at", 0) < CACHE_TTL:
            return 200, c["data"], "cache"

    # Try HTTP first (fast)
    http_result = http_fetch(vehicle_number)
    if http_result:
        cache[vehicle_number] = {"at": int(time.time()), "data": http_result}
        save_json(CACHE_FILE, cache)
        return 200, http_result, "http"

    # Browser fallback (slow but works)
    result = asyncio.run(browser_fetch(vehicle_number))

    if result.get("error"):
        return 500, result, "browser_error"

    data = result.get("result")
    if not data:
        return 500, {"error": "no_result", "details": result}, "no_result"

    cache[vehicle_number] = {"at": int(time.time()), "data": data}
    save_json(CACHE_FILE, cache)
    return 200, data, "browser"


# ================== ROUTES ==================
HTML_HOME = """
<!DOCTYPE html>
<html>
<head>
    <title>NXCar ULTRA</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, sans-serif; padding: 20px;
               background: #0a0a0a; color: #fff; }
        h1 { color: #00ff88; }
        .box { background: #1a1a1a; padding: 15px; border-radius: 8px;
               margin: 10px 0; }
        input, button { padding: 10px; font-size: 16px; border-radius: 5px;
                       border: 1px solid #333; background: #222; color: #fff; }
        button { background: #00ff88; color: #000; cursor: pointer;
                font-weight: bold; }
        pre { background: #000; padding: 15px; overflow-x: auto;
              border-radius: 5px; font-size: 12px; }
        .status { color: #00ff88; }
    </style>
</head>
<body>
    <h1>🚗 NXCar ULTRA</h1>
    <div class="box">
        <input id="vnum" placeholder="MH02FZ0555" value="MH02FZ0555">
        <button onclick="fetchData()">Get Details</button>
    </div>
    <pre id="result">Ready...</pre>

    <script>
        async function fetchData() {
            const v = document.getElementById('vnum').value;
            const r = document.getElementById('result');
            r.textContent = '⏳ Loading... (may take 10-30 sec if browser needed)';
            try {
                const resp = await fetch('/vehicle/' + v);
                const data = await resp.json();
                r.textContent = JSON.stringify(data, null, 2);
            } catch(e) {
                r.textContent = 'Error: ' + e.message;
            }
        }
    </script>
</body>
</html>
"""


@app.route("/")
def home():
    session = load_session()
    cache = load_json(CACHE_FILE)
    return render_template_string(HTML_HOME)


@app.route("/vehicle/<vehicle_number>")
def vehicle(vehicle_number):
    print(f"\n{'='*60}")
    print(f"🚗 {vehicle_number}")
    code, data, source = ultra_fetch(vehicle_number)
    print(f"📡 {code} via {source}")
    print(f"{'='*60}\n")
    resp = jsonify(data)
    resp.headers["X-Source"] = source
    return resp, code


@app.route("/session")
def session_info():
    s = load_session()
    token = s.get("auth_token", "")
    return jsonify({
        "has_token": bool(token),
        "valid": is_token_valid(token),
        "decoded": decode_jwt(token) if token else {},
        "checksum": s.get("checksum", ""),
        "cf_token_set": bool(s.get("cf_token")),
    })


@app.route("/import-cookies", methods=["POST", "GET"])
def import_cookies():
    """Cookies import karo — POST JSON ya GET query"""
    if request.method == "GET":
        cookie_str = request.args.get("cookie", "")
        cf_token = request.args.get("cf_token", "")
    else:
        data = request.get_json(silent=True) or {}
        cookie_str = data.get("cookie", "")
        cf_token = data.get("cf_token", "")

    if not cookie_str:
        return jsonify({"error": "cookie required"}), 400

    # Parse cookies
    cookies = []
    cookie_dict = {}
    for item in cookie_str.split(";"):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            cookies.append({
                "name": k, "value": v,
                "domain": ".nxcar.in", "path": "/",
            })
            cookie_dict[k] = v

    auth_token = cookie_dict.get("auth_token")
    if not auth_token:
        return jsonify({"error": "auth_token not found in cookies"}), 400

    session = load_session()
    session["auth_token"] = auth_token
    session["cookies"] = cookies
    session["imported_cookies"] = cookies
    session["cookies_raw"] = cookie_str
    session["updated_at"] = int(time.time())
    if cf_token:
        session["cf_token"] = cf_token
    save_session(session)

    return jsonify({
        "status": "ok",
        "token_preview": auth_token[:40] + "...",
        "valid": is_token_valid(auth_token),
        "cookies_count": len(cookies),
        "cf_token_set": bool(cf_token),
    })


@app.route("/import-cf", methods=["POST", "GET"])
def import_cf():
    if request.method == "GET":
        cf_token = request.args.get("cf_token", "")
    else:
        data = request.get_json(silent=True) or {}
        cf_token = data.get("cf_token", "")

    if not cf_token:
        return jsonify({"error": "cf_token required"}), 400

    session = load_session()
    session["cf_token"] = cf_token
    save_session(session)
    return jsonify({"status": "ok", "cf_token_length": len(cf_token)})


@app.route("/refresh")
def refresh():
    """Browser se token refresh karo"""
    result = asyncio.run(browser_fetch("MH02FZ0555"))
    return jsonify(result)


@app.route("/clear-cache")
def clear_cache():
    save_json(CACHE_FILE, {})
    return jsonify({"status": "ok"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": int(time.time())})


# ================== MAIN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  🚀 NXCar ULTRA Auto Server")
    print("=" * 60)
    print(f"  Port: {port}")
    print(f"  Data: {DATA_DIR}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
