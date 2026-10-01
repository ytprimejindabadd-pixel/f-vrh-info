#!/usr/bin/env python3
"""
nxcar Vehicle Details API - Render Server
Run: python app.py
Then open: https://my-web.onrender.com/rc=MH02FZ0555
"""

import os
import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ---------- CONFIG ----------
BASE_URL = "https://api.nxcar.in/vehicle_details"

# Default token (can be overridden via form)
DEFAULT_AUTH_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJ1c2VyX2lkIjo3ODc4NiwidXNlcm5hbWUiOiI5NjEyMDU3NDU1Iiwicm9sZV9pZCI6IjEiLCJ0b2tlbl92ZXJzaW9uIjoiMSIsIkFQSV9USU1FIjoxNzkwODY0NzUxfQ."
    "qAUgkmfMXrcp1N863xVhI_u50V040Qk7AnPhIUHXbWM"
)

DEFAULT_CHECKSUM = "27ca4c231bb8b41514fb08d5a413862b"


def build_headers(token: str):
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "sec-ch-ua-platform": '"Android"',
        "authorization": token,
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


def fetch_vehicle(vehicle_number: str, checksum: str, token: str):
    params = {
        "vehicle_number": vehicle_number,
        "backend": "yes",
        "checksum": checksum,
    }
    try:
        r = requests.get(BASE_URL, params=params, headers=build_headers(token), timeout=25)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text}
    except requests.RequestException as e:
        return 500, {"error": str(e)}


