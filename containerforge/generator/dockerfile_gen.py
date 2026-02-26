"""
DockerfileGenerator: Generates a multi-stage, production-hardened Dockerfile
for Python Flask/FastAPI applications.
"""

from pathlib import Path


DOCKERFILE_TEMPLATE = """# ──────────────────────────────────────────────────────
# ContainerForge - Auto-generated Dockerfile
# Framework: {framework}  |  Port: {port}
# ──────────────────────────────────────────────────────

# ── Stage 1: Build dependencies ──────────────────────
FROM python:{python_version}-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    g++ \\
    libffi-dev \\
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies (layer-cached)
{deps_copy}
RUN pip install --upgrade pip && \\
    pip install --prefix=/install --no-cache-dir {deps_install_cmd}

# ── Stage 2: Runtime ─────────────────────────────────
FROM python:{python_version}-slim AS runtime

# Security: non-root user
RUN groupadd --gid 1001 appgroup && \\
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Runtime deps only (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Expose app port
EXPOSE {port}

# Built-in Docker health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \\
    CMD curl -sf http://localhost:{port}/health || exit 1

# Start command
CMD {cmd_json}
"""

DOCKERFILE_NO_DEPS = """# ──────────────────────────────────────────────────────
# ContainerForge - Auto-generated Dockerfile  
# Framework: {framework}  |  Port: {port}
# ──────────────────────────────────────────────────────

FROM python:{python_version}-slim

# Security: non-root user
RUN groupadd --gid 1001 appgroup && \\
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Install runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Copy app
COPY --chown=appuser:appgroup . .

# Install any deps if present
RUN pip install --upgrade pip --no-cache-dir {extra_install}

USER appuser

EXPOSE {port}

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \\
    CMD curl -sf http://localhost:{port}/health || exit 1

CMD {cmd_json}
"""

DOCKERIGNORE = """# ContainerForge - .dockerignore
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.eggs/
.tox/
.coverage
htmlcov/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Virtual environments
venv/
.venv/
env/
.env
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Git
.git/
.gitignore
.gitattributes

# Docker files (don't copy into itself)
Dockerfile*
docker-compose*
.dockerignore

# ContainerForge artifacts
sidecar/

# OS
.DS_Store
Thumbs.db
*.log
"""


class DockerfileGenerator:
    def __init__(self, app_path: Path, app_info: dict):
        self.app_path = Path(app_path)
        self.info = app_info

    def generate(self) -> Path:
        dockerfile_path = self.app_path / "Dockerfile"
        dockerignore_path = self.app_path / ".dockerignore"

        content = self._build_dockerfile()
        dockerfile_path.write_text(content)

        # Only write .dockerignore if it doesn't exist
        if not dockerignore_path.exists():
            dockerignore_path.write_text(DOCKERIGNORE)

        return dockerfile_path

    def _build_dockerfile(self) -> str:
        framework = self.info.get("framework", "Unknown")
        port = self.info.get("port", 8000)
        python_version = self.info.get("python_version", "3.11")
        start_command = self.info.get("start_command", "python main.py")
        deps_file = self.info.get("deps_file")

        # Convert start command to JSON array for CMD
        cmd_json = self._command_to_json(start_command)

        # Make sure psutil is always included (needed for health endpoints)
        extra_packages = ["psutil"]

        if deps_file:
            # Multi-stage build with deps
            if deps_file == "requirements.txt":
                deps_copy = "COPY requirements.txt ."
                deps_install_cmd = "-r requirements.txt " + " ".join(extra_packages)
            elif deps_file == "pyproject.toml":
                deps_copy = "COPY pyproject.toml .\nCOPY . ."
                deps_install_cmd = ". " + " ".join(extra_packages)
            elif deps_file == "Pipfile":
                deps_copy = "COPY Pipfile Pipfile.lock* ."
                deps_install_cmd = "pipenv install --system --deploy " + " ".join(extra_packages)
            else:
                deps_copy = f"COPY {deps_file} ."
                deps_install_cmd = f"-r {deps_file} " + " ".join(extra_packages)

            return DOCKERFILE_TEMPLATE.format(
                framework=framework,
                port=port,
                python_version=python_version,
                deps_copy=deps_copy,
                deps_install_cmd=deps_install_cmd,
                cmd_json=cmd_json,
            )
        else:
            # Simple single-stage build
            extra_install = " ".join(extra_packages)
            return DOCKERFILE_NO_DEPS.format(
                framework=framework,
                port=port,
                python_version=python_version,
                extra_install=extra_install,
                cmd_json=cmd_json,
            )

    def _command_to_json(self, command: str) -> str:
        """Convert a shell command string to Docker CMD JSON array."""
        import shlex
        parts = shlex.split(command)
        quoted = ', '.join(f'"{p}"' for p in parts)
        return f"[{quoted}]"
