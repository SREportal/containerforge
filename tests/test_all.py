"""
ContainerForge — Complete Test Suite
=====================================
Run with:   pytest tests/ -v
Coverage:   pytest tests/ --cov=containerforge --cov-report=html

Tests are organized by module and use only stdlib + pytest (no mocking libs needed).
All tests create isolated temp directories and clean up after themselves.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def app_dir(files: dict) -> Path:
    """Create a temp directory with given files. Returns the Path."""
    d = Path(tempfile.mkdtemp(prefix="cf_test_"))
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 1. SOURCE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceDetector:
    """Tests for analyzer/source_detector.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.analyzer.source_detector import SourceDetector
        self.Detector = SourceDetector

    def detect(self, files):
        d = app_dir(files)
        try:
            return self.Detector(d).detect()
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ── Language detection ────────────────────────────────────────────────────

    def test_detects_python_by_requirements(self):
        r = self.detect({"requirements.txt": "flask\n"})
        assert r["language"] == "python"

    def test_detects_nodejs_by_package_json(self):
        r = self.detect({"package.json": '{"dependencies": {"express": "^4"}}'})
        assert r["language"] == "nodejs"

    def test_detects_go_by_go_mod(self):
        r = self.detect({"go.mod": "module myapp\n\ngo 1.22\n"})
        assert r["language"] == "go"

    def test_detects_java_by_pom_xml(self):
        r = self.detect({"pom.xml": "<project><artifactId>myapp</artifactId></project>"})
        assert r["language"] == "java"

    def test_detects_ruby_by_gemfile(self):
        r = self.detect({"Gemfile": "source 'https://rubygems.org'\ngem 'sinatra'\n"})
        assert r["language"] == "ruby"

    def test_detects_rust_by_cargo_toml(self):
        r = self.detect({"Cargo.toml": '[package]\nname = "myapp"\nversion = "0.1.0"\n'})
        assert r["language"] == "rust"

    def test_unknown_language_on_empty_dir(self):
        r = self.detect({})
        assert r["language"] == "unknown"

    # ── Framework detection ────────────────────────────────────────────────────

    def test_flask_framework(self):
        r = self.detect({
            "requirements.txt": "flask>=2.0\ngunicorn\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        assert r["framework"] == "flask"

    def test_fastapi_framework(self):
        r = self.detect({
            "requirements.txt": "fastapi\nuvicorn\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        assert r["framework"] == "fastapi"

    def test_django_framework(self):
        r = self.detect({
            "requirements.txt": "django>=4.2\n",
            "manage.py": "from django.core.management import execute_from_command_line\n",
        })
        assert r["framework"] == "django"

    def test_express_framework(self):
        r = self.detect({
            "package.json": json.dumps({"dependencies": {"express": "^4.18"}}),
            "index.js": "const express = require('express');\nconst app = express();\napp.listen(3000);\n",
        })
        assert r["framework"] == "express"

    def test_gin_framework(self):
        r = self.detect({
            "go.mod": "module myapp\n\ngo 1.22\n\nrequire github.com/gin-gonic/gin v1.9.1\n",
            "main.go": 'package main\nimport "github.com/gin-gonic/gin"\nfunc main() { r := gin.Default(); r.Run(":8080") }\n',
        })
        assert r["framework"] == "gin"

    def test_nextjs_framework(self):
        r = self.detect({
            "package.json": json.dumps({"dependencies": {"next": "^14.0", "react": "^18"}}),
            "pages/index.js": "export default function Home() { return <div>Hello</div> }",
        })
        assert r["framework"] == "nextjs"

    # ── Port detection ─────────────────────────────────────────────────────────

    def test_default_flask_port(self):
        r = self.detect({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        assert r["port"] == 5000

    def test_default_fastapi_port(self):
        r = self.detect({
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        assert r["port"] == 8000

    def test_port_from_env_file(self):
        r = self.detect({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
            ".env.example": "PORT=9001\nDEBUG=false\n",
        })
        assert r["port"] == 9001

    def test_port_from_source_code(self):
        r = self.detect({
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n# app.run(port=7777)\n",
        })
        assert r["port"] == 7777

    # ── Runtime version ────────────────────────────────────────────────────────

    def test_python_version_from_dotfile(self):
        r = self.detect({
            "requirements.txt": "flask\n",
            ".python-version": "3.11\n",
        })
        assert r["runtime_version"] == "3.11"

    def test_go_version_from_go_mod(self):
        r = self.detect({"go.mod": "module myapp\n\ngo 1.22\n"})
        assert r["runtime_version"] == "1.22"

    def test_node_version_from_nvmrc(self):
        r = self.detect({
            "package.json": '{"dependencies": {}}',
            ".nvmrc": "20\n",
        })
        assert r["runtime_version"] == "20"

    # ── OCI labels ─────────────────────────────────────────────────────────────

    def test_oci_labels_present(self):
        r = self.detect({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        labels = r["oci_labels"]
        assert "org.opencontainers.image.title" in labels
        assert "org.opencontainers.image.vendor" in labels
        assert "org.opencontainers.image.created" in labels
        assert labels["dev.containerforge.language"] == "python"
        assert labels["dev.containerforge.framework"] == "flask"

    # ── Confidence scoring ─────────────────────────────────────────────────────

    def test_high_confidence_with_full_signals(self):
        r = self.detect({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        assert r["confidence"] in ("high", "medium")

    def test_low_confidence_empty_dir(self):
        r = self.detect({})
        assert r["confidence"] == "low"

    # ── Start command ──────────────────────────────────────────────────────────

    def test_flask_start_command_uses_gunicorn(self):
        r = self.detect({
            "requirements.txt": "flask\ngunicorn\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        assert "gunicorn" in r["start_command"]
        assert "0.0.0.0" in r["start_command"]

    def test_fastapi_start_command_uses_uvicorn(self):
        r = self.detect({
            "requirements.txt": "fastapi\nuvicorn\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        assert "uvicorn" in r["start_command"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONFIG LOADER
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigLoader:
    """Tests for config_loader.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.config_loader import ForgeConfig, generate_example_config, load_config
        self.load_config = load_config
        self.generate_example_config = generate_example_config
        self.ForgeConfig = ForgeConfig

    def test_defaults_when_no_yaml(self):
        d = app_dir({})
        try:
            cfg = self.load_config(d)
            assert cfg.tag == "latest"
            assert cfg.platform == "linux/amd64"
            assert cfg.sidecar_port == 9090
            assert cfg.inject_health is True
            assert cfg.scan is True
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_loads_name_and_port(self):
        d = app_dir({"containerforge.yml": "name: my-api\nport: 4567\n"})
        try:
            cfg = self.load_config(d)
            assert cfg.name == "my-api"
            assert cfg.port == 4567
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_loads_databases_list(self):
        d = app_dir({"containerforge.yml": "databases:\n  - postgres\n  - redis\n"})
        try:
            cfg = self.load_config(d)
            assert "postgres" in cfg.databases
            assert "redis" in cfg.databases
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_loads_k8s_section(self):
        d = app_dir({"containerforge.yml": "k8s:\n  namespace: staging\n  replicas: 5\n  ingress: true\n  hpa: true\n"})
        try:
            cfg = self.load_config(d)
            assert cfg.k8s_namespace == "staging"
            assert cfg.k8s_replicas == 5
            assert cfg.k8s_ingress is True
            assert cfg.k8s_hpa is True
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_loads_cloud_section(self):
        d = app_dir({"containerforge.yml": "cloud:\n  provider: aws\n  region: eu-west-1\n"})
        try:
            cfg = self.load_config(d)
            assert cfg.cloud_provider == "aws"
            assert cfg.cloud_region == "eu-west-1"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_generate_example_config_has_required_keys(self):
        from containerforge.analyzer.source_detector import SourceDetector
        d = app_dir({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        try:
            detection = SourceDetector(d).detect()
            yml = self.generate_example_config(detection, d)
            assert "name:" in yml
            assert "lang:" in yml
            assert "port:" in yml
            assert "k8s:" in yml
            assert "cloud:" in yml
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_invalid_yaml_does_not_crash(self):
        d = app_dir({"containerforge.yml": "this: is: invalid: yaml: ::::\n"})
        try:
            cfg = self.load_config(d)
            assert cfg.tag == "latest"  # falls back to defaults
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 3. OCI DOCKERFILE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestOCIDockerfileGenerator:
    """Tests for generator/oci_dockerfile_gen.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.analyzer.source_detector import SourceDetector
        from containerforge.generator.oci_dockerfile_gen import OCIDockerfileGenerator
        self.Generator = OCIDockerfileGenerator
        self.Detector = SourceDetector

    def generate(self, files) -> tuple[Path, str]:
        d = app_dir(files)
        detection = self.Detector(d).detect()
        self.Generator(d, detection).generate()
        content = (d / "Dockerfile").read_text()
        return d, content

    def test_generates_dockerfile(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "FROM" in content
        assert "EXPOSE" in content

    def test_dockerfile_has_oci_labels(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "org.opencontainers.image.title" in content
        assert "org.opencontainers.image.vendor" in content
        assert "ContainerForge" in content

    def test_dockerfile_has_healthcheck(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "HEALTHCHECK" in content
        assert "/health" in content

    def test_dockerfile_has_non_root_user(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "USER" in content
        assert "1001" in content or "appuser" in content

    def test_dockerfile_has_stop_signal(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "STOPSIGNAL" in content
        assert "SIGTERM" in content

    def test_dockerfile_multistage_build(self):
        d, content = self.generate({
            "requirements.txt": "flask\ngunicorn\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        shutil.rmtree(d, ignore_errors=True)
        # Multi-stage = at least 2 FROM statements
        from_count = content.count("\nFROM ")
        assert from_count >= 1

    def test_generates_dockerignore(self):
        d = app_dir({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        detection = self.Detector(d).detect()
        self.Generator(d, detection).generate()
        assert (d / ".dockerignore").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_flask_cmd_uses_gunicorn(self):
        d, content = self.generate({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "gunicorn" in content

    def test_fastapi_cmd_uses_uvicorn(self):
        d, content = self.generate({"requirements.txt": "fastapi\nuvicorn\n", "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
        shutil.rmtree(d, ignore_errors=True)
        assert "uvicorn" in content

    def test_nodejs_dockerfile_uses_node_alpine(self):
        d, content = self.generate({
            "package.json": json.dumps({"dependencies": {"express": "^4"}, "scripts": {"start": "node index.js"}}),
            "index.js": "const express = require('express'); express().listen(3000);",
        })
        shutil.rmtree(d, ignore_errors=True)
        assert "node" in content.lower()

    def test_go_dockerfile_uses_distroless(self):
        d, content = self.generate({
            "go.mod": "module myapp\n\ngo 1.22\n\nrequire github.com/gin-gonic/gin v1.9.1\n",
            "main.go": 'package main\nimport "github.com/gin-gonic/gin"\nfunc main() { gin.Default().Run(":8080") }\n',
        })
        shutil.rmtree(d, ignore_errors=True)
        assert "distroless" in content


# ══════════════════════════════════════════════════════════════════════════════
# 4. DATABASE WIRER
# ══════════════════════════════════════════════════════════════════════════════

class TestDatabaseWirer:
    """Tests for generator/db_wirer.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.generator.db_wirer import (
            DB_SERVICES,
            detect_databases,
            render_app_env_additions,
            render_db_services,
            render_db_volumes,
            render_depends_on,
        )
        self.detect_databases = detect_databases
        self.render_db_services = render_db_services
        self.render_app_env_additions = render_app_env_additions
        self.render_depends_on = render_depends_on
        self.render_db_volumes = render_db_volumes
        self.DB_SERVICES = DB_SERVICES

    def test_detects_postgres_from_requirements(self):
        d = app_dir({
            "requirements.txt": "flask\npsycopg2-binary\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        dbs = self.detect_databases(detection, d)
        shutil.rmtree(d, ignore_errors=True)
        assert "postgres" in dbs

    def test_detects_redis_from_requirements(self):
        d = app_dir({"requirements.txt": "flask\nredis\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        dbs = self.detect_databases(detection, d)
        shutil.rmtree(d, ignore_errors=True)
        assert "redis" in dbs

    def test_detects_postgres_from_env_var(self):
        d = app_dir({
            "requirements.txt": "flask\n",
            ".env.example": "DATABASE_URL=postgresql://localhost/mydb\n",
        })
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        dbs = self.detect_databases(detection, d)
        shutil.rmtree(d, ignore_errors=True)
        assert "postgres" in dbs

    def test_renders_postgres_service_block(self):
        content = self.render_db_services(["postgres"])
        assert "postgres:16-alpine" in content
        assert "POSTGRES_DB" in content
        assert "POSTGRES_USER" in content
        assert "healthcheck" in content.lower()

    def test_renders_redis_service_block(self):
        content = self.render_db_services(["redis"])
        assert "redis:7-alpine" in content
        assert "redis-cli ping" in content

    def test_renders_app_env_vars_for_postgres(self):
        env = self.render_app_env_additions(["postgres"])
        assert "DATABASE_URL" in env

    def test_renders_app_env_vars_for_redis(self):
        env = self.render_app_env_additions(["redis"])
        assert "REDIS_URL" in env

    def test_renders_depends_on_for_healthy_db(self):
        depends = self.render_depends_on(["postgres"])
        assert "postgres" in depends
        assert "service_healthy" in depends

    def test_renders_volumes(self):
        vols = self.render_db_volumes(["postgres", "redis"])
        assert "postgres_data" in vols
        assert "redis_data" in vols

    def test_sqlite_has_no_container(self):
        # sqlite should not generate a service block (it's a file)
        content = self.render_db_services(["sqlite"])
        assert "image:" not in content

    def test_multiple_databases_rendered(self):
        content = self.render_db_services(["postgres", "redis", "mongodb"])
        assert "postgres" in content
        assert "redis" in content
        assert "mongo" in content


# ══════════════════════════════════════════════════════════════════════════════
# 5. COMPOSE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestComposeGenerator:
    """Tests for generator/compose_gen.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.generator.compose_gen import ComposeGenerator
        self.Generator = ComposeGenerator

    def test_generates_compose_file(self):
        d = app_dir({"requirements.txt": "flask\n"})
        app_info = {"language": "python", "framework": "flask", "port": 5000,
                    "has_env_file": False, "start_command": "gunicorn app:app"}
        gen = self.Generator(d, app_info, "myapp", "latest", 9090)
        gen.generate()
        assert (d / "docker-compose.yml").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_compose_has_app_and_sidecar(self):
        d = app_dir({})
        app_info = {"language": "python", "framework": "flask", "port": 5000, "has_env_file": False}
        gen = self.Generator(d, app_info, "myapp", "latest", 9090)
        gen.generate()
        content = (d / "docker-compose.yml").read_text()
        assert "myapp:" in content
        assert "sidecar:" in content
        assert "/sidecar/metrics" not in content  # should be in env
        assert "forge-net" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_compose_includes_db_services(self):
        d = app_dir({})
        app_info = {"language": "python", "framework": "flask", "port": 5000, "has_env_file": False}
        gen = self.Generator(d, app_info, "myapp", "latest", 9090, databases=["postgres", "redis"])
        gen.generate()
        content = (d / "docker-compose.yml").read_text()
        assert "postgres:" in content
        assert "redis:" in content
        assert "DATABASE_URL" in content
        assert "REDIS_URL" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_compose_has_healthcheck(self):
        d = app_dir({})
        app_info = {"language": "python", "framework": "flask", "port": 5000, "has_env_file": False}
        gen = self.Generator(d, app_info, "myapp", "latest", 9090)
        gen.generate()
        content = (d / "docker-compose.yml").read_text()
        assert "healthcheck:" in content
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 6. KUBERNETES GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestK8sGenerator:
    """Tests for k8s/k8s_gen.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.config_loader import ForgeConfig
        from containerforge.k8s.k8s_gen import K8sGenerator
        self.Generator = K8sGenerator
        self.ForgeConfig = ForgeConfig

    def _gen(self, extra_config=None):
        d = app_dir({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp=Flask(__name__)\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp", k8s_namespace="test-ns", k8s_replicas=2)
        if extra_config:
            for k, v in extra_config.items():
                setattr(cfg, k, v)
        gen = self.Generator(d, detection, cfg, "myapp:latest")
        k8s_dir = gen.generate()
        return d, k8s_dir

    def test_creates_k8s_directory(self):
        d, k8s_dir = self._gen()
        assert k8s_dir.exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_generates_required_manifests(self):
        d, k8s_dir = self._gen()
        required = ["00-namespace.yaml", "04-deployment.yaml", "05-service.yaml",
                    "06-networkpolicy.yaml", "07-pdb.yaml"]
        for f in required:
            assert (k8s_dir / f).exists(), f"Missing {f}"
        shutil.rmtree(d, ignore_errors=True)

    def test_deployment_has_health_probes(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "04-deployment.yaml").read_text()
        assert "livenessProbe" in content
        assert "readinessProbe" in content
        assert "startupProbe" in content
        assert "/health" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_deployment_has_resource_limits(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "04-deployment.yaml").read_text()
        assert "limits:" in content
        assert "requests:" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_deployment_runs_as_non_root(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "04-deployment.yaml").read_text()
        assert "runAsNonRoot: true" in content
        assert "1001" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_deployment_namespace(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "00-namespace.yaml").read_text()
        assert "test-ns" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_secret_template_has_warning(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "03-secret.yaml").read_text()
        assert "DO NOT commit" in content or "DO NOT" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_ingress_generated_when_enabled(self):
        d, k8s_dir = self._gen({"k8s_ingress": True, "k8s_ingress_host": "api.example.com"})
        assert (k8s_dir / "08-ingress.yaml").exists()
        content = (k8s_dir / "08-ingress.yaml").read_text()
        assert "api.example.com" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_hpa_generated_when_enabled(self):
        d, k8s_dir = self._gen({"k8s_hpa": True, "k8s_min_replicas": 2, "k8s_max_replicas": 10})
        assert (k8s_dir / "09-hpa.yaml").exists()
        content = (k8s_dir / "09-hpa.yaml").read_text()
        assert "minReplicas: 2" in content
        assert "maxReplicas: 10" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_network_policy_deny_all(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "06-networkpolicy.yaml").read_text()
        assert "Ingress" in content
        assert "Egress" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_kustomization_lists_all_files(self):
        d, k8s_dir = self._gen()
        content = (k8s_dir / "kustomization.yaml").read_text()
        assert "00-namespace.yaml" in content
        assert "04-deployment.yaml" in content
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 7. CICD PIPELINE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestCICDGenerator:
    """Tests for cicd/pipeline_gen.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.cicd.pipeline_gen import CICDGenerator
        from containerforge.config_loader import ForgeConfig
        self.Generator = CICDGenerator
        self.ForgeConfig = ForgeConfig

    def _make(self, lang="python", framework="flask"):
        d = app_dir({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp=Flask(__name__)\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        detection["language"] = lang
        detection["framework"] = framework
        cfg = self.ForgeConfig(name="myapp")
        gen = self.Generator(d, detection, cfg)
        return d, gen

    def test_github_actions_file_created(self):
        d, gen = self._make()
        gen.generate_github_actions()
        assert (d / ".github/workflows/containerforge.yml").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_github_actions_has_trivy(self):
        d, gen = self._make()
        gen.generate_github_actions()
        content = (d / ".github/workflows/containerforge.yml").read_text()
        assert "trivy" in content.lower()
        shutil.rmtree(d, ignore_errors=True)

    def test_github_actions_has_sbom_step(self):
        d, gen = self._make()
        gen.generate_github_actions()
        content = (d / ".github/workflows/containerforge.yml").read_text()
        assert "sbom" in content.lower() or "cyclonedx" in content.lower()
        shutil.rmtree(d, ignore_errors=True)

    def test_gitlab_ci_file_created(self):
        d, gen = self._make()
        gen.generate_gitlab_ci()
        assert (d / ".gitlab-ci.yml").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_gitlab_ci_has_stages(self):
        d, gen = self._make()
        gen.generate_gitlab_ci()
        content = (d / ".gitlab-ci.yml").read_text()
        assert "stages:" in content
        assert "build" in content
        assert "push" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_jenkinsfile_created(self):
        d, gen = self._make()
        gen.generate_jenkins()
        assert (d / "Jenkinsfile").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_jenkinsfile_declarative_pipeline(self):
        d, gen = self._make()
        gen.generate_jenkins()
        content = (d / "Jenkinsfile").read_text()
        assert "pipeline {" in content
        assert "stages {" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_node_pipeline_uses_node_setup(self):
        d, gen = self._make(lang="nodejs", framework="express")
        gen.generate_github_actions()
        content = (d / ".github/workflows/containerforge.yml").read_text()
        assert "setup-node" in content
        shutil.rmtree(d, ignore_errors=True)

    def test_go_pipeline_uses_go_setup(self):
        d, gen = self._make(lang="go", framework="gin")
        gen.generate_github_actions()
        content = (d / ".github/workflows/containerforge.yml").read_text()
        assert "setup-go" in content
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 8. CLOUD DEPLOYER (IaC generation only — no actual deploy)
# ══════════════════════════════════════════════════════════════════════════════

class TestCloudDeployer:
    """Tests for cloud/cloud_deployer.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.cloud.cloud_deployer import CloudDeployer
        from containerforge.config_loader import ForgeConfig
        self.Deployer = CloudDeployer
        self.ForgeConfig = ForgeConfig

    def _make(self, provider, region=None):
        d = app_dir({"requirements.txt": "flask\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp", cloud_provider=provider, cloud_region=region)
        dep = self.Deployer(d, detection, cfg, "myapp:latest")
        return d, dep

    def test_aws_generates_task_definition(self):
        d, dep = self._make("aws", "us-east-1")
        files = dep.generate_iac()
        assert "ecs-task-definition.json" in files
        task_def = json.loads(files["ecs-task-definition.json"])
        assert task_def["family"] == "myapp"
        assert task_def["requiresCompatibilities"] == ["FARGATE"]
        shutil.rmtree(d, ignore_errors=True)

    def test_aws_generates_deploy_script(self):
        d, dep = self._make("aws")
        files = dep.generate_iac()
        assert "deploy-aws.sh" in files
        assert "ECR" in files["deploy-aws.sh"]
        shutil.rmtree(d, ignore_errors=True)

    def test_aws_generates_cloudformation(self):
        d, dep = self._make("aws")
        files = dep.generate_iac()
        assert "cf-stack.yaml" in files
        assert "ECSCluster" in files["cf-stack.yaml"]
        shutil.rmtree(d, ignore_errors=True)

    def test_gcp_generates_cloudrun_yaml(self):
        d, dep = self._make("gcp", "us-central1")
        files = dep.generate_iac()
        assert "cloudrun-service.yaml" in files
        assert "serving.knative.dev" in files["cloudrun-service.yaml"]
        shutil.rmtree(d, ignore_errors=True)

    def test_azure_generates_bicep(self):
        d, dep = self._make("azure")
        files = dep.generate_iac()
        assert "main.bicep" in files
        assert "containerApps" in files["main.bicep"] or "Container" in files["main.bicep"]
        shutil.rmtree(d, ignore_errors=True)

    def test_fly_generates_fly_toml(self):
        d, dep = self._make("fly")
        files = dep.generate_iac()
        assert "fly.toml" in files
        assert "app = " in files["fly.toml"]
        assert "myapp" in files["fly.toml"]
        shutil.rmtree(d, ignore_errors=True)

    def test_files_written_to_disk(self):
        d, dep = self._make("fly")
        dep.generate_iac()
        assert (d / ".containerforge/cloud/fly.toml").exists()
        shutil.rmtree(d, ignore_errors=True)

    def test_health_check_in_aws_task_def(self):
        d, dep = self._make("aws")
        files = dep.generate_iac()
        task_def = json.loads(files["ecs-task-definition.json"])
        container = task_def["containerDefinitions"][0]
        assert "healthCheck" in container
        assert "/health" in str(container["healthCheck"])
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 9. GRAFANA DASHBOARD GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestGrafanaGenerator:
    """Tests for grafana/dashboard_gen.py"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from containerforge.config_loader import ForgeConfig
        from containerforge.grafana.dashboard_gen import GrafanaGenerator
        self.Generator = GrafanaGenerator
        self.ForgeConfig = ForgeConfig

    def test_generates_dashboard_json(self):
        d = app_dir({"requirements.txt": "flask\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp")
        gen = self.Generator(d, cfg, detection)
        out = gen.generate()
        assert out.exists()
        dashboard = json.loads(out.read_text())
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 0
        shutil.rmtree(d, ignore_errors=True)

    def test_dashboard_has_required_fields(self):
        d = app_dir({"requirements.txt": "flask\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp")
        gen = self.Generator(d, cfg, detection)
        out = gen.generate()
        dashboard = json.loads(out.read_text())
        assert "title" in dashboard
        assert "uid" in dashboard
        assert "refresh" in dashboard
        shutil.rmtree(d, ignore_errors=True)

    def test_dashboard_panels_have_prometheus_targets(self):
        d = app_dir({"requirements.txt": "flask\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp")
        gen = self.Generator(d, cfg, detection)
        out = gen.generate()
        dashboard = json.loads(out.read_text())
        # Check that panels have datasource targets
        for panel in dashboard["panels"]:
            assert "targets" in panel
            for target in panel["targets"]:
                assert "expr" in target
        shutil.rmtree(d, ignore_errors=True)

    def test_generates_provisioning_config(self):
        d = app_dir({"requirements.txt": "flask\n"})
        from containerforge.analyzer.source_detector import SourceDetector
        detection = SourceDetector(d).detect()
        cfg = self.ForgeConfig(name="myapp")
        gen = self.Generator(d, cfg, detection)
        gen.generate()
        prov = d / ".containerforge/grafana-provisioning.yml"
        assert prov.exists()
        assert "ContainerForge" in prov.read_text()
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 10. INTEGRATION — Full pipeline end-to-end (no docker required)
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end tests that run the full generate pipeline (no docker/trivy needed)."""

    def test_flask_full_pipeline(self):
        """Flask app: detect + dockerfile + compose + k8s + cicd + cloud + grafana"""
        from containerforge.analyzer.source_detector import SourceDetector
        from containerforge.cicd.pipeline_gen import CICDGenerator
        from containerforge.cloud.cloud_deployer import CloudDeployer
        from containerforge.config_loader import ForgeConfig
        from containerforge.generator.compose_gen import ComposeGenerator
        from containerforge.generator.db_wirer import detect_databases
        from containerforge.generator.oci_dockerfile_gen import OCIDockerfileGenerator
        from containerforge.grafana.dashboard_gen import GrafanaGenerator
        from containerforge.k8s.k8s_gen import K8sGenerator

        d = app_dir({
            "requirements.txt": "flask\npsycopg2-binary\nredis\ngunicorn\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n@app.route('/health')\ndef h(): return 'ok'\n",
            ".env.example": "DATABASE_URL=postgresql://localhost/mydb\nSECRET_KEY=changeme\n",
        })

        detection = SourceDetector(d).detect()
        assert detection["language"] == "python"
        assert detection["framework"] == "flask"

        # Dockerfile
        OCIDockerfileGenerator(d, detection).generate()
        assert (d / "Dockerfile").exists()

        # DB detection
        dbs = detect_databases(detection, d)
        assert "postgres" in dbs
        assert "redis" in dbs

        # Compose with DBs
        cfg = ForgeConfig(name="flask-app", k8s_namespace="prod", k8s_replicas=3,
                          env_secrets=["DATABASE_URL", "SECRET_KEY"])
        app_info = {"language": "python", "framework": "flask", "port": 5000, "has_env_file": True}
        ComposeGenerator(d, app_info, "flask-app", "latest", 9090, dbs, cfg).generate()
        compose = (d / "docker-compose.yml").read_text()
        assert "postgres:" in compose
        assert "redis:" in compose

        # K8s
        K8sGenerator(d, detection, cfg, "flask-app:latest").generate()
        assert (d / "k8s/04-deployment.yaml").exists()
        dep = (d / "k8s/04-deployment.yaml").read_text()
        assert "SECRET_KEY" in dep  # secret should appear in deployment

        # CI/CD
        CICDGenerator(d, detection, cfg).generate_github_actions()
        assert (d / ".github/workflows/containerforge.yml").exists()

        # Grafana
        GrafanaGenerator(d, cfg, detection).generate()
        assert (d / ".containerforge/grafana-dashboard.json").exists()

        # Cloud IaC
        cfg.cloud_provider = "fly"
        CloudDeployer(d, detection, cfg, "flask-app:latest").generate_iac()
        assert (d / ".containerforge/cloud/fly.toml").exists()

        shutil.rmtree(d, ignore_errors=True)

    def test_nodejs_full_pipeline(self):
        """Express app: full generate pipeline"""
        from containerforge.analyzer.source_detector import SourceDetector
        from containerforge.config_loader import ForgeConfig
        from containerforge.generator.oci_dockerfile_gen import OCIDockerfileGenerator
        from containerforge.k8s.k8s_gen import K8sGenerator

        d = app_dir({
            "package.json": json.dumps({
                "name": "my-api",
                "dependencies": {"express": "^4.18", "mongoose": "^8"},
                "scripts": {"start": "node index.js"},
            }),
            "index.js": "const express = require('express');\nconst app = express();\napp.listen(3000);\n",
        })

        detection = SourceDetector(d).detect()
        assert detection["language"] == "nodejs"
        assert detection["framework"] == "express"
        assert detection["port"] == 3000

        OCIDockerfileGenerator(d, detection).generate()
        df = (d / "Dockerfile").read_text()
        assert "node" in df.lower()
        assert "tini" in df  # Node images should use tini

        cfg = ForgeConfig(name="node-api")
        K8sGenerator(d, detection, cfg, "node-api:latest").generate()
        assert (d / "k8s").exists()

        shutil.rmtree(d, ignore_errors=True)

    def test_go_full_pipeline(self):
        """Gin app: Go with distroless image"""
        from containerforge.analyzer.source_detector import SourceDetector
        from containerforge.generator.oci_dockerfile_gen import OCIDockerfileGenerator

        d = app_dir({
            "go.mod": "module myapp\n\ngo 1.22\n\nrequire github.com/gin-gonic/gin v1.9.1\n",
            "main.go": 'package main\nimport "github.com/gin-gonic/gin"\nfunc main() { gin.Default().Run(":8080") }\n',
        })

        detection = SourceDetector(d).detect()
        assert detection["language"] == "go"
        assert detection["framework"] == "gin"

        OCIDockerfileGenerator(d, detection).generate()
        df = (d / "Dockerfile").read_text()
        assert "distroless" in df
        assert "CGO_ENABLED=0" in df  # static binary required for distroless

        shutil.rmtree(d, ignore_errors=True)
