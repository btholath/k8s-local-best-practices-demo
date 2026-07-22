import os
import time
import random

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

app = FastAPI(title="demo-backend")

START_TIME = time.time()
APP_ENV = os.environ.get("APP_ENV", "dev")
GREETING = os.environ.get("GREETING", "Hello from backend")

# simple in-memory counters, exposed as Prometheus-style text so HPA custom
# metrics / ServiceMonitor scraping has something real to look at
REQUEST_COUNT = 0


@app.get("/")
def root():
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    return {"message": GREETING, "env": APP_ENV, "requests_served": REQUEST_COUNT}


@app.get("/healthz")
def healthz():
    """Liveness probe target: is the process alive at all."""
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    """Readiness probe target: is the app ready to serve traffic.
    Simulates occasional not-ready state right after boot."""
    uptime = time.time() - START_TIME
    if uptime < 5:
        return JSONResponse(status_code=503, content={"status": "warming up"})
    return {"status": "ready", "uptime_seconds": round(uptime, 1)}


@app.get("/metrics")
def metrics():
    """Minimal Prometheus text-format exposition for the demo."""
    cpu_load = round(random.uniform(0.1, 0.9), 2)
    body = (
        f"# HELP demo_requests_total Total requests served\n"
        f"# TYPE demo_requests_total counter\n"
        f"demo_requests_total {REQUEST_COUNT}\n"
        f"# HELP demo_simulated_load Simulated load gauge for HPA custom metric demo\n"
        f"# TYPE demo_simulated_load gauge\n"
        f"demo_simulated_load {cpu_load}\n"
    )
    return Response(content=body, media_type="text/plain")


@app.get("/version")
def version():
    return {"version": os.environ.get("APP_VERSION", "v1")}
