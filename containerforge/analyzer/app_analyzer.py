"""
AppAnalyzer: Detects Python app framework, entry point, port, and start command.
Supports: Flask, FastAPI, Django, plain Python WSGI/ASGI apps.
"""

import re
import ast
from pathlib import Path
from typing import Optional


FLASK_PATTERNS = ["flask", "Flask", "from flask"]
FASTAPI_PATTERNS = ["fastapi", "FastAPI", "from fastapi"]
DJANGO_PATTERNS = ["django", "Django", "from django"]

PORT_PATTERNS = [
    r'port\s*=\s*(\d{4,5})',
    r'\.run\(.*port\s*=\s*(\d{4,5})',
    r'PORT["\s]*[=:]\s*["\']?(\d{4,5})',
    r'uvicorn\.run\(.*port\s*=\s*(\d{4,5})',
    r'--port[=\s]+(\d{4,5})',
]

DEFAULT_PORTS = {
    "flask": 5000,
    "fastapi": 8000,
    "django": 8000,
    "unknown": 8000,
}


class AppAnalyzer:
    def __init__(self, app_path: Path):
        self.app_path = Path(app_path)

    def analyze(self) -> dict:
        framework = self._detect_framework()
        entry_point = self._detect_entry_point(framework)
        port = self._detect_port(entry_point) or DEFAULT_PORTS.get(framework, 8000)
        deps_file = self._detect_deps_file()
        start_command = self._build_start_command(framework, entry_point, port)
        python_version = self._detect_python_version()

        return {
            "language": "Python",
            "framework": framework.capitalize() if framework else "Unknown",
            "framework_key": framework,
            "entry_point": str(entry_point.relative_to(self.app_path)) if entry_point else "main.py",
            "entry_point_abs": str(entry_point) if entry_point else None,
            "port": port,
            "start_command": start_command,
            "deps_file": deps_file,
            "python_version": python_version,
            "has_env_file": (self.app_path / ".env").exists() or (self.app_path / ".env.example").exists(),
            "app_object": self._detect_app_object(entry_point),
            "module_name": self._path_to_module(entry_point),
        }

    # ─── Framework Detection ─────────────────────────────────────────────────

    def _detect_framework(self) -> str:
        py_files = list(self.app_path.rglob("*.py"))

        # Check requirements.txt / pyproject.toml first (fastest)
        deps_text = self._read_deps_text()
        if deps_text:
            if "fastapi" in deps_text.lower():
                return "fastapi"
            if "flask" in deps_text.lower():
                return "flask"
            if "django" in deps_text.lower():
                return "django"

        # Scan source files
        for py_file in py_files[:30]:  # limit scan
            try:
                text = py_file.read_text(errors="ignore")
                if any(p in text for p in FASTAPI_PATTERNS):
                    return "fastapi"
                if any(p in text for p in FLASK_PATTERNS):
                    return "flask"
                if any(p in text for p in DJANGO_PATTERNS):
                    return "django"
            except Exception:
                pass

        return "unknown"

    # ─── Entry Point Detection ────────────────────────────────────────────────

    def _detect_entry_point(self, framework: str) -> Optional[Path]:
        # Common entry point names in priority order
        candidates = [
            "main.py", "app.py", "server.py", "run.py",
            "application.py", "api.py", "wsgi.py", "asgi.py",
            "manage.py",  # Django
        ]

        for name in candidates:
            candidate = self.app_path / name
            if candidate.exists():
                return candidate

        # Search subdirectories
        for name in candidates:
            results = list(self.app_path.rglob(name))
            if results:
                return results[0]

        # Fall back to first .py file with app/main definition
        for py_file in sorted(self.app_path.glob("*.py")):
            try:
                text = py_file.read_text(errors="ignore")
                if "app = " in text or "application = " in text or "__main__" in text:
                    return py_file
            except Exception:
                pass

        return None

    # ─── Port Detection ───────────────────────────────────────────────────────

    def _detect_port(self, entry_point: Optional[Path]) -> Optional[int]:
        # Check .env file
        for env_file in [".env", ".env.example", ".env.sample"]:
            env_path = self.app_path / env_file
            if env_path.exists():
                try:
                    text = env_path.read_text(errors="ignore")
                    for pat in PORT_PATTERNS:
                        m = re.search(pat, text, re.IGNORECASE)
                        if m:
                            return int(m.group(1))
                except Exception:
                    pass

        # Check entry point
        if entry_point and entry_point.exists():
            try:
                text = entry_point.read_text(errors="ignore")
                for pat in PORT_PATTERNS:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        return int(m.group(1))
            except Exception:
                pass

        # Check all Python files
        for py_file in list(self.app_path.glob("*.py"))[:10]:
            try:
                text = py_file.read_text(errors="ignore")
                for pat in PORT_PATTERNS:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        return int(m.group(1))
            except Exception:
                pass

        return None

    # ─── Start Command ────────────────────────────────────────────────────────

    def _build_start_command(self, framework: str, entry_point: Optional[Path], port: int) -> str:
        module = self._path_to_module(entry_point) if entry_point else "main"
        app_obj = self._detect_app_object(entry_point)

        if framework == "fastapi":
            return f"uvicorn {module}:{app_obj} --host 0.0.0.0 --port {port}"
        elif framework == "flask":
            return f"gunicorn {module}:{app_obj} --bind 0.0.0.0:{port} --workers 2"
        elif framework == "django":
            return f"gunicorn {module}.wsgi:application --bind 0.0.0.0:{port} --workers 2"
        else:
            if entry_point:
                rel = entry_point.relative_to(self.app_path)
                return f"python {rel}"
            return "python main.py"

    def _detect_app_object(self, entry_point: Optional[Path]) -> str:
        if not entry_point or not entry_point.exists():
            return "app"
        try:
            text = entry_point.read_text(errors="ignore")
            # Look for app = Flask(...) or app = FastAPI() etc.
            for pattern in [r'^(app|application|api)\s*=\s*(?:Flask|FastAPI|Starlette)', r'^(app)\s*=']:
                m = re.search(pattern, text, re.MULTILINE)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return "app"

    def _path_to_module(self, path: Optional[Path]) -> str:
        if not path:
            return "main"
        try:
            rel = path.relative_to(self.app_path)
            return str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
        except Exception:
            return path.stem

    # ─── Dependencies ─────────────────────────────────────────────────────────

    def _detect_deps_file(self) -> Optional[str]:
        for f in ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg"]:
            if (self.app_path / f).exists():
                return f
        return None

    def _read_deps_text(self) -> str:
        for f in ["requirements.txt", "pyproject.toml", "Pipfile"]:
            p = self.app_path / f
            if p.exists():
                try:
                    return p.read_text(errors="ignore").lower()
                except Exception:
                    pass
        return ""

    def _detect_python_version(self) -> str:
        # Check .python-version
        pv = self.app_path / ".python-version"
        if pv.exists():
            v = pv.read_text().strip()
            if v:
                return v

        # Check pyproject.toml
        pp = self.app_path / "pyproject.toml"
        if pp.exists():
            text = pp.read_text(errors="ignore")
            m = re.search(r'python_requires\s*=\s*["\']>=?\s*([\d.]+)', text)
            if m:
                return m.group(1)

        return "3.11"
