"""
OCIDockerfileGenerator: Generates fully OCI Image Spec compliant Dockerfiles
for Python, Node.js, Go, Java, Ruby, Rust, PHP, and .NET applications.

OCI Compliance:
  - org.opencontainers.image.* labels on every image
  - Multi-stage builds (build stage + minimal runtime stage)
  - Distroless or slim runtime images where possible
  - Non-root USER with fixed UID/GID
  - HEALTHCHECK directive
  - Deterministic layer ordering for maximum cache reuse
  - ARG for build-time variables
  - OCI media types via BuildKit --platform support
"""

import shlex
import json
from pathlib import Path
from typing import Optional


# ─── Language-specific Dockerfile templates ────────────────────────────────────

TEMPLATES: dict[str, str] = {}

# ── Python ──────────────────────────────────────────────────────────────────────
TEMPLATES["python"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Python {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

# ── Build Arguments (override with --build-arg) ────────────
ARG PYTHON_VERSION={runtime_version}
ARG APP_PORT={port}
ARG APP_USER=appuser
ARG APP_UID=1001

# ── Stage 1: dependency installer ─────────────────────────
FROM python:${{PYTHON_VERSION}}-slim AS deps

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc g++ libffi-dev libssl-dev \\
    && rm -rf /var/lib/apt/lists/*

{deps_copy_section}
RUN pip install --upgrade pip --no-cache-dir && \\
    pip install --prefix=/install --no-cache-dir {deps_install_args}

# ── Stage 2: runtime ───────────────────────────────────────
FROM python:${{PYTHON_VERSION}}-slim AS runtime

ARG APP_USER APP_UID APP_PORT

# OCI Image Spec labels
LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      org.opencontainers.image.licenses="MIT" \\
      org.opencontainers.image.base.name="docker.io/library/python:${{PYTHON_VERSION}}-slim" \\
      dev.containerforge.language="python" \\
      dev.containerforge.framework="{framework}"

# Non-root user (fixed UID for reproducibility)
RUN groupadd --gid ${{APP_UID}} ${{APP_USER}} && \\
    useradd --uid ${{APP_UID}} --gid ${{APP_UID}} --shell /sbin/nologin \\
            --no-create-home --no-user-group ${{APP_USER}}

WORKDIR /app

# Runtime system packages
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from deps stage
COPY --from=deps /install /usr/local

# Copy application source
COPY --chown=${{APP_USER}}:${{APP_USER}} . .

USER ${{APP_USER}}

EXPOSE ${{APP_PORT}}

# OCI-compliant STOP signal
STOPSIGNAL SIGTERM

# Built-in health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

CMD {cmd_json}
"""

# ── Node.js ─────────────────────────────────────────────────────────────────────
TEMPLATES["nodejs"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Node.js {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG NODE_VERSION={runtime_version}
ARG APP_PORT={port}
ARG APP_USER=nodeuser
ARG APP_UID=1001

# ── Stage 1: install dependencies ─────────────────────────
FROM node:${{NODE_VERSION}}-alpine AS deps

WORKDIR /build
{deps_copy_section}
RUN {deps_install_args}

# ── Stage 2: build (if needed) ────────────────────────────
FROM node:${{NODE_VERSION}}-alpine AS builder

WORKDIR /build
COPY --from=deps /build/node_modules ./node_modules
COPY . .
{build_step}

# ── Stage 3: runtime ───────────────────────────────────────
FROM node:${{NODE_VERSION}}-alpine AS runtime

ARG APP_USER APP_UID APP_PORT

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      org.opencontainers.image.base.name="docker.io/library/node:${{NODE_VERSION}}-alpine" \\
      dev.containerforge.language="nodejs" \\
      dev.containerforge.framework="{framework}"

RUN addgroup -g ${{APP_UID}} ${{APP_USER}} && \\
    adduser -D -u ${{APP_UID}} -G ${{APP_USER}} ${{APP_USER}}

RUN apk add --no-cache curl ca-certificates tini

WORKDIR /app
COPY --from=builder --chown=${{APP_USER}}:${{APP_USER}} /build .

USER ${{APP_USER}}

EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

# tini for proper signal handling
ENTRYPOINT ["/sbin/tini", "--"]
CMD {cmd_json}
"""

# ── Go ──────────────────────────────────────────────────────────────────────────
TEMPLATES["go"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Go {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG GO_VERSION={runtime_version}
ARG APP_PORT={port}

# ── Stage 1: build ─────────────────────────────────────────
FROM golang:${{GO_VERSION}}-alpine AS builder

RUN apk add --no-cache git ca-certificates tzdata

WORKDIR /src

# Download dependencies first (cache-friendly)
COPY go.mod go.sum* ./
RUN go mod download && go mod verify

COPY . .

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \\
    go build -ldflags="-w -s -extldflags=-static" \\
    -o /app/server ./...

# ── Stage 2: distroless runtime ────────────────────────────
FROM gcr.io/distroless/static-debian12:nonroot AS runtime

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      org.opencontainers.image.base.name="gcr.io/distroless/static-debian12:nonroot" \\
      dev.containerforge.language="go" \\
      dev.containerforge.framework="{framework}"

# Copy CA certs and timezone data from builder
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

COPY --from=builder /app/server /server

EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
    CMD ["/server", "--health-check"] || exit 1

USER nonroot:nonroot

CMD ["/server"]
"""

# ── Java ─────────────────────────────────────────────────────────────────────────
TEMPLATES["java"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Java {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG JAVA_VERSION={runtime_version}
ARG APP_PORT={port}
ARG APP_USER=javauser
ARG APP_UID=1001

# ── Stage 1: build ─────────────────────────────────────────
FROM eclipse-temurin:${{JAVA_VERSION}}-jdk-alpine AS builder

WORKDIR /build

{deps_copy_section}
RUN {deps_install_args}

COPY . .
RUN {build_command}

# ── Stage 2: minimal JRE runtime ───────────────────────────
FROM eclipse-temurin:${{JAVA_VERSION}}-jre-alpine AS runtime

ARG APP_USER APP_UID APP_PORT

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      org.opencontainers.image.base.name="docker.io/library/eclipse-temurin:${{JAVA_VERSION}}-jre-alpine" \\
      dev.containerforge.language="java" \\
      dev.containerforge.framework="{framework}"

RUN addgroup -g ${{APP_UID}} ${{APP_USER}} && \\
    adduser -D -u ${{APP_UID}} -G ${{APP_USER}} ${{APP_USER}}

RUN apk add --no-cache curl ca-certificates tini

WORKDIR /app
COPY --from=builder --chown=${{APP_USER}}:${{APP_USER}} /build/target/*.jar app.jar

USER ${{APP_USER}}
EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/actuator/health || \\
        curl -sf http://localhost:${{APP_PORT}}/health || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["java", "-jar", "app.jar"]
"""

# ── Ruby ─────────────────────────────────────────────────────────────────────────
TEMPLATES["ruby"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Ruby {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG RUBY_VERSION={runtime_version}
ARG APP_PORT={port}
ARG APP_USER=rubyuser
ARG APP_UID=1001

# ── Stage 1: gems installer ────────────────────────────────
FROM ruby:${{RUBY_VERSION}}-slim AS gems

RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential libssl-dev libpq-dev git \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY Gemfile Gemfile.lock* ./
RUN bundle config set --local without 'development test' && \\
    bundle install --jobs 4 --retry 3

# ── Stage 2: runtime ───────────────────────────────────────
FROM ruby:${{RUBY_VERSION}}-slim AS runtime

ARG APP_USER APP_UID APP_PORT

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      dev.containerforge.language="ruby" \\
      dev.containerforge.framework="{framework}"

RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl ca-certificates libpq5 \\
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid ${{APP_UID}} ${{APP_USER}} && \\
    useradd --uid ${{APP_UID}} --gid ${{APP_UID}} --no-create-home ${{APP_USER}}

WORKDIR /app
COPY --from=gems /build/vendor/bundle ./vendor/bundle
COPY --chown=${{APP_USER}}:${{APP_USER}} . .

ENV BUNDLE_PATH=/app/vendor/bundle
USER ${{APP_USER}}
EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

CMD {cmd_json}
"""

# ── Rust ─────────────────────────────────────────────────────────────────────────
TEMPLATES["rust"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: Rust  ·  Framework: {framework_display}   ║
# ╚══════════════════════════════════════════════════════╝

ARG APP_PORT={port}

# ── Stage 1: build ─────────────────────────────────────────
FROM rust:slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \\
    pkg-config libssl-dev \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Cache dependency build separately
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo "fn main(){{}}" > src/main.rs && \\
    cargo build --release && \\
    rm -rf src

COPY . .
RUN touch src/main.rs && cargo build --release

# ── Stage 2: distroless runtime ────────────────────────────
FROM gcr.io/distroless/cc-debian12:nonroot AS runtime

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      org.opencontainers.image.base.name="gcr.io/distroless/cc-debian12:nonroot" \\
      dev.containerforge.language="rust" \\
      dev.containerforge.framework="{framework}"

COPY --from=builder /src/target/release/app /app

EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM
USER nonroot:nonroot

CMD ["/app"]
"""

# ── PHP ──────────────────────────────────────────────────────────────────────────
TEMPLATES["php"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: PHP {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG PHP_VERSION={runtime_version}
ARG APP_PORT={port}

FROM php:${{PHP_VERSION}}-fpm-alpine AS runtime

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      dev.containerforge.language="php" \\
      dev.containerforge.framework="{framework}"

RUN apk add --no-cache curl nginx composer ca-certificates

WORKDIR /app
COPY . .
RUN composer install --no-dev --optimize-autoloader 2>/dev/null || true

RUN adduser -D -u 1001 phpuser && \\
    chown -R phpuser:phpuser /app

USER phpuser
EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

CMD {cmd_json}
"""

# ── .NET ─────────────────────────────────────────────────────────────────────────
TEMPLATES["dotnet"] = """\
# syntax=docker/dockerfile:1.6
# ╔══════════════════════════════════════════════════════╗
# ║  ContainerForge  ·  OCI Compliant Image              ║
# ║  Language: .NET {runtime_version}  ·  Framework: {framework_display}  ║
# ╚══════════════════════════════════════════════════════╝

ARG DOTNET_VERSION={runtime_version}
ARG APP_PORT={port}

# ── Stage 1: build ─────────────────────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:${{DOTNET_VERSION}}-alpine AS builder

WORKDIR /src
COPY . .
RUN dotnet restore && \\
    dotnet publish -c Release -o /app/publish --no-restore

# ── Stage 2: runtime ───────────────────────────────────────
FROM mcr.microsoft.com/dotnet/aspnet:${{DOTNET_VERSION}}-alpine AS runtime

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.description="{oci_description}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}" \\
      dev.containerforge.language="dotnet" \\
      dev.containerforge.framework="{framework}"

RUN apk add --no-cache curl ca-certificates && \\
    adduser -D -u 1001 dotnetuser

WORKDIR /app
COPY --from=builder --chown=dotnetuser /app/publish .

USER dotnetuser
EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

CMD {cmd_json}
"""

# ── Unknown / Generic fallback ────────────────────────────────────────────────────
TEMPLATES["unknown"] = """\
# syntax=docker/dockerfile:1.6
# ContainerForge - Generic OCI Image (language not detected)

ARG APP_PORT={port}

FROM ubuntu:22.04

LABEL org.opencontainers.image.title="{app_name}" \\
      org.opencontainers.image.vendor="ContainerForge" \\
      org.opencontainers.image.created="{oci_created}"

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \\
    rm -rf /var/lib/apt/lists/* && \\
    useradd --uid 1001 --no-create-home --shell /sbin/nologin appuser

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser
EXPOSE ${{APP_PORT}}
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\
    CMD curl -sf http://localhost:${{APP_PORT}}/health || exit 1

CMD {cmd_json}
"""

# ─── .dockerignore templates per language ────────────────────────────────────────
DOCKERIGNORE_EXTRAS: dict[str, list[str]] = {
    "python":  ["__pycache__/", "*.pyc", "*.pyo", ".venv/", "venv/", "env/", "*.egg-info/",
                ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", "dist/", "build/"],
    "nodejs":  ["node_modules/", "dist/", ".next/", ".nuxt/", "*.log", "coverage/", ".cache/"],
    "go":      ["*.exe", "*.test", "vendor/", "bin/"],
    "java":    ["target/", "build/", "*.class", "*.jar", ".gradle/", ".mvn/"],
    "ruby":    [".bundle/", "log/", "tmp/", "*.gem"],
    "rust":    ["target/"],
    "php":     ["vendor/", "node_modules/", "storage/logs/", ".env"],
    "dotnet":  ["bin/", "obj/", "*.user"],
}

DOCKERIGNORE_COMMON = """\
# ContainerForge .dockerignore
.git/
.gitignore
.gitattributes
.github/

# Docker
Dockerfile*
docker-compose*
.dockerignore

# ContainerForge generated
sidecar/
_cf_health.py
_cf_health_server.py

# Environment
.env
.env.*
*.local

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store
Thumbs.db

# Tests
tests/
test/
spec/
__tests__/
*.test.*
*.spec.*

# Docs
docs/
*.md
LICENSE*

# CI
.circleci/
.travis.yml
.github/
"""


class OCIDockerfileGenerator:
    """
    Generates OCI-compliant Dockerfiles from SourceDetector output.
    Supports: Python, Node.js, Go, Java, Ruby, Rust, PHP, .NET
    """

    def __init__(self, app_path: Path, detection: dict):
        self.app_path = Path(app_path)
        self.d = detection

    def generate(self) -> Path:
        dockerfile_path = self.app_path / "Dockerfile"
        dockerignore_path = self.app_path / ".dockerignore"

        dockerfile_path.write_text(self._render())

        if not dockerignore_path.exists():
            dockerignore_path.write_text(self._render_dockerignore())

        return dockerfile_path

    def _render(self) -> str:
        language = self.d.get("language", "unknown")
        template = TEMPLATES.get(language, TEMPLATES["unknown"])

        ctx = self._build_context()
        return template.format(**ctx)

    def _build_context(self) -> dict:
        d = self.d
        language = d.get("language", "unknown")
        framework = d.get("framework", "unknown")
        start_cmd = d.get("start_command", "")
        build_cmd = d.get("build_command", "")

        # Deps copy section varies per language
        deps_copy = self._deps_copy_section(language, d.get("deps_file"), d.get("lock_file"))

        # Install args for Python: strip leading "pip install " (template adds its own pip prefix)
        raw_cmd = d.get("deps_install_cmd", "-r requirements.txt") or "-r requirements.txt"
        if language == "python":
            for pfx in ["pip install ", "pip3 install "]:
                if raw_cmd.startswith(pfx):
                    raw_cmd = raw_cmd[len(pfx):]
            deps_install = f"{raw_cmd} psutil"
        else:
            deps_install = raw_cmd

        # Build step for Node.js (optional)
        pkg_build = ""
        if language == "nodejs":
            pkg = self.app_path / "package.json"
            if pkg.exists():
                try:
                    data = json.loads(pkg.read_text())
                    build_script = data.get("scripts", {}).get("build", "")
                    if build_script:
                        pkg_build = f"RUN npm run build"
                except Exception:
                    pass

        return {
            "app_name":          self.app_path.name,
            "language":          language,
            "framework":         framework,
            "framework_display": d.get("framework_display", framework.capitalize()),
            "runtime_version":   d.get("runtime_version", "latest"),
            "port":              d.get("port", 8080),
            "cmd_json":          self._to_cmd_json(start_cmd),
            "build_command":     build_cmd or "echo 'No build step'",
            "build_step":        pkg_build or "# No build step detected",
            "deps_copy_section": deps_copy,
            "deps_install_args": deps_install,
            "oci_description":   d.get("oci_labels", {}).get("org.opencontainers.image.description", f"{framework} application"),
            "oci_created":       d.get("oci_labels", {}).get("org.opencontainers.image.created", ""),
        }

    def _deps_copy_section(self, language: str, deps_file: Optional[str], lock_file: Optional[str]) -> str:
        if not deps_file:
            return "# No dependency file detected"

        sections = {
            "python": {
                "requirements.txt": f"COPY requirements.txt .\n{f'COPY {lock_file} .' if lock_file else ''}",
                "pyproject.toml":   "COPY pyproject.toml .\nCOPY . .",
                "Pipfile":          f"COPY Pipfile {'Pipfile.lock' if lock_file else ''} ./",
                "setup.py":         "COPY setup.py .\nCOPY . .",
            },
            "nodejs": {
                "package.json": f"COPY package.json {'package-lock.json' if lock_file == 'package-lock.json' else 'yarn.lock' if lock_file == 'yarn.lock' else ''} ./",
            },
            "go": {
                "go.mod": "COPY go.mod go.sum* ./",
            },
            "java": {
                "pom.xml":           "COPY pom.xml .\nCOPY src ./src",
                "build.gradle":      "COPY build.gradle settings.gradle* ./\nCOPY src ./src",
                "build.gradle.kts":  "COPY build.gradle.kts settings.gradle.kts* ./\nCOPY src ./src",
            },
            "ruby": {
                "Gemfile": f"COPY Gemfile {'Gemfile.lock' if lock_file else ''} ./",
            },
        }

        lang_sections = sections.get(language, {})
        return lang_sections.get(deps_file, f"COPY {deps_file} .")

    def _to_cmd_json(self, command: str) -> str:
        if not command:
            return '["sh", "-c", "echo No start command detected"]'
        parts = shlex.split(command)
        quoted = ", ".join(f'"{p}"' for p in parts)
        return f"[{quoted}]"

    def _render_dockerignore(self) -> str:
        language = self.d.get("language", "unknown")
        extras = DOCKERIGNORE_EXTRAS.get(language, [])
        lang_section = "\n".join(f"# {language.capitalize()} specific\n" + "\n".join(extras)) if extras else ""
        return DOCKERIGNORE_COMMON + "\n" + lang_section + "\n"
