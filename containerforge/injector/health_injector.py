"""
HealthInjector: Injects /health and /telemetry endpoints into Flask/FastAPI apps.
Non-destructive: adds a separate _cf_health.py file and imports it.
"""

import re
from pathlib import Path

FLASK_HEALTH_CODE = '''
# ── ContainerForge: Health & Telemetry ──────────────────────────────────────
import time as _cf_time
import os as _cf_os
import threading as _cf_threading
from flask import Blueprint as _CFBlueprint, jsonify as _cfjsonify

_cf_start_time = _cf_time.time()
_cf_request_count = 0
_cf_error_count = 0
_cf_total_latency = 0.0
_cf_lock = _cf_threading.Lock()

_cf_bp = _CFBlueprint("_cf_health", __name__)


@_cf_bp.route("/health")
def _cf_health():
    import psutil as _psutil
    uptime = _cf_time.time() - _cf_start_time
    mem = _psutil.virtual_memory()
    return _cfjsonify({
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "memory": {
            "used_mb": round(mem.used / 1024 / 1024, 1),
            "total_mb": round(mem.total / 1024 / 1024, 1),
            "percent": mem.percent,
        },
        "pid": _cf_os.getpid(),
        "checks": {"app": "ok"},
    }), 200


@_cf_bp.route("/telemetry")
def _cf_telemetry():
    import psutil as _psutil
    uptime = _cf_time.time() - _cf_start_time
    with _cf_lock:
        req = _cf_request_count
        err = _cf_error_count
        avg_lat = (_cf_total_latency / req) if req > 0 else 0
    proc = _psutil.Process(_cf_os.getpid())
    return _cfjsonify({
        "requests_total": req,
        "errors_total": err,
        "error_rate": round((err / req * 100) if req > 0 else 0, 2),
        "avg_latency_ms": round(avg_lat * 1000, 2),
        "uptime_seconds": round(uptime, 2),
        "cpu_percent": proc.cpu_percent(interval=0.1),
        "memory_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
    }), 200


def _cf_register(app):
    """Call this in your Flask app after creating it: _cf_register(app)"""
    app.register_blueprint(_cf_bp)

    @app.before_request
    def _cf_before():
        import flask
        flask.g._cf_start = _cf_time.time()

    @app.after_request
    def _cf_after(response):
        import flask
        global _cf_request_count, _cf_error_count, _cf_total_latency
        elapsed = _cf_time.time() - getattr(flask.g, "_cf_start", _cf_time.time())
        with _cf_lock:
            _cf_request_count += 1
            if response.status_code >= 400:
                _cf_error_count += 1
            _cf_total_latency += elapsed
        return response

# ── End ContainerForge ───────────────────────────────────────────────────────
'''

FASTAPI_HEALTH_CODE = '''
# ── ContainerForge: Health & Telemetry ──────────────────────────────────────
import time as _cf_time
import os as _cf_os
import asyncio as _cf_asyncio
from fastapi import APIRouter as _CFRouter, Request as _CFRequest, Response as _CFResponse
from fastapi.responses import JSONResponse as _CFJSONResponse

_cf_start_time = _cf_time.time()
_cf_request_count = 0
_cf_error_count = 0
_cf_total_latency = 0.0

_cf_router = _CFRouter(tags=["_containerforge"])


@_cf_router.get("/health")
async def _cf_health():
    try:
        import psutil as _psutil
        mem = _psutil.virtual_memory()
        mem_info = {
            "used_mb": round(mem.used / 1024 / 1024, 1),
            "total_mb": round(mem.total / 1024 / 1024, 1),
            "percent": mem.percent,
        }
    except ImportError:
        mem_info = {}
    return {
        "status": "healthy",
        "uptime_seconds": round(_cf_time.time() - _cf_start_time, 2),
        "memory": mem_info,
        "pid": _cf_os.getpid(),
        "checks": {"app": "ok"},
    }


@_cf_router.get("/telemetry")
async def _cf_telemetry():
    uptime = _cf_time.time() - _cf_start_time
    req = _cf_request_count
    err = _cf_error_count
    avg_lat = (_cf_total_latency / req) if req > 0 else 0
    try:
        import psutil as _psutil
        proc = _psutil.Process(_cf_os.getpid())
        cpu = proc.cpu_percent(interval=0.1)
        mem_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
    except ImportError:
        cpu, mem_mb = 0, 0
    return {
        "requests_total": req,
        "errors_total": err,
        "error_rate": round((err / req * 100) if req > 0 else 0, 2),
        "avg_latency_ms": round(avg_lat * 1000, 2),
        "uptime_seconds": round(uptime, 2),
        "cpu_percent": cpu,
        "memory_mb": mem_mb,
    }


async def _cf_middleware(request: _CFRequest, call_next):
    global _cf_request_count, _cf_error_count, _cf_total_latency
    start = _cf_time.time()
    response = await call_next(request)
    elapsed = _cf_time.time() - start
    _cf_request_count += 1
    if response.status_code >= 400:
        _cf_error_count += 1
    _cf_total_latency += elapsed
    return response


def _cf_register(app):
    """Call this after creating your FastAPI app: _cf_register(app)"""
    app.include_router(_cf_router)
    app.middleware("http")(_cf_middleware)

# ── End ContainerForge ───────────────────────────────────────────────────────
'''

