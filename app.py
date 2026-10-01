#!/usr/bin/env python3
"""
nxcar Vehicle Details - Clean URL Version
URL: https://my-web.onrender.com/rc=MH02FZ0555
Token & Checksum hidden in backend
"""

import os
import requests
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

BASE_URL = "https://api.nxcar.in/vehicle_details"

# ---------- HIDDEN CONFIG (Render Environment Variables) ----------
# Render → Environment → Add these:
#   NXCAR_TOKEN    = your JWT
#   NXCAR_CHECKSUMS = comma separated checksum list (optional fallback)
AUTH_TOKEN = os.environ.get("NXCAR_TOKEN", "").strip()
DEFAULT_CHECKSUMS = [
    c.strip() for c in os.environ.get("NXCAR_CHECKSUMS", "").split(",") if c.strip()
]

# Manual checksum map (agar tumhe pata hai kis vehicle ka kaunsa checksum hai)
# Format: {"MH02FZ0555": "27ca4c231bb8b41514fb08d5a413862b"}
CHECKSUM_MAP = {
    # "MH02FZ0555": "27ca4c231bb8b41514fb08d5a413862b",
}


def build_headers(auth_token: str):
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "sec-ch-ua-platform": '"Android"',
        "authorization": auth_token,
        "sec-ch-ua": '"Not=A?Brand";v="99", "Brave";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?1",
        "sec-gpc": "1",
        "origin": "https://www.nxcar.in",
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": "https://www.nxcar.in/",
        "accept-language": "en-US,en;q=0.6",
        "priority": "u=1, i",
    }


def try_checksum(vehicle_number: str, checksum: str):
    params = {"vehicle_number": vehicle_number, "backend": "yes", "checksum": checksum}
    try:
        r = requests.get(BASE_URL, params=params, headers=build_headers(AUTH_TOKEN), timeout=20)
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        return r.status_code, data
    except requests.RequestException as e:
        return 500, {"error": str(e)}


def fetch_vehicle_hidden(vehicle_number: str):
    """
    Try all possible checksums until we get a valid response.
    1. Check CHECKSUM_MAP first
    2. Then try DEFAULT_CHECKSUMS list
    """
    if not AUTH_TOKEN:
        return 500, {"error": "Server token not configured. Set NXCAR_TOKEN on Render."}

    # Step 1: check manual map
    if vehicle_number in CHECKSUM_MAP:
        code, data = try_checksum(vehicle_number, CHECKSUM_MAP[vehicle_number])
        if code == 200 and not data.get("error"):
            return code, data
        # if failed, fall through to brute list

    # Step 2: try all default checksums
    if not DEFAULT_CHECKSUMS:
        return 500, {
            "error": "No checksums configured. Add NXCAR_CHECKSUMS env var or CHECKSUM_MAP."
        }

    last_error = None
    for cs in DEFAULT_CHECKSUMS:
        code, data = try_checksum(vehicle_number, cs)
        # success = 200 and no error key and has meaningful data
        if code == 200 and isinstance(data, dict) and not data.get("error"):
            return code, data
        last_error = (code, data)

    return last_error or (500, {"error": "All checksums failed"})


