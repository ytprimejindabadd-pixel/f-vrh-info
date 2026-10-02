#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 Unified Vehicle Details API
Single endpoint /adv?rc=MH02FZ0555 — runs all APIs in parallel.
Deploy on Render — no extra config needed.
"""

import re
import os
import json
import time
import base64
import hashlib
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

app = Flask(__name__)

UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36")

# ============================================================
# ═══════════════ API 1 ═══════════════
# ============================================================
URL_1 = "https://insurance-v2.parkplus.io/api/v2/vehicle"
TOKEN_1 = os.environ.get("TOKEN_1", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiIsImtpZCI6InYxIn0.eyJleHAiOjE3OTM0MjgxODAsInN1YiI6IjM3NDg3MDQwIiwidW5pcXVlX2lkIjoiZ3V3a3RhUUtQRFBMY2pWUGVFUFpmUFJYSEJPUVVkand5VFZsUW9Xb1NpSUdtS0VoakpCY09YZ2xRU1l5ek1FeCIsImh0dHBzOi8vcGFya3doZWVscy5jby5pbi8iOnsidXNlcl9pZCI6Mzc0ODcwNDAsIm5hbWUiOiIgIiwiZW1haWwiOiIiLCJwaG9uZV9udW1iZXIiOiI4MDk5NDg1MTEwIiwicm9sZSI6ImNsaWVudCIsImRldmljZV9pZCI6bnVsbCwidmVyc2lvbiI6NCwidGVzdF91c2VyIjpmYWxzZX19.0gJhqB1rycVLsuXo9y71kB4wZ4m0SgtQPLANE0R_MFLkBCuO8qrz-Y6BDz2uVEezSvDzUmQ-bVhIAVNUMf0uTA")


def api_1(rc):
    token = os.environ.get("TOKEN_1", TOKEN_1)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "authorization": token,
        "app-name": "Park+ PWA",
        "content-type": "application/json;charset=UTF-8",
        "platform": "web",
        "origin": "https://parkplus.io",
        "referer": "https://parkplus.io/",
        "client-id": "8186c1be-660f-428c-93a7-6480c2d8af66",
        "client-secret": "hjjh0uw8c3j7vw5jgba8",
        "device-id": "75112be82bf6deb427e4a5e26b6cf58b",
        "new-device-id": "75112be82bf6deb427e4a5e26b6cf58b",
        "package-name": "web.pwa",
        "accept-language": "en-US,en;q=0.8",
    }
    try:
        r = requests.post(
            URL_1,
            json={"source": "existing-car", "vehicle_number": rc},
            headers=headers, timeout=20,
        )
        return _try_json(r)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ═══════════════ API 2 ═══════════════
# ============================================================
BASE_2 = "https://vehicle.cars24.team/v1/2025-09/vehicle-number"
AUTH_2 = "Basic YzJiX2Zyb250ZW5kOko1SXRmQTk2bTJfY3lRVk00dEtOSnBYaFJ0c0NtY1h1"


def api_2(rc):
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "authorization": AUTH_2,
        "device_category": "mSite",
        "origin_source": "c2b-website",
        "platform": "rto",
        "origin": "https://www.cars24.com",
        "referer": "https://www.cars24.com/",
        "accept-language": "en-US,en;q=0.8",
    }
    try:
        r = requests.get(f"{BASE_2}/{rc}", headers=headers, timeout=20)
        return _try_json(r)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ═══════════════ API 3 ═══════════════
# ============================================================
URL_3 = "https://carinfo.pbwheels.com/api/Vahan/getdetails"
SID_3 = os.environ.get("SID_3", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJFbnF1aXJ5SWQiOiIxNDkxNDI4IiwiQ2F0ZWdvcnlJZCI6IlZBSEFOIiwiTGVhZElkIjoiODM5MDI2IiwiVmlzaXRJZCI6IjE1NzI0NTEiLCJSZWdOdW1iZXIiOiJNSDAyRlowNTU1IiwiQ3VzdG9tZXJJZCI6IjY4NDM3NjUiLCJuYmYiOjE3OTA4MzczNTksImV4cCI6MjUzNDAyMzAwODAwLCJpYXQiOjE3OTA4MzczNTl9.mQQzzv28a1udz6OCg5S_tP-aFVGDurOIzdDthBCwSgI")
COOKIE_3 = os.environ.get("COOKIE_3", "PbwVisitId=1572451; CustomerAccessToken=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJDdXN0b21lcklkIjoiNjg0Mzc2NSIsIlR5cGUiOiJGcmVzaCIsIlNlc3Npb25JZCI6IjE5MWIzNzM1ZGIzZjQ0MTRhNTcxMTA4NzI2OWZhZjUwIiwiQ2F0ZWdvcnkiOiJSZWd1bGFyIiwibmJmIjoxNzkwODM3MzU4LCJleHAiOjE3OTM0MjkzNTgsImlhdCI6MTc5MDgzNzM1OH0.E0PC3xb6YVCgUnc45D37FSrSjDAvrLELT19UoCxU7NWbaO7rcCJJ5aRaHbHtyobbFPrW6TnWPlouDdtqflLYHY1hK968BKnxSAuxzhgJycgKAdvXIvFzGlJQjcSP0o-qmEa-jUPH5QX6QvtCnrFl294Iiq1RpIYSa9W--6OAGmBiUpgqTqNV3HgQJi2TU9oUBIOoDCi84TSFp8xcYDAe57aQCPmm6KbnsPkv09sMs3EFofylMwP8Krp8KN-gVLjb0aFDhtgCchMtqTapgjst12yWuyZ5wsHs346BcADrlp6nw_B6BELnSYBHGf6fLGpQZJQl0jChidv6-rCOs38lDA")


def api_3(rc):
    sid = os.environ.get("SID_3", SID_3)
    cookie = os.environ.get("COOKIE_3", COOKIE_3)
    try:
        p = sid.split('.')[1]
        p += '=' * (-len(p) % 4)
        payload = json.loads(base64.urlsafe_b64decode(p))
        embedded = payload.get("RegNumber", "").upper()
        if embedded and embedded != rc:
            return {"warning": f"Token bound to {embedded}, requested {rc}"}
    except Exception:
        pass

    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
        "origin": "https://carinfo.pbwheels.com",
        "referer": f"https://carinfo.pbwheels.com/vahan?sid={sid}",
        "accept-language": "en-US,en;q=0.8",
        "Cookie": cookie,
    }
    try:
        r = requests.post(URL_3, json={"sid": sid}, headers=headers, timeout=30)
        return _try_json(r)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ═══════════════ API 4 ═══════════════
# ============================================================
URL_4 = "https://api.spinny.com/v3/api/supply/rto/"
COOKIES_4 = {
    "platform": "mweb_android",
    "hasDeliveredCar": "false",
    "csrftoken": os.environ.get("CSRF_4", "U0nC1zP1cezBOZ1F9ODEludYYhQqNNtK02vs3UlWNibLRZmrjiRhAqtV1BPJZAJW"),
    "sessionid": os.environ.get("SESS_4", "wsa83wc503gnlxke930fxftkbuwnpk9d"),
}


def api_4(rc):
    headers = {
        "User-Agent": UA,
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
        "platform": "mweb_android",
        "origin": "https://www.spinny.com",
        "referer": "https://www.spinny.com/",
        "accept-language": "en-US,en;q=0.5",
    }
    try:
        r = requests.post(
            URL_4,
            json={"registration_number": rc.lower()},
            headers=headers,
            cookies=COOKIES_4,
            timeout=30,
        )
        return _try_json(r)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ═══════════════ API 5 ═══════════════
# ============================================================
BASE_5 = "https://restapi.vahandetails.com"
POW_5 = f"{BASE_5}/api/auth/pow-challenge"
TOK_5 = f"{BASE_5}/api/auth/session-token"
SEARCH_5 = f"{BASE_5}/api/vehicles/search"

HEADERS_5 = {
    'User-Agent': UA,
    'Accept-Encoding': "gzip, deflate",
    'Content-Type': "application/json",
    'Origin': "https://vahandetails.com",
    'Referer': "https://vahandetails.com/",
    'Accept-Language': "en-US,en;q=0.9",
}


def _pow_solve(challenge, difficulty):
    prefix = "0" * difficulty
    for nonce in range(10_000_000):
        h = hashlib.sha256(f"{challenge}{nonce}".encode()).hexdigest()
        if h.startswith(prefix):
            return str(nonce)
    raise Exception("PoW failed")


def _gen_token_5():
    for _ in range(5):
        try:
            r = requests.get(POW_5, headers=HEADERS_5, timeout=15)
            if r.status_code != 200:
                time.sleep(1); continue
            d = r.json()
            ch, diff = d.get("challenge"), int(d.get("difficulty", 4))
            if not ch:
                time.sleep(1); continue
            nonce = _pow_solve(ch, diff)
            r2 = requests.post(TOK_5, json={"challenge": ch, "solution": nonce},
                               headers=HEADERS_5, timeout=15)
            if r2.status_code == 200:
                tok = r2.json().get("token")
                if tok:
                    return tok
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


class _Pool5:
    def __init__(self, size=2):
        self.lock = threading.Lock()
        self.tokens = []
        threads = [threading.Thread(target=self._gen, daemon=True) for _ in range(size)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=60)

    def _gen(self):
        tok = _gen_token_5()
        if tok:
            with self.lock:
                self.tokens.append(tok)

    def get(self):
        with self.lock:
            if not self.tokens:
                tok = _gen_token_5()
                if tok:
                    self.tokens.append(tok)
                    return tok
                return None
            tok = self.tokens.pop(0)
            self.tokens.append(tok)
            return tok


_pool_5 = None


def api_5(rc):
    global _pool_5
    if _pool_5 is None:
        try:
            _pool_5 = _Pool5(size=2)
        except Exception as e:
            return {"error": f"pool init failed: {e}"}

    for attempt in range(3):
        tok = _pool_5.get()
        if not tok:
            return {"error": "no token"}
        h = dict(HEADERS_5)
        h["X-Session-Token"] = tok
        try:
            r = requests.post(SEARCH_5, json={"rc_regn_no": rc},
                              headers=h, timeout=20)
            if r.status_code in (401, 403):
                continue
            return _try_json(r)
        except Exception as e:
            return {"error": str(e)}
    return {"error": "all retries failed"}


# ============================================================
# ═══════════════ API 6 ═══════════════
# ============================================================
BASE_6 = "https://vahanx.in"
HOME_6 = f"{BASE_6}/rc-search"
SEARCH_6 = f"{BASE_6}/rc-search/{{rc}}"


class _Session6:
    def __init__(self, name):
        self.name = name
        self.session = requests.Session()
        self.token = None
        self.cookies_ok = False
        self.last_refresh = 0

    def refresh(self):
        try:
            r = self.session.get(HOME_6, timeout=20, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            })
            if r.status_code != 200:
                return False
            m = re.search(r'window\.VX_ST\s*=\s*\{([^}]+)\}', r.text, re.S)
            if not m:
                return False
            rm = re.search(r'rc\s*:\s*"([^"]+)"', m.group(1))
            if not rm:
                return False
            self.token = rm.group(1)
            self.cookies_ok = True
            self.last_refresh = time.time()
            return True
        except Exception:
            return False

    def search(self, rc):
        if not self.token or (time.time() - self.last_refresh) > 900:
            if not self.refresh():
                return None, "refresh_failed"
        url = SEARCH_6.format(rc=rc)
        try:
            r = self.session.get(url, params={"t": self.token}, timeout=25,
                                 headers={
                                     "User-Agent": UA,
                                     "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                     "Accept-Encoding": "gzip, deflate",
                                 })
            if r.status_code in (401, 403, 419):
                self.token = None
                if self.refresh():
                    return self.search(rc)
                return None, "token_expired"
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            return r.text, "ok"
        except Exception as e:
            return None, str(e)


_pool_6 = None


def _parse_6(html, rc):
    soup = BeautifulSoup(html, "html.parser")
    data = {"rc_number": rc}
    for card in soup.find_all("div", class_="hrc-details-card"):
        for item in card.find_all("div", class_=re.compile(r"col-sm-6|col-12")):
            lbl = item.find("span", class_="text-muted")
            val = item.find("p", class_="fw-semibold")
            if not lbl or not val:
                continue
            k = lbl.get_text(strip=True).lower()
            v = val.get_text(" ", strip=True)
            if not v or v.upper() in ("NA", "N/A"):
                continue
            key = (k.replace(" ", "_").replace("-", "_"))
            data[key] = v
    return data


def api_6(rc):
    global _pool_6
    if _pool_6 is None:
        _pool_6 = _Session6("main")
        _pool_6.refresh()

    for attempt in range(3):
        html, status = _pool_6.search(rc)
        if status == "ok" and html:
            return _parse_6(html, rc)
        time.sleep(0.5)
    return {"error": f"failed: {status}"}


# ============================================================
# ═══════════════ API 7 ═══════════════
# ============================================================
CD_BASE = "https://apis.cardekho.com/f8"
CD_LISTING = "https://listing.cardekho.com/api/v1/rto/vehicle-details"
CD_FALLBACK = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJtb2JpbGUiOiI5MzY1NDYzOTExIiwi"
    "Y29ubmVjdG9pZCI6ImZmZTVhOTFkLTRmMTEtMmUwNy01NzgwLTVlYWU5MWY1NjQ2YSIs"
    "IndhT3RwIjpmYWxzZSwiaW50ZW50U291cmNlIjoiZGlyZWN0IiwicGxhdGZvcm0iOiJ3"
    "YXAiLCJ1dG1QYXJhbXMiOnt9LCJpYXQiOjE3OTA5MDY5NTMsImV4cCI6MTc5ODY4Mjk1"
    "M30.sxUM1x58Gg7KmgE_qK5OGZvVb4lgyUEQ369ImIJ2Q4d5O9BiUiniVxazj4oiMBfj"
    "dK3OV5R8V-i13P3uTl0wblv_WTcfppYkwLBtsMvaUdjgnwiMZVDgTAZ4zoL7ThL-X2X"
    "5DHMxC5DKyuvmXckdJlPpggQWoCA1W5v1LsJJlYRluOeBoU2fM9rARxjzi3wa398edX"
    "Mw4Xkt_W9k_LlkrXJSqgUrek5XMn1OftEOktGTdrN2cwukphAQy9x0MQdqVFDemNTf"
    "f-x-Bc84qMS8aRlSEPlzpADX79IGYBA12tZ8VWsiMXgu66NIXIN3-abjw2Hm8Tdix1"
    "GuipMxORHSYvq_V4se6WbqTJlSpTFgHiEW-FpbF0C-zzojEPcfBF9FbXOxUFNz7d3d"
    "bF80FKvnkYc6MUOrln5LZaZzoKeygWv6xCIQtH4Jrf2CZ1mEXUgE-D4zY0cc1ShsXt1"
    "4JDMJtHa-sJvJywFCBsAIGb5_EXKtEEQXwzrRCFgK2pIHZjwdR_6w74wtjNS6fU-sa"
    "3Lb3uTyyix7Zj_XJrYhn0FcfThE_Nd1wJM1hP-rBm-4NEkVtj6yMp4e1GNUVJ55G2se5"
    "qv2dYifGnI_ipYV0HXOZ__1OoaoRG7_ZLdqq-sQ8pot8ortgCGB-E57mBPRXCNnpU_p"
    "nYx2mH-8Qk68hMbqlyc"
)

_cd_token = {"val": None, "ts": 0}
_cd_lock = threading.Lock()


def _cd_mint():
    h = {
        'User-Agent': UA,
        'Accept': '*/*',
        'Origin': 'https://www.cardekho.com',
        'Referer': 'https://www.cardekho.com/',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type,secret',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        r = requests.options(CD_BASE, headers=h, timeout=15)
        sc = r.headers.get('set-cookie', '') or ''
        m = re.search(r'Authorization=(?:Bearer%20|Bearer\+|Bearer )([A-Za-z0-9_\-\.]+)', sc)
        if m:
            return m.group(1)
    except Exception:
        pass
    return CD_FALLBACK


def _cd_ensure():
    with _cd_lock:
        if not _cd_token["val"] or (time.time() - _cd_token["ts"] > 3600):
            _cd_token["val"] = _cd_mint()
            _cd_token["ts"] = time.time()
        return _cd_token["val"]


def api_7(rc):
    tok = _cd_ensure()
    params = {
        'cityId': "",
        'connectoid': "ffe5a91d-4f11-2e07-5780-5eae91f5646a",
        'sessionid': "f7aee590555d1ffa110fa28bf8778190",
        'lang_code': "en",
        'regionId': "0",
        'regNo': rc,
        'source': "ucr_wap",
    }
    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
        'authorization': f"Bearer {tok}",
        'source': 'ucr_wap',
        'origin': 'https://www.cardekho.com',
        'referer': 'https://www.cardekho.com/',
        'accept-language': 'en-US,en;q=0.9',
    }
    try:
        r = requests.get(CD_LISTING, params=params, headers=headers, timeout=25)
        if r.status_code in (401, 403):
            with _cd_lock:
                _cd_token["val"] = None
            tok = _cd_ensure()
            headers['authorization'] = f"Bearer {tok}"
            r = requests.get(CD_LISTING, params=params, headers=headers, timeout=25)
        return _try_json(r)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# UTILS
# ============================================================
def _try_json(r):
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:500], "status": r.status_code}


def _norm_rc(rc):
    return re.sub(r'[^A-Z0-9]', '', (rc or "").upper())


# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "server": "Unified Vehicle API",
        "routes": {
            "all_in_one": "/adv?rc=MH02FZ0555",
            "api1": "/api1?rc=MH02FZ0555",
            "api2": "/api2?rc=MH02FZ0555",
            "api3": "/api3?rc=MH02FZ0555",
            "api4": "/api4?rc=MH02FZ0555",
            "api5": "/api5?rc=MH02FZ0555",
            "api6": "/api6?rc=MH02FZ0555",
            "api7": "/api7?rc=MH02FZ0555",
        },
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now(timezone.utc).isoformat()})


def _single(fn, rc):
    rc = _norm_rc(rc)
    if len(rc) < 8:
        return jsonify({"error": "Invalid RC"}), 400
    return jsonify(fn(rc))


@app.route("/api1")
def r_api1(): return _single(api_1, request.args.get("rc", ""))


@app.route("/api2")
def r_api2(): return _single(api_2, request.args.get("rc", ""))


@app.route("/api3")
def r_api3(): return _single(api_3, request.args.get("rc", ""))


@app.route("/api4")
def r_api4(): return _single(api_4, request.args.get("rc", ""))


@app.route("/api5")
def r_api5(): return _single(api_5, request.args.get("rc", ""))


@app.route("/api6")
def r_api6(): return _single(api_6, request.args.get("rc", ""))


@app.route("/api7")
def r_api7(): return _single(api_7, request.args.get("rc", ""))


# ---------- ADV: all in one ----------
def _run_all(rc):
    rc = _norm_rc(rc)
    if len(rc) < 8:
        return jsonify({"error": "Invalid RC. Use ?rc=MH02FZ0555"}), 400

    apis = {
        "api1": api_1,
        "api2": api_2,
        "api3": api_3,
        "api4": api_4,
        "api5": api_5,
        "api6": api_6,
        "api7": api_7,
    }

    results = {}
    with ThreadPoolExecutor(max_workers=7) as ex:
        futs = {ex.submit(fn, rc): name for name, fn in apis.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result(timeout=45)
            except Exception as e:
                results[name] = {"error": str(e)}

    return jsonify({
        "rc": rc,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_apis": len(apis),
        "results": results,
    })


@app.route("/adv")
def r_adv():
    return _run_all(request.args.get("rc", ""))


@app.route("/adv/<rc>")
def r_adv_path(rc):
    return _run_all(rc)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  🚀 Unified Vehicle API Server")
    print("=" * 60)
    print(f"  Server:  http://0.0.0.0:{port}")
    print(f"  All:     http://0.0.0.0:{port}/adv?rc=MH02FZ0555")
    for i in range(1, 8):
        print(f"  API{i}:    http://0.0.0.0:{port}/api{i}?rc=MH02FZ0555")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
