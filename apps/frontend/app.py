import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")


@app.route("/")
def index():
    try:
        r = requests.get(f"{BACKEND_URL}/", timeout=3)
        backend_data = r.json()
    except Exception as exc:  # noqa: BLE001
        backend_data = {"error": str(exc)}
    return jsonify({"frontend": "ok", "backend_response": backend_data})


@app.route("/healthz")
def healthz():
    return {"status": "alive"}


@app.route("/readyz")
def readyz():
    return {"status": "ready"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
