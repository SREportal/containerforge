"""
SidecarGenerator: Creates a standalone FastAPI sidecar watchdog container.
The sidecar monitors the main app, auto-restarts it if health fails,
aggregates metrics, and exposes Prometheus-compatible /metrics.
"""

from pathlib import Path

SIDECAR_APP = '''#!/usr/bin/env python3
"""
ContainerForge Sidecar - Container Watchdog & Metrics Aggregator
Monitors the target container, auto-restarts on failure, exposes metrics.
"""

import asyncio
import time
import os
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import httpx
import docker
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn

# ─── Config ──────────────────────────────────────────────────────────────────
TARGET_URL = os.environ.get("TARGET_URL", "http://app:8000")
WATCH_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "10"))
FAILURE_THRESHOLD = int(os.environ.get("FAILURE_THRESHOLD", "3"))
RESTART_ENABLED = os.environ.get("RESTART_ENABLED", "true").lower() == "true"
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "app")
SIDECAR_PORT = int(os.environ.get("SIDECAR_PORT", "9090"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # Optional alert webhook
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("containerforge.sidecar")

# ─── State ────────────────────────────────────────────────────────────────────
class WatchState:
    def __init__(self):
        self.start_time = time.time()
        self.consecutive_failures = 0
        self.total_checks = 0
        self.total_failures = 0
        self.total_restarts = 0
        self.last_check_time: Optional[float] = None
        self.last_status = "unknown"
        self.last_error: Optional[str] = None
        self.history: deque = deque(maxlen=100)
        self.last_telemetry: dict = {}
        self.restart_history: list = []

state = WatchState()

# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="ContainerForge Sidecar",
    description="Watchdog & metrics aggregator for containerized applications",
    version="1.0.0",
    docs_url="/sidecar/docs",
    redoc_url=None,
)


# ─── Watchdog Loop ────────────────────────────────────────────────────────────
async def watchdog_loop():
    """Main watchdog coroutine. Runs continuously in background."""
    log.info(f"Sidecar watchdog started. Monitoring: {TARGET_URL}")
    log.info(f"Check interval: {WATCH_INTERVAL}s | Failure threshold: {FAILURE_THRESHOLD}")

    async with httpx.AsyncClient(timeout=8.0) as client:
        while True:
            await _check_target(client)
            await asyncio.sleep(WATCH_INTERVAL)


async def _check_target(client: httpx.AsyncClient):
    """Perform a single health check against the target."""
    state.total_checks += 1
    state.last_check_time = time.time()
    check_start = time.time()

    try:
        response = await client.get(f"{TARGET_URL}/health")
        latency_ms = (time.time() - check_start) * 1000

        if response.status_code == 200:
            state.consecutive_failures = 0
            state.last_status = "healthy"
            state.last_error = None
            health_data = response.json()
            state.history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "status": "healthy",
                "latency_ms": round(latency_ms, 1),
            })
            log.debug(f"Health check OK — {latency_ms:.0f}ms")

            # Also fetch telemetry
            try:
                t = await client.get(f"{TARGET_URL}/telemetry")
                if t.status_code == 200:
                    state.last_telemetry = t.json()
            except Exception:
                pass

        else:
            await _handle_failure(f"HTTP {response.status_code}", latency_ms)

    except httpx.ConnectError:
        await _handle_failure("Connection refused")
    except httpx.TimeoutException:
        await _handle_failure("Timeout")
    except Exception as e:
        await _handle_failure(str(e))


async def _handle_failure(reason: str, latency_ms: float = 0):
    """Handle a failed health check."""
    state.consecutive_failures += 1
    state.total_failures += 1
    state.last_status = "unhealthy"
    state.last_error = reason
    state.history.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": "unhealthy",
        "error": reason,
        "latency_ms": round(latency_ms, 1),
    })

    log.warning(
        f"Health check FAILED ({state.consecutive_failures}/{FAILURE_THRESHOLD}): {reason}"
    )

    # Send webhook alert if configured
    if WEBHOOK_URL and state.consecutive_failures == 1:
        await _send_alert(f"Container unhealthy: {reason}")

    # Auto-restart if threshold reached
    if RESTART_ENABLED and state.consecutive_failures >= FAILURE_THRESHOLD:
        log.error(f"Failure threshold reached! Attempting container restart...")
        await _restart_container()


async def _restart_container():
    """Attempt to restart the target container via Docker socket."""
    try:
        docker_client = docker.from_env()
        containers = docker_client.containers.list(filters={"name": CONTAINER_NAME})

        if not containers:
            log.error(f"Container '{CONTAINER_NAME}' not found for restart")
            return

        container = containers[0]
        container.restart(timeout=10)
        state.total_restarts += 1
        state.consecutive_failures = 0
        state.restart_history.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "container": CONTAINER_NAME,
            "reason": f"Health check failed {FAILURE_THRESHOLD}x consecutively",
        })
        log.info(f"Container '{CONTAINER_NAME}' restarted successfully")

        if WEBHOOK_URL:
            await _send_alert(f"Container '{CONTAINER_NAME}' was auto-restarted")

    except Exception as e:
        log.error(f"Restart failed: {e}")


async def _send_alert(message: str):
    """Send a webhook alert."""
    if not WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(WEBHOOK_URL, json={
                "text": f"[ContainerForge Sidecar] {message}",
                "container": CONTAINER_NAME,
                "time": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        log.warning(f"Webhook delivery failed: {e}")


# ─── API Endpoints ────────────────────────────────────────────────────────────
@app.get("/sidecar/status", summary="Sidecar + target container status")
async def sidecar_status():
    uptime = time.time() - state.start_time
    availability = (
        round((state.total_checks - state.total_failures) / state.total_checks * 100, 2)
        if state.total_checks > 0 else 100.0
    )
    return {
        "sidecar": {
            "status": "running",
            "uptime_seconds": round(uptime, 1),
            "version": "1.0.0",
        },
        "target": {
            "url": TARGET_URL,
            "status": state.last_status,
            "last_error": state.last_error,
            "consecutive_failures": state.consecutive_failures,
            "last_check": datetime.fromtimestamp(
                state.last_check_time, tz=timezone.utc
            ).isoformat() if state.last_check_time else None,
        },
        "stats": {
            "total_checks": state.total_checks,
            "total_failures": state.total_failures,
            "total_restarts": state.total_restarts,
            "availability_percent": availability,
        },
        "config": {
            "watch_interval_seconds": WATCH_INTERVAL,
            "failure_threshold": FAILURE_THRESHOLD,
            "restart_enabled": RESTART_ENABLED,
        },
    }


@app.get("/sidecar/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def prometheus_metrics():
    """Expose metrics in Prometheus text format."""
    uptime = time.time() - state.start_time
    availability = (
        (state.total_checks - state.total_failures) / state.total_checks * 100
        if state.total_checks > 0 else 100.0
    )

    # App metrics from last telemetry poll
    tel = state.last_telemetry

    lines = [
        "# HELP cf_target_up Whether the target container is healthy (1=up, 0=down)",
        "# TYPE cf_target_up gauge",
        f"cf_target_up{{container=\"{CONTAINER_NAME}\"}} {1 if state.last_status == 'healthy' else 0}",
        "",
        "# HELP cf_checks_total Total health checks performed",
        "# TYPE cf_checks_total counter",
        f"cf_checks_total{{container=\"{CONTAINER_NAME}\"}} {state.total_checks}",
        "",
        "# HELP cf_failures_total Total health check failures",
        "# TYPE cf_failures_total counter",
        f"cf_failures_total{{container=\"{CONTAINER_NAME}\"}} {state.total_failures}",
        "",
        "# HELP cf_restarts_total Total container restarts triggered",
        "# TYPE cf_restarts_total counter",
        f"cf_restarts_total{{container=\"{CONTAINER_NAME}\"}} {state.total_restarts}",
        "",
        "# HELP cf_availability_percent Target availability percentage",
        "# TYPE cf_availability_percent gauge",
        f"cf_availability_percent{{container=\"{CONTAINER_NAME}\"}} {round(availability, 2)}",
        "",
        "# HELP cf_sidecar_uptime_seconds Sidecar uptime in seconds",
        "# TYPE cf_sidecar_uptime_seconds gauge",
        f"cf_sidecar_uptime_seconds {round(uptime, 1)}",
        "",
    ]

    if tel:
        lines += [
            "# HELP cf_app_requests_total Application request count",
            "# TYPE cf_app_requests_total counter",
            f"cf_app_requests_total{{container=\"{CONTAINER_NAME}\"}} {tel.get('requests_total', 0)}",
            "",
            "# HELP cf_app_errors_total Application error count",
            "# TYPE cf_app_errors_total counter",
            f"cf_app_errors_total{{container=\"{CONTAINER_NAME}\"}} {tel.get('errors_total', 0)}",
            "",
            "# HELP cf_app_avg_latency_ms Application average request latency ms",
            "# TYPE cf_app_avg_latency_ms gauge",
            f"cf_app_avg_latency_ms{{container=\"{CONTAINER_NAME}\"}} {tel.get('avg_latency_ms', 0)}",
            "",
            "# HELP cf_app_memory_mb Application memory usage in MB",
            "# TYPE cf_app_memory_mb gauge",
            f"cf_app_memory_mb{{container=\"{CONTAINER_NAME}\"}} {tel.get('memory_mb', 0)}",
            "",
            "# HELP cf_app_cpu_percent Application CPU usage percent",
            "# TYPE cf_app_cpu_percent gauge",
            f"cf_app_cpu_percent{{container=\"{CONTAINER_NAME}\"}} {tel.get('cpu_percent', 0)}",
            "",
        ]

    return "\\n".join(lines)


@app.get("/sidecar/history", summary="Last 100 health check events")
async def check_history():
    return {
        "count": len(state.history),
        "events": list(state.history),
    }


@app.get("/sidecar/restarts", summary="Restart history")
async def restart_history():
    return {
        "total": state.total_restarts,
        "history": state.restart_history,
    }


@app.post("/sidecar/restart", summary="Manually trigger container restart")
async def manual_restart():
    if not RESTART_ENABLED:
        raise HTTPException(status_code=403, detail="Restart is disabled (RESTART_ENABLED=false)")
    await _restart_container()
    return {"message": f"Restart triggered for '{CONTAINER_NAME}'"}


@app.get("/health", summary="Sidecar own health check")
async def health():
    return {"status": "healthy", "service": "containerforge-sidecar"}


# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    asyncio.create_task(watchdog_loop())
    log.info(f"ContainerForge Sidecar v1.0.0 running on port {SIDECAR_PORT}")


if __name__ == "__main__":
    uvicorn.run(
        "sidecar:app",
        host="0.0.0.0",
        port=SIDECAR_PORT,
        log_level=LOG_LEVEL.lower(),
    )
'''

