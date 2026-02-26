"""
SourceDetector: Universal language & framework detector.

Scans a source directory and identifies:
  - Language (Python, Node.js, Go, Java, Ruby, Rust, PHP, .NET)
  - Framework (Flask, FastAPI, Django, Express, Gin, Spring, Rails, etc.)
  - Entry point file
  - Port
  - Build/start commands
  - Runtime version
  - Dependency file & lock file

Used as the first pass before framework-specific analysis.
"""

import re
import json
from pathlib import Path
from typing import Optional


# ─── Language Fingerprints ────────────────────────────────────────────────────
# Each entry: (language_key, indicator_files, indicator_extensions)
LANGUAGE_FINGERPRINTS = [
    ("python",  ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg", "poetry.lock"], [".py"]),
    ("nodejs",  ["package.json"],                                                                            [".js", ".ts", ".mjs", ".cjs"]),
    ("go",      ["go.mod", "go.sum"],                                                                        [".go"]),
    ("java",    ["pom.xml", "build.gradle", "build.gradle.kts", "gradlew"],                                  [".java"]),
    ("ruby",    ["Gemfile", "Gemfile.lock", "Rakefile"],                                                     [".rb"]),
    ("rust",    ["Cargo.toml", "Cargo.lock"],                                                                [".rs"]),
    ("php",     ["composer.json", "artisan"],                                                                [".php"]),
    ("dotnet",  [".sln", ".csproj", ".fsproj", ".vbproj"],                                                   [".cs", ".fs"]),
]

# ─── Framework Patterns per Language ─────────────────────────────────────────
FRAMEWORK_PATTERNS = {
    "python": [
        ("fastapi",  ["fastapi"],                    ["fastapi", "FastAPI"]),
        ("flask",    ["flask"],                      ["flask", "Flask"]),
        ("django",   ["django"],                     ["django", "Django"]),
        ("starlette",["starlette"],                  ["starlette", "Starlette"]),
        ("tornado",  ["tornado"],                    ["tornado", "Application"]),
        ("aiohttp",  ["aiohttp"],                    ["aiohttp", "web.Application"]),
        ("bottle",   ["bottle"],                     ["bottle", "Bottle"]),
        ("sanic",    ["sanic"],                      ["sanic", "Sanic"]),
        ("litestar", ["litestar"],                   ["litestar", "Litestar"]),
    ],
    "nodejs": [
        ("express",  ["express"],                    ["require('express')", "require(\"express\")", "from 'express'"]),
        ("fastify",  ["fastify"],                    ["require('fastify')", "fastify()"]),
        ("nextjs",   ["next"],                       ["next/app", "from 'next'"]),
        ("nestjs",   ["@nestjs/core"],               ["NestFactory", "@nestjs"]),
        ("koa",      ["koa"],                        ["require('koa')", "new Koa()"]),
        ("hapi",     ["@hapi/hapi"],                 ["@hapi/hapi", "Hapi.server"]),
        ("nuxt",     ["nuxt"],                       ["nuxt", "defineNuxtConfig"]),
    ],
    "go": [
        ("gin",      ["github.com/gin-gonic/gin"],   ["gin.New()", "gin.Default()"]),
        ("echo",     ["github.com/labstack/echo"],   ["echo.New()"]),
        ("fiber",    ["github.com/gofiber/fiber"],   ["fiber.New()"]),
        ("chi",      ["github.com/go-chi/chi"],      ["chi.NewRouter()"]),
        ("gorilla",  ["github.com/gorilla/mux"],     ["mux.NewRouter()"]),
        ("net/http", [],                             ["http.ListenAndServe", "http.HandleFunc"]),
    ],
    "java": [
        ("spring",   ["spring-boot", "org.springframework"],  ["SpringApplication", "@SpringBootApplication"]),
        ("quarkus",  ["quarkus"],                             ["@QuarkusMain"]),
        ("micronaut",["micronaut"],                           ["@MicronautApplication"]),
        ("vertx",    ["vertx"],                               ["Vertx.vertx()"]),
        ("jakarta",  ["jakarta"],                             ["@WebServlet"]),
    ],
    "ruby": [
        ("rails",    ["rails"],                      ["Rails.application", "config.application"]),
        ("sinatra",  ["sinatra"],                    ["require 'sinatra'", "Sinatra::Base"]),
        ("hanami",   ["hanami"],                     ["Hanami.app"]),
        ("grape",    ["grape"],                      ["Grape::API"]),
    ],
    "rust": [
        ("actix",    ["actix-web"],                  ["actix_web", "HttpServer::new"]),
        ("axum",     ["axum"],                       ["axum::Router", "axum::serve"]),
        ("warp",     ["warp"],                       ["warp::serve"]),
        ("rocket",   ["rocket"],                     ["#[rocket::main]", "rocket::build"]),
    ],
    "php": [
        ("laravel",  ["laravel/framework"],          ["Illuminate\\", "artisan"]),
        ("symfony",  ["symfony/symfony"],            ["Symfony\\", "bin/console"]),
        ("slim",     ["slim/slim"],                  ["Slim\\Factory"]),
        ("lumen",    ["laravel/lumen-framework"],    ["Laravel\\Lumen"]),
    ],
    "dotnet": [
        ("aspnet",   ["Microsoft.AspNetCore"],       ["WebApplication.Create", "builder.Build()"]),
        ("blazor",   ["Microsoft.AspNetCore.Components"], ["@page"]),
        ("minimal",  [],                             ["app.MapGet", "app.MapPost"]),
    ],
}

# ─── Default ports per framework ─────────────────────────────────────────────
DEFAULT_PORTS = {
    # Python
    "flask": 5000, "fastapi": 8000, "django": 8000, "starlette": 8000,
    "tornado": 8888, "aiohttp": 8080, "bottle": 8080, "sanic": 8000, "litestar": 8000,
    # Node
    "express": 3000, "fastify": 3000, "nextjs": 3000, "nestjs": 3000,
    "koa": 3000, "hapi": 3000, "nuxt": 3000,
    # Go
    "gin": 8080, "echo": 8080, "fiber": 3000, "chi": 8080, "gorilla": 8080, "net/http": 8080,
    # Java
    "spring": 8080, "quarkus": 8080, "micronaut": 8080, "vertx": 8888, "jakarta": 8080,
    # Ruby
    "rails": 3000, "sinatra": 4567, "hanami": 2300, "grape": 9292,
    # Rust
    "actix": 8080, "axum": 3000, "warp": 3030, "rocket": 8000,
    # PHP
    "laravel": 8000, "symfony": 8000, "slim": 8080, "lumen": 8000,
    # .NET
    "aspnet": 5000, "blazor": 5000, "minimal": 5000,
    # fallback
    "unknown": 8080,
}

# ─── Runtime version detection files ─────────────────────────────────────────
VERSION_FILES = {
    "python":  [".python-version", "pyproject.toml", "runtime.txt"],
    "nodejs":  [".nvmrc", ".node-version", "package.json"],
    "go":      ["go.mod"],
    "java":    [".java-version", "pom.xml", "build.gradle"],
    "ruby":    [".ruby-version", "Gemfile"],
    "rust":    ["rust-toolchain", "rust-toolchain.toml"],
    "php":     [".php-version", "composer.json"],
    "dotnet":  ["global.json", ".csproj"],
}

# ─── Default runtime versions ─────────────────────────────────────────────────
DEFAULT_VERSIONS = {
    "python": "3.11",
    "nodejs": "20",
    "go":     "1.22",
    "java":   "21",
    "ruby":   "3.3",
    "rust":   "latest",
    "php":    "8.3",
    "dotnet": "8.0",
}


class SourceDetector:
    """
    Detects language, framework, entry point, and runtime info from a source directory.
    Returns a normalized detection result dict consumed by Dockerfile/Compose generators.
    """

    def __init__(self, app_path: Path):
        self.app_path = Path(app_path).resolve()
        self._file_cache: dict[str, str] = {}

    def detect(self) -> dict:
        language = self._detect_language()
        framework = self._detect_framework(language)
        runtime_version = self._detect_runtime_version(language)
        entry_point = self._detect_entry_point(language, framework)
        port = self._detect_port(language, framework, entry_point)
        deps_info = self._detect_deps(language)
        build_cmd, start_cmd = self._detect_commands(language, framework, entry_point, port)
        expose_ports = self._detect_all_ports(language, framework)

        return {
            # Identity
            "language": language,
            "language_display": language.capitalize() if language != "nodejs" else "Node.js",
            "framework": framework,
            "framework_display": self._framework_display_name(framework),

            # Runtime
            "runtime_version": runtime_version,
            "base_image": self._base_image(language, runtime_version),
            "base_image_builder": self._base_image_builder(language, runtime_version),

            # Entry point
            "entry_point": str(entry_point.relative_to(self.app_path)) if entry_point else None,
            "entry_point_abs": str(entry_point) if entry_point else None,
            "app_object": self._detect_app_object(language, framework, entry_point),
            "module_name": self._path_to_module(entry_point),

            # Ports
            "port": port,
            "expose_ports": expose_ports,

            # Commands
            "build_command": build_cmd,
            "start_command": start_cmd,

            # Dependencies
            "deps_file": deps_info.get("deps_file"),
            "lock_file": deps_info.get("lock_file"),
            "package_manager": deps_info.get("package_manager"),
            "deps_install_cmd": deps_info.get("install_cmd"),

            # Environment
            "has_env_file": self._has_env_file(),
            "env_vars": self._detect_env_vars(entry_point),

            # OCI metadata
            "oci_labels": self._build_oci_labels(language, framework),

            # Detection confidence
            "confidence": self._score_confidence(language, framework, entry_point, deps_info),
        }

    # ─── Language Detection ───────────────────────────────────────────────────

    def _detect_language(self) -> str:
        scores: dict[str, int] = {}

        for lang, indicator_files, indicator_exts in LANGUAGE_FINGERPRINTS:
            score = 0
            # Check indicator files (strong signal)
            for fname in indicator_files:
                if (self.app_path / fname).exists():
                    score += 10
                # Also search one level deep
                elif list(self.app_path.glob(f"*/{fname}")):
                    score += 5

            # Count source files (weaker signal)
            for ext in indicator_exts:
                count = len(list(self.app_path.rglob(f"*{ext}")))
                score += min(count, 5)  # cap so one big file dump doesn't skew

            if score > 0:
                scores[lang] = score

        if not scores:
            return "unknown"
        return max(scores, key=lambda k: scores[k])

    # ─── Framework Detection ──────────────────────────────────────────────────

    def _detect_framework(self, language: str) -> str:
        if language not in FRAMEWORK_PATTERNS:
            return "unknown"

        deps_text = self._read_all_deps_text(language)
        source_text = self._sample_source_text(language)
        combined = (deps_text + "\n" + source_text).lower()

        for fw_key, dep_signals, source_signals in FRAMEWORK_PATTERNS[language]:
            # Check dependency files first
            for sig in dep_signals:
                if sig.lower() in combined:
                    return fw_key
            # Check source patterns
            for sig in source_signals:
                if sig.lower() in combined:
                    return fw_key

        return "unknown"

    # ─── Entry Point Detection ────────────────────────────────────────────────

    def _detect_entry_point(self, language: str, framework: str) -> Optional[Path]:
        candidates_by_lang = {
            "python":  ["main.py", "app.py", "server.py", "run.py", "application.py", "api.py", "wsgi.py", "asgi.py", "manage.py"],
            "nodejs":  ["index.js", "server.js", "app.js", "main.js", "src/index.js", "src/server.js", "src/app.js",
                        "index.ts", "server.ts", "app.ts", "main.ts", "src/index.ts"],
            "go":      ["main.go", "cmd/main.go", "cmd/server/main.go", "cmd/app/main.go"],
            "java":    ["src/main/java/**/*Application.java", "src/main/java/**/*Main.java"],
            "ruby":    ["config.ru", "app.rb", "server.rb", "config/application.rb"],
            "rust":    ["src/main.rs"],
            "php":     ["public/index.php", "index.php", "artisan"],
            "dotnet":  ["Program.cs", "Startup.cs", "src/*/Program.cs"],
        }

        candidates = candidates_by_lang.get(language, [])

        for pattern in candidates:
            if "**" in pattern or "*" in pattern:
                results = list(self.app_path.rglob(pattern.lstrip("/")))
                if results:
                    return results[0]
            else:
                p = self.app_path / pattern
                if p.exists():
                    return p

        # Fallback: first source file with main/app definition
        ext_by_lang = {"python": ".py", "nodejs": ".js", "go": ".go", "ruby": ".rb", "rust": ".rs", "php": ".php"}
        ext = ext_by_lang.get(language)
        if ext:
            for f in sorted(self.app_path.glob(f"*{ext}")):
                try:
                    t = f.read_text(errors="ignore")
                    if any(kw in t for kw in ["main(", "app =", "application =", "__main__", "def main"]):
                        return f
                except Exception:
                    pass

        return None

    # ─── Port Detection ───────────────────────────────────────────────────────

    def _detect_port(self, language: str, framework: str, entry_point: Optional[Path]) -> int:
        PORT_PATTERNS = [
            r'port\s*[:=]\s*(\d{4,5})',
            r'PORT\s*[:=]\s*["\']?(\d{4,5})',
            r'listen\s*\(\s*(\d{4,5})',
            r':(\d{4,5})["\'\s]',
            r'--port[=\s]+(\d{4,5})',
            r'localhost:(\d{4,5})',
        ]

        # 1. Check .env / .env.example
        for env_name in [".env", ".env.example", ".env.sample", ".env.local"]:
            env_path = self.app_path / env_name
            if env_path.exists():
                text = self._read_file(env_path)
                for pat in PORT_PATTERNS:
                    m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
                    if m and 1024 <= int(m.group(1)) <= 65535:
                        return int(m.group(1))

        # 2. Check entry point
        if entry_point and entry_point.exists():
            text = self._read_file(entry_point)
            for pat in PORT_PATTERNS:
                m = re.search(pat, text, re.IGNORECASE)
                if m and 1024 <= int(m.group(1)) <= 65535:
                    return int(m.group(1))

        # 3. Check package.json "scripts" for port hints (Node)
        if language == "nodejs":
            pkg = self.app_path / "package.json"
            if pkg.exists():
                try:
                    data = json.loads(pkg.read_text())
                    scripts = json.dumps(data.get("scripts", {}))
                    for pat in PORT_PATTERNS:
                        m = re.search(pat, scripts)
                        if m and 1024 <= int(m.group(1)) <= 65535:
                            return int(m.group(1))
                except Exception:
                    pass

        # 4. Default by framework
        return DEFAULT_PORTS.get(framework, DEFAULT_PORTS.get("unknown", 8080))

    def _detect_all_ports(self, language: str, framework: str) -> list[int]:
        """Detect all ports the app might expose (main + metrics + debug)."""
        main_port = self._detect_port(language, framework, None)
        ports = [main_port]
        # Common secondary ports
        text = self._sample_source_text(language)
        for m in re.finditer(r'\b(\d{4,5})\b', text):
            p = int(m.group(1))
            if 1024 <= p <= 65535 and p != main_port and p not in ports:
                ports.append(p)
                if len(ports) >= 3:
                    break
        return ports[:1]  # only expose main port in Dockerfile (others via compose)

    # ─── Runtime Version ──────────────────────────────────────────────────────

    def _detect_runtime_version(self, language: str) -> str:
        version_patterns = {
            "python": [
                (r"python_requires\s*=\s*[\"']>=?\s*([\d.]+)", "pyproject.toml"),
                (r"^python-([\d.]+)$", "runtime.txt"),
                (r"^([\d.]+)$", ".python-version"),
            ],
            "nodejs": [
                (r"^([\d.]+)$", ".nvmrc"),
                (r"^v?([\d.]+)$", ".node-version"),
                (r'"node":\s*"[>=~^]*([\d.]+)', "package.json"),
                (r'"engines".*"node".*"([\d.]+)', "package.json"),
            ],
            "go": [
                (r"^go\s+([\d.]+)", "go.mod"),
            ],
            "java": [
                (r"<java\.version>([\d.]+)<", "pom.xml"),
                (r"sourceCompatibility\s*=\s*[\"']?([\d.]+)", "build.gradle"),
                (r"^([\d.]+)$", ".java-version"),
            ],
            "ruby": [
                (r"^ruby\s+[\"']([\d.]+)", "Gemfile"),
                (r"^([\d.]+)$", ".ruby-version"),
            ],
            "rust": [
                (r'^channel\s*=\s*"([\w.]+)"', "rust-toolchain.toml"),
                (r'^([\w.-]+)$', "rust-toolchain"),
            ],
            "php": [
                (r'"php":\s*"[>=~^]*([\d.]+)', "composer.json"),
                (r"^([\d.]+)$", ".php-version"),
            ],
            "dotnet": [
                (r'"version":\s*"([\d.]+)"', "global.json"),
                (r'<TargetFramework>net([\d.]+)<', ".csproj"),
            ],
        }

        for pattern, filename in version_patterns.get(language, []):
            # Try root first, then first match
            for fpath in [self.app_path / filename] + list(self.app_path.rglob(filename))[:2]:
                if fpath.exists():
                    try:
                        text = fpath.read_text(errors="ignore")
                        m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
                        if m:
                            v = m.group(1).strip()
                            if v:
                                return v
                    except Exception:
                        pass

        return DEFAULT_VERSIONS.get(language, "latest")

    # ─── Dependency Detection ─────────────────────────────────────────────────

    def _detect_deps(self, language: str) -> dict:
        specs = {
            "python": {
                "files": ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"],
                "locks": ["requirements.lock", "poetry.lock", "Pipfile.lock"],
                "managers": {
                    "requirements.txt": ("pip", "pip install -r requirements.txt"),
                    "pyproject.toml":   ("pip/poetry", "pip install ."),
                    "Pipfile":          ("pipenv", "pipenv install --system --deploy"),
                },
            },
            "nodejs": {
                "files": ["package.json"],
                "locks": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
                "managers": {
                    "package-lock.json": ("npm",  "npm ci --omit=dev"),
                    "yarn.lock":         ("yarn", "yarn install --frozen-lockfile --production"),
                    "pnpm-lock.yaml":    ("pnpm", "pnpm install --frozen-lockfile --prod"),
                    "package.json":      ("npm",  "npm ci --omit=dev"),
                },
            },
            "go": {
                "files": ["go.mod"],
                "locks": ["go.sum"],
                "managers": {"go.mod": ("go", "go mod download")},
            },
            "java": {
                "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
                "locks": [],
                "managers": {
                    "pom.xml":           ("maven",  "mvn package -DskipTests"),
                    "build.gradle":      ("gradle", "./gradlew bootJar"),
                    "build.gradle.kts":  ("gradle", "./gradlew bootJar"),
                },
            },
            "ruby": {
                "files": ["Gemfile"],
                "locks": ["Gemfile.lock"],
                "managers": {"Gemfile": ("bundler", "bundle install --without development test")},
            },
            "rust": {
                "files": ["Cargo.toml"],
                "locks": ["Cargo.lock"],
                "managers": {"Cargo.toml": ("cargo", "cargo build --release")},
            },
            "php": {
                "files": ["composer.json"],
                "locks": ["composer.lock"],
                "managers": {"composer.json": ("composer", "composer install --no-dev --optimize-autoloader")},
            },
            "dotnet": {
                "files": [".csproj", ".fsproj"],
                "locks": [],
                "managers": {".csproj": ("dotnet", "dotnet publish -c Release -o /app/publish")},
            },
        }

        spec = specs.get(language, {})
        deps_file = None
        lock_file = None
        package_manager = "unknown"
        install_cmd = ""

        # Find deps file
        for fname in spec.get("files", []):
            if "*" in fname:
                results = list(self.app_path.rglob(fname))
                if results:
                    deps_file = str(results[0].relative_to(self.app_path))
                    break
            elif (self.app_path / fname).exists():
                deps_file = fname
                break

        # Find lock file
        for fname in spec.get("locks", []):
            if (self.app_path / fname).exists():
                lock_file = fname
                break

        # Determine package manager & install command
        managers = spec.get("managers", {})
        # Prefer lock file for determining manager
        key = lock_file or deps_file
        if key and key in managers:
            package_manager, install_cmd = managers[key]
        elif deps_file and deps_file in managers:
            package_manager, install_cmd = managers[deps_file]

        return {
            "deps_file": deps_file,
            "lock_file": lock_file,
            "package_manager": package_manager,
            "install_cmd": install_cmd,
        }

    # ─── Build & Start Commands ───────────────────────────────────────────────

    def _detect_commands(self, language: str, framework: str, entry_point: Optional[Path], port: int) -> tuple[str, str]:
        """Returns (build_command, start_command)."""
        module = self._path_to_module(entry_point) if entry_point else "main"
        app_obj = self._detect_app_object(language, framework, entry_point)

        if language == "python":
            if framework == "fastapi":
                return "", f"uvicorn {module}:{app_obj} --host 0.0.0.0 --port {port} --workers 2"
            elif framework == "flask":
                return "", f"gunicorn {module}:{app_obj} --bind 0.0.0.0:{port} --workers 2 --timeout 120"
            elif framework == "django":
                return "", f"gunicorn {module}.wsgi:application --bind 0.0.0.0:{port} --workers 2"
            elif framework in ("starlette", "litestar"):
                return "", f"uvicorn {module}:{app_obj} --host 0.0.0.0 --port {port}"
            else:
                ep = entry_point.relative_to(self.app_path) if entry_point else Path("main.py")
                return "", f"python {ep}"

        elif language == "nodejs":
            # Check package.json start script
            pkg_path = self.app_path / "package.json"
            if pkg_path.exists():
                try:
                    pkg = json.loads(pkg_path.read_text())
                    start = pkg.get("scripts", {}).get("start", "")
                    if start:
                        return pkg.get("scripts", {}).get("build", ""), start
                except Exception:
                    pass
            ep = entry_point.relative_to(self.app_path) if entry_point else Path("index.js")
            return "", f"node {ep}"

        elif language == "go":
            return "go build -o /app/server ./...", "/app/server"

        elif language == "java":
            if (self.app_path / "pom.xml").exists():
                return "mvn package -DskipTests", "java -jar target/*.jar"
            elif (self.app_path / "build.gradle").exists() or (self.app_path / "build.gradle.kts").exists():
                return "./gradlew bootJar", "java -jar build/libs/*.jar"
            return "", "java -jar app.jar"

        elif language == "ruby":
            if framework == "rails":
                return "bundle exec rake assets:precompile", "bundle exec rails server -b 0.0.0.0 -p {port}"
            ep = entry_point.relative_to(self.app_path) if entry_point else Path("config.ru")
            return "", f"bundle exec rackup {ep} -o 0.0.0.0 -p {port}"

        elif language == "rust":
            return "cargo build --release", "/app/target/release/app"

        elif language == "php":
            if framework == "laravel":
                return "composer install --no-dev", f"php artisan serve --host 0.0.0.0 --port {port}"
            return "", f"php -S 0.0.0.0:{port} -t public"

        elif language == "dotnet":
            return "dotnet publish -c Release -o /app/publish", "dotnet /app/publish/*.dll"

        return "", f"./start.sh"

    # ─── OCI Labels ──────────────────────────────────────────────────────────

    def _build_oci_labels(self, language: str, framework: str) -> dict:
        """Build OCI image spec compliant labels."""
        import datetime
        return {
            "org.opencontainers.image.created":     datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "org.opencontainers.image.title":       self.app_path.name,
            "org.opencontainers.image.description": f"Containerized {language} {framework} application",
            "org.opencontainers.image.source":      "https://github.com/your-org/" + self.app_path.name,
            "org.opencontainers.image.vendor":      "ContainerForge",
            "org.opencontainers.image.licenses":    "MIT",
            "org.opencontainers.image.base.name":   f"docker.io/library/{language}",
            "dev.containerforge.language":          language,
            "dev.containerforge.framework":         framework,
            "dev.containerforge.version":           "2.1.0",
        }

    # ─── App Object Detection ─────────────────────────────────────────────────

    def _detect_app_object(self, language: str, framework: str, entry_point: Optional[Path]) -> str:
        if not entry_point or not entry_point.exists():
            return "app"
        try:
            text = self._read_file(entry_point)
            patterns = [
                r'^(app|application|api|server)\s*=\s*(?:Flask|FastAPI|Starlette|Sanic|Litestar|Bottle)',
                r'^(app|application)\s*=\s*\w+\(',
                r'(app)\s*:=\s*(?:gin|echo|fiber|chi)',  # Go
                r'var\s+(app|server)\s*=',                # JS
                r'const\s+(app|server)\s*=',              # JS
            ]
            for pat in patterns:
                m = re.search(pat, text, re.MULTILINE)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return "app"

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _base_image(self, language: str, version: str) -> str:
        """Return the slim runtime base image for OCI builds."""
        images = {
            "python":  f"python:{version}-slim",
            "nodejs":  f"node:{version}-alpine",
            "go":      f"gcr.io/distroless/static-debian12",
            "java":    f"eclipse-temurin:{version}-jre-alpine",
            "ruby":    f"ruby:{version}-slim",
            "rust":    f"gcr.io/distroless/cc-debian12",
            "php":     f"php:{version}-fpm-alpine",
            "dotnet":  f"mcr.microsoft.com/dotnet/aspnet:{version}-alpine",
        }
        return images.get(language, f"{language}:{version}-slim")

    def _base_image_builder(self, language: str, version: str) -> str:
        """Return the full build-stage base image."""
        images = {
            "python":  f"python:{version}-slim",
            "nodejs":  f"node:{version}-alpine",
            "go":      f"golang:{version}-alpine",
            "java":    f"eclipse-temurin:{version}-jdk-alpine",
            "ruby":    f"ruby:{version}",
            "rust":    f"rust:latest-slim",
            "php":     f"php:{version}-cli",
            "dotnet":  f"mcr.microsoft.com/dotnet/sdk:{version}-alpine",
        }
        return images.get(language, f"{language}:{version}")

    def _framework_display_name(self, framework: str) -> str:
        display = {
            "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
            "starlette": "Starlette", "tornado": "Tornado", "aiohttp": "aiohttp",
            "sanic": "Sanic", "litestar": "Litestar",
            "express": "Express.js", "fastify": "Fastify", "nextjs": "Next.js",
            "nestjs": "NestJS", "koa": "Koa", "nuxt": "Nuxt",
            "gin": "Gin", "echo": "Echo", "fiber": "Fiber",
            "chi": "Chi", "gorilla": "Gorilla Mux", "net/http": "net/http",
            "spring": "Spring Boot", "quarkus": "Quarkus", "micronaut": "Micronaut",
            "rails": "Ruby on Rails", "sinatra": "Sinatra",
            "actix": "Actix-web", "axum": "Axum", "rocket": "Rocket",
            "laravel": "Laravel", "symfony": "Symfony",
            "aspnet": "ASP.NET Core",
        }
        return display.get(framework, framework.capitalize() if framework else "Unknown")

    def _path_to_module(self, path: Optional[Path]) -> str:
        if not path:
            return "main"
        try:
            rel = path.relative_to(self.app_path)
            return str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
        except Exception:
            return path.stem

    def _has_env_file(self) -> bool:
        return any((self.app_path / f).exists() for f in [".env", ".env.example", ".env.sample"])

    def _detect_env_vars(self, entry_point: Optional[Path]) -> list[str]:
        """Detect env var names referenced in code."""
        found = set()
        patterns = [
            r'os\.environ\.get\(["\'](\w+)["\']',
            r'os\.getenv\(["\'](\w+)["\']',
            r'process\.env\.(\w+)',
            r'os\.Getenv\(["\'](\w+)["\']',
            r'ENV\[.(\w+).\]',
        ]
        files_to_check = []
        if entry_point and entry_point.exists():
            files_to_check.append(entry_point)
        for f in list(self.app_path.glob("*.py"))[:5] + list(self.app_path.glob("*.js"))[:5]:
            files_to_check.append(f)
        for f in files_to_check:
            try:
                text = self._read_file(f)
                for pat in patterns:
                    for m in re.finditer(pat, text):
                        found.add(m.group(1))
            except Exception:
                pass
        return sorted(found)

    def _score_confidence(self, language: str, framework: str, entry_point, deps_info: dict) -> str:
        score = 0
        if language != "unknown": score += 30
        if framework != "unknown": score += 25
        if entry_point: score += 20
        if deps_info.get("deps_file"): score += 15
        if deps_info.get("lock_file"): score += 10
        if score >= 90: return "high"
        if score >= 60: return "medium"
        return "low"

    def _read_file(self, path: Path) -> str:
        key = str(path)
        if key not in self._file_cache:
            try:
                self._file_cache[key] = path.read_text(errors="ignore")
            except Exception:
                self._file_cache[key] = ""
        return self._file_cache[key]

    def _read_all_deps_text(self, language: str) -> str:
        dep_files = {
            "python":  ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"],
            "nodejs":  ["package.json"],
            "go":      ["go.mod"],
            "java":    ["pom.xml", "build.gradle"],
            "ruby":    ["Gemfile"],
            "rust":    ["Cargo.toml"],
            "php":     ["composer.json"],
            "dotnet":  [".csproj"],
        }
        texts = []
        for fname in dep_files.get(language, []):
            if "*" in fname:
                for p in list(self.app_path.rglob(fname))[:1]:
                    texts.append(self._read_file(p))
            else:
                p = self.app_path / fname
                if p.exists():
                    texts.append(self._read_file(p))
        return "\n".join(texts)

    def _sample_source_text(self, language: str, max_files: int = 15) -> str:
        ext_map = {
            "python": ".py", "nodejs": ".js", "go": ".go", "java": ".java",
            "ruby": ".rb", "rust": ".rs", "php": ".php", "dotnet": ".cs",
        }
        ext = ext_map.get(language, ".txt")
        texts = []
        for f in list(self.app_path.rglob(f"*{ext}"))[:max_files]:
            texts.append(self._read_file(f))
        return "\n".join(texts)