STANDALONE_HEALTH_SERVER = '''#!/usr/bin/env python3
"""
ContainerForge standalone health server.
Runs on port {health_port} when the app doesn\'t support direct injection.
"""
import time, os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

START_TIME = time.time()

class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        if self.path == "/health":
            data = {{
                "status": "healthy",
                "uptime_seconds": round(time.time() - START_TIME, 2),
                "pid": os.getpid(),
                "checks": {{"app": "ok"}},
            }}
            self._respond(200, data)
        elif self.path == "/telemetry":
            data = {{
                "uptime_seconds": round(time.time() - START_TIME, 2),
                "pid": os.getpid(),
                "note": "Full telemetry requires direct injection",
            }}
            self._respond(200, data)
        else:
            self._respond(404, {{"error": "not found"}})

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def run():
    port = int(os.environ.get("HEALTH_PORT", {health_port}))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"ContainerForge health server on :{{port}}")
    server.serve_forever()


if __name__ == "__main__":
    run()
'''


class HealthInjector:
    def __init__(self, app_path: Path, app_info: dict):
        self.app_path = Path(app_path)
        self.info = app_info

    def inject(self) -> dict:
        framework = self.info.get("framework_key", "unknown").lower()
        entry_abs = self.info.get("entry_point_abs")

        if not entry_abs:
            return self._write_standalone()

        entry_path = Path(entry_abs)
        if not entry_path.exists():
            return self._write_standalone()

        if framework == "flask":
            return self._inject_flask(entry_path)
        elif framework == "fastapi":
            return self._inject_fastapi(entry_path)
        else:
            return self._write_standalone()

    def _inject_flask(self, entry_path: Path) -> dict:
        text = entry_path.read_text(errors="ignore")

        # Already injected?
        if "_cf_register" in text and "ContainerForge injection" in text:
            return {"success": True, "file": entry_path.name, "message": "Already injected"}

        # Write the health module
        health_file = self.app_path / "_cf_health.py"
        health_file.write_text(FLASK_HEALTH_CODE)

        # Find where the Flask app is created and inject after it
        app_obj = self.info.get("app_object", "app")
        inject_line = f"\n# ContainerForge injection\nfrom _cf_health import _cf_register as _cf_reg\n_cf_reg({app_obj})\n"

        # Try to inject after the app = Flask(...) line
        pattern = rf'({re.escape(app_obj)}\s*=\s*Flask\([^)]*\))'
        new_text, n = re.subn(pattern, r'\1' + inject_line, text, count=1, flags=re.DOTALL)

        if n == 0:
            # Fallback: append at end
            new_text = text + "\n" + inject_line

        entry_path.write_text(new_text)
        return {"success": True, "file": entry_path.name}

    def _inject_fastapi(self, entry_path: Path) -> dict:
        text = entry_path.read_text(errors="ignore")

        if "_cf_register" in text and "ContainerForge injection" in text:
            return {"success": True, "file": entry_path.name, "message": "Already injected"}

        health_file = self.app_path / "_cf_health.py"
        health_file.write_text(FASTAPI_HEALTH_CODE)

        app_obj = self.info.get("app_object", "app")
        inject_line = f"\n# ContainerForge injection\nfrom _cf_health import _cf_register as _cf_reg\n_cf_reg({app_obj})\n"

        pattern = rf'({re.escape(app_obj)}\s*=\s*FastAPI\([^)]*\))'
        new_text, n = re.subn(pattern, r'\1' + inject_line, text, count=1)

        if n == 0:
            new_text = text + "\n" + inject_line

        entry_path.write_text(new_text)
        return {"success": True, "file": entry_path.name}

    def _write_standalone(self, health_port: int = 8099) -> dict:
        standalone = self.app_path / "_cf_health_server.py"
        standalone.write_text(STANDALONE_HEALTH_SERVER.format(health_port=health_port))
        return {
            "success": False,
            "message": f"Could not inject directly — standalone health server written to {standalone.name}",
        }