SIDECAR_DOCKERFILE = """# ContainerForge Sidecar Dockerfile
FROM python:3.11-slim

RUN groupadd --gid 1001 sidecar && \\
    useradd --uid 1001 --gid sidecar --shell /bin/bash --create-home sidecar

WORKDIR /sidecar

RUN apt-get update && apt-get install -y --no-install-recommends curl && \\
    rm -rf /var/lib/apt/lists/*

COPY sidecar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sidecar/sidecar.py .

USER sidecar

EXPOSE {sidecar_port}

HEALTHCHECK --interval=20s --timeout=5s CMD curl -sf http://localhost:{sidecar_port}/health || exit 1

CMD ["python", "sidecar.py"]
"""

SIDECAR_REQUIREMENTS = """fastapi==0.115.6
uvicorn[standard]==0.32.1
httpx==0.28.1
docker==7.1.0
psutil==6.1.1
"""


class SidecarGenerator:
    def __init__(self, app_path: Path, app_info: dict, sidecar_port: int = 9090):
        self.app_path = Path(app_path)
        self.info = app_info
        self.sidecar_port = sidecar_port

    def generate(self) -> Path:
        sidecar_dir = self.app_path / "sidecar"
        sidecar_dir.mkdir(exist_ok=True)

        # Write sidecar app
        sidecar_py = sidecar_dir / "sidecar.py"
        sidecar_py.write_text(SIDECAR_APP)

        # Write requirements
        req = sidecar_dir / "requirements.txt"
        req.write_text(SIDECAR_REQUIREMENTS)

        # Write Dockerfile.sidecar at app root
        sidecar_dockerfile = self.app_path / "Dockerfile.sidecar"
        sidecar_dockerfile.write_text(SIDECAR_DOCKERFILE.format(sidecar_port=self.sidecar_port))

        return sidecar_dir
