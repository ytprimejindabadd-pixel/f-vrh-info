import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------- CONFIG ----------
NXCAR_BASE_URL = "https://api.nxcar.in/vehicle_details"

AUTH_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJ1c2VyX2lkIjo3ODc4NiwidXNlcm5hbWUiOiI5NjEyMDU3NDU1Iiwicm9sZV9pZCI6IjEiLCJ0b2tlbl92ZXJzaW9uIjoiMSIsIkFQSV9USU1FIjoxNzkwODY0NzUxfQ."
    "qAUgkmfMXrcp1N863xVhI_u50V040Qk7AnPhIUHXbWM"
)

DEFAULT_CHECKSUM = "27ca4c231bb8b41514fb08d5a413862b"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua-platform": '"Android"',
    "authorization": AUTH_TOKEN,
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


# ---------- CORE HANDLER ----------
def fetch_vehicle(vehicle_number, checksum=None, backend="yes"):
    checksum = checksum or DEFAULT_CHECKSUM
    url = (
        f"{NXCAR_BASE_URL}"
        f"?vehicle_number={vehicle_number}"
        f"&backend={backend}"
        f"&checksum={checksum}"
    )

    resp = requests.get(url, headers=HEADERS, timeout=30)
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    return resp.status_code, data


# ---------- ROUTES ----------
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "service": "Nxcar Vehicle Details API",
        "usage": [
            "/rc=MH02FZ0555",
            "/vehicle_details?vehicle_number=MH02FZ0555",
        ],
    })


@app.route("/rc=<vehicle_number>", methods=["GET"])
def rc_lookup(vehicle_number):
    checksum = request.args.get("checksum")
    backend = request.args.get("backend", "yes")

    try:
        status, data = fetch_vehicle(vehicle_number, checksum, backend)
        return jsonify(data), status
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Failed to fetch vehicle details",
            "message": str(e),
        }), 500


@app.route("/vehicle_details", methods=["GET"])
def vehicle_details():
    vehicle_number = request.args.get("vehicle_number")
    if not vehicle_number:
        return jsonify({"error": "vehicle_number query param is required"}), 400

    checksum = request.args.get("checksum")
    backend = request.args.get("backend", "yes")

    try:
        status, data = fetch_vehicle(vehicle_number, checksum, backend)
        return jsonify(data), status
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Failed to fetch vehicle details",
            "message": str(e),
        }), 500


# ---------- START ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