# ---------- HTML PAGE ----------
PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RC Lookup - Vehicle Details</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    min-height: 100vh;
    color: #e2e8f0;
    padding: 20px;
  }
  .container { max-width: 900px; margin: 0 auto; }
  h1 {
    text-align: center;
    font-size: 28px;
    margin-bottom: 6px;
    background: linear-gradient(90deg, #38bdf8, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .sub { text-align: center; color: #94a3b8; margin-bottom: 24px; font-size: 13px; }
  .card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  }
  label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
    margin-bottom: 6px;
  }
  input, textarea {
    width: 100%;
    padding: 11px 13px;
    border-radius: 9px;
    border: 1px solid #334155;
    background: #0f172a;
    color: #e2e8f0;
    font-size: 14px;
    font-family: inherit;
    outline: none;
    transition: border 0.2s;
  }
  input:focus, textarea:focus { border-color: #38bdf8; }
  textarea { resize: vertical; min-height: 60px; font-family: monospace; font-size: 12px; }
  .field { margin-bottom: 14px; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row > .field { flex: 1; min-width: 200px; }
  button {
    width: 100%;
    padding: 13px;
    border: none;
    border-radius: 9px;
    background: linear-gradient(90deg, #0ea5e9, #8b5cf6);
    color: white;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
  }
  button:hover { opacity: 0.92; }
  button:active { transform: scale(0.99); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .toggle {
    text-align: center;
    margin-top: 14px;
    color: #64748b;
    font-size: 12px;
    cursor: pointer;
    user-select: none;
  }
  .toggle:hover { color: #38bdf8; }
  #advanced { display: none; margin-top: 14px; }
  .result {
    margin-top: 18px;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 16px;
    display: none;
  }
  .result.show { display: block; }
  .result h3 {
    font-size: 13px;
    color: #38bdf8;
    margin-bottom: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .kv {
    display: grid;
    grid-template-columns: 40% 60%;
    gap: 6px 12px;
    font-size: 13px;
  }
  .kv .k { color: #94a3b8; }
  .kv .v { color: #e2e8f0; word-break: break-word; }
  pre {
    background: #020617;
    padding: 12px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 11px;
    color: #67e8f9;
    max-height: 400px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .error { color: #f87171; }
  .spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    background: #064e3b;
    color: #6ee7b7;
  }
  .badge.err { background: #7f1d1d; color: #fca5a5; }
</style>
</head>
<body>
<div class="container">
  <h1>🚗 RC Vehicle Lookup</h1>
  <p class="sub">Enter vehicle number to fetch details</p>

  <div class="card">
    <div class="field">
      <label>Vehicle Number</label>
      <input id="vnum" type="text" placeholder="MH02FZ0555" style="text-transform: uppercase;">
    </div>

    <button id="go" onclick="lookup()">🔍 Get Details</button>

    <div class="toggle" onclick="toggleAdv()">⚙️ Advanced Settings (Auth Token / Checksum)</div>

    <div id="advanced">
      <div class="field" style="margin-top:10px;">
        <label>Authorization Token</label>
        <textarea id="token" placeholder="Paste JWT token here..."></textarea>
      </div>
      <div class="field">
        <label>Checksum</label>
        <input id="checksum" type="text" placeholder="27ca4c231bb8b41514fb08d5a413862b">
      </div>
    </div>
  </div>

  <div id="result" class="result"></div>
</div>

<script>
  // Prefill from localStorage
  const savedToken = localStorage.getItem('nx_token') || '';
  const savedSum   = localStorage.getItem('nx_checksum') || '';
  document.getElementById('token').value    = savedToken;
  document.getElementById('checksum').value = savedSum;

  // Auto-load from URL ?rc=MH02FZ0555
  const urlParams = new URLSearchParams(window.location.search);
  const rcParam = urlParams.get('rc') || window.location.pathname.split('/rc=')[1];
  if (rcParam) {
    document.getElementById('vnum').value = rcParam.toUpperCase();
    setTimeout(lookup, 400);
  }

  function toggleAdv() {
    const a = document.getElementById('advanced');
    a.style.display = a.style.display === 'block' ? 'none' : 'block';
  }

  async function lookup() {
    const vnum = document.getElementById('vnum').value.trim().toUpperCase();
    const token = document.getElementById('token').value.trim();
    const checksum = document.getElementById('checksum').value.trim();

    if (!vnum) { alert('Enter vehicle number'); return; }

    // Save to localStorage
    if (token) localStorage.setItem('nx_token', token);
    if (checksum) localStorage.setItem('nx_checksum', checksum);

    const btn = document.getElementById('go');
    const res = document.getElementById('result');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Fetching...';
    res.className = 'result show';
    res.innerHTML = '<p style="color:#94a3b8">Loading...</p>';

    try {
      const payload = { vehicle_number: vnum };
      if (token) payload.token = token;
      if (checksum) payload.checksum = checksum;

      const r = await fetch('/api/vehicle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await r.json();
      renderResult(data, r.status);
    } catch (e) {
      res.innerHTML = '<h3 class="error">Network Error</h3><p class="error">' + e.message + '</p>';
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🔍 Get Details';
    }
  }

  function renderResult(data, status) {
    const res = document.getElementById('result');
    let html = '';

    // Try to find the actual vehicle data
    let v = data;
    if (data && data.data && typeof data.data === 'object') v = data.data;
    if (data && data.result && typeof data.result === 'object') v = data.result;

    if (status >= 400 || (data && data.error)) {
      html += '<h3><span class="badge err">ERROR</span></h3>';
      html += '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
      res.innerHTML = html;
      return;
    }

    html += '<h3><span class="badge">SUCCESS</span> Vehicle Details</h3>';

    // Friendly key-value view
    const flat = flatten(v);
    if (Object.keys(flat).length > 0) {
      html += '<div class="kv">';
      for (const [k, val] of Object.entries(flat)) {
        html += `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(String(val))}</div>`;
      }
      html += '</div>';
    }

    // Raw JSON toggle
    html += '<div class="toggle" style="margin-top:14px;" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\\'block\\'?\\'none\\':\\'block\\'">📄 Show Raw JSON</div>';
    html += '<pre style="display:none;margin-top:10px;">' + JSON.stringify(data, null, 2) + '</pre>';

    res.innerHTML = html;
  }

  function flatten(obj, prefix = '') {
    const out = {};
    if (!obj || typeof obj !== 'object') return out;
    for (const [k, v] of Object.entries(obj)) {
      const key = prefix ? prefix + ' → ' + k : k;
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        Object.assign(out, flatten(v, key));
      } else if (Array.isArray(v)) {
        out[key] = v.join(', ');
      } else if (v !== null && v !== '') {
        out[key] = v;
      }
    }
    return out;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // Enter key
  document.getElementById('vnum').addEventListener('keydown', e => {
    if (e.key === 'Enter') lookup();
  });
</script>
</body>
</html>
"""


# ---------- ROUTES ----------

@app.route("/")
def home():
    return render_template_string(PAGE_HTML)


@app.route("/rc=<path:vehicle_number>")
def rc_path(vehicle_number):
    """Pretty URL: /rc=MH02FZ0555"""
    return render_template_string(PAGE_HTML)


@app.route("/api/vehicle", methods=["POST"])
def api_vehicle():
    """Hidden backend - handles auth token + checksum internally."""
    body = request.get_json(silent=True) or {}
    vnum = (body.get("vehicle_number") or "").strip().upper()
    token = (body.get("token") or "").strip() or DEFAULT_AUTH_TOKEN
    checksum = (body.get("checksum") or "").strip() or DEFAULT_CHECKSUM

    if not vnum:
        return jsonify({"error": "vehicle_number required"}), 400

    code, data = fetch_vehicle(vnum, checksum, token)
    return jsonify(data), code


@app.route("/vehicle/<vehicle_number>")
def vehicle(vehicle_number):
    """Legacy GET endpoint."""
    checksum = request.args.get("checksum", DEFAULT_CHECKSUM)
    token = request.args.get("token", DEFAULT_AUTH_TOKEN)
    code, data = fetch_vehicle(vehicle_number.upper(), checksum, token)
    return jsonify(data), code


# ---------- MAIN ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  nxcar Vehicle Details Server")
    print(f"  Local:   http://127.0.0.1:{port}/")
    print(f"  Example: http://127.0.0.1:{port}/rc=MH02FZ0555")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