# ---------- HTML PAGE ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>nxcar RC Lookup</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    padding: 20px;
    color: #333;
  }
  .container {
    max-width: 800px; margin: 0 auto; background: #fff;
    border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); overflow: hidden;
  }
  .header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff; padding: 28px 30px;
  }
  .header h1 { font-size: 22px; margin-bottom: 6px; }
  .header p { opacity: 0.9; font-size: 13px; }
  .body { padding: 30px; }
  .search {
    display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;
  }
  .search input {
    flex: 1; min-width: 200px;
    padding: 14px 16px; border: 2px solid #e2e8f0; border-radius: 10px;
    font-size: 16px; font-weight: 600; letter-spacing: 1px;
    text-transform: uppercase; background: #f8fafc;
  }
  .search input:focus {
    outline: none; border-color: #667eea; background: #fff;
    box-shadow: 0 0 0 4px rgba(102,126,234,0.1);
  }
  .search button {
    padding: 14px 28px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff; border: none; border-radius: 10px;
    font-size: 16px; font-weight: 600; cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
  }
  .search button:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(102,126,234,0.4); }
  .search button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
  .loader { display: none; text-align: center; padding: 30px; color: #667eea; font-weight: 600; }
  .loader.active { display: block; }
  .spinner {
    display: inline-block; width: 22px; height: 22px;
    border: 3px solid #e2e8f0; border-top-color: #667eea;
    border-radius: 50%; animation: spin 0.7s linear infinite;
    vertical-align: middle; margin-right: 10px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .result { margin-top: 10px; animation: fadeIn 0.3s; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .badge {
    display: inline-block; padding: 6px 14px; border-radius: 8px;
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    margin-bottom: 14px;
  }
  .badge.ok { background: #d1fae5; color: #065f46; }
  .badge.err { background: #fee2e2; color: #991b1b; }
  pre {
    background: #1e293b; color: #e2e8f0; padding: 18px;
    border-radius: 10px; overflow-x: auto; font-size: 13px;
    line-height: 1.6; max-height: 600px;
  }
  .hint { font-size: 12px; color: #94a3b8; margin-top: 12px; text-align: center; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🚗 nxcar RC Lookup</h1>
      <p>Enter vehicle number — token & checksum handled on server</p>
    </div>
    <div class="body">
      <div class="search">
        <input id="vehicle" type="text" placeholder="MH02FZ0555" value="{{ vehicle }}" autofocus>
        <button id="go" onclick="run()">🔍 Search</button>
      </div>
      <div class="loader" id="loader"><span class="spinner"></span>Fetching vehicle details...</div>
      <div class="result" id="result"></div>
      <div class="hint">Try: /rc=MH02FZ0555 in URL for direct lookup</div>
    </div>
  </div>

<script>
async function run() {
  const vehicle = document.getElementById('vehicle').value.trim().toUpperCase();
  if (!vehicle) return alert('Enter vehicle number');

  const btn = document.getElementById('go');
  const loader = document.getElementById('loader');
  const result = document.getElementById('result');

  btn.disabled = true;
  loader.classList.add('active');
  result.innerHTML = '';

  try {
    const res = await fetch('/rc=' + encodeURIComponent(vehicle));
    const data = await res.json();
    const ok = res.ok && !data.error;

    result.innerHTML = `
      <span class="badge ${ok ? 'ok' : 'err'}">${ok ? '✓ Success' : '✗ Failed'}</span>
      <pre>${JSON.stringify(data, null, 2).replace(/</g, '&lt;')}</pre>
    `;
  } catch (e) {
    result.innerHTML = `<span class="badge err">Error</span><pre>${e.message}</pre>`;
  }

  btn.disabled = false;
  loader.classList.remove('active');
}

// Enter key triggers search
document.getElementById('vehicle').addEventListener('keypress', e => {
  if (e.key === 'Enter') run();
});
</script>
</body>
</html>
"""


# ---------- ROUTES ----------

@app.route("/rc=<vehicle_number>")
def rc_lookup(vehicle_number):
    """
    Clean URL: /rc=MH02FZ0555
    Directly returns JSON (works for both browser + API calls)
    """
    vehicle_number = vehicle_number.strip().upper()

    # Basic validation
    if not (5 <= len(vehicle_number) <= 15):
        return jsonify({"error": "Invalid vehicle number"}), 400

    # Check if request wants HTML (browser) or JSON (API)
    wants_html = "text/html" in request.headers.get("Accept", "") if False else False
    # Actually let's just always return JSON — simpler

    code, data = fetch_vehicle_hidden(vehicle_number)
    return jsonify(data), code


@app.route("/")
def home():
    return render_template_string(HTML_PAGE, vehicle="")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "token_set": bool(AUTH_TOKEN),
        "checksums_count": len(DEFAULT_CHECKSUMS),
        "map_entries": len(CHECKSUM_MAP),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"nxcar server running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
