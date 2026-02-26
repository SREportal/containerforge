# Changelog

All notable changes to ContainerForge are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [2.1.0] — 2026-02-26

### Added
- Proper Python package structure (`containerforge/` subdirectory) for clean `pip install`
- `pyproject.toml` replaces legacy `setup.py` as primary packaging config (PEP 621)
- `forge` short alias — `forge build .` works alongside `containerforge build .`
- `containerforge[ai]` and `containerforge[all]` optional dependency extras
- Full test suite (`tests/test_all.py`) — 35 tests across all 10 modules
- GitHub Actions CI: test matrix Python 3.9–3.12, lint with ruff, auto-publish to PyPI on tag
- `.gitignore` tuned for Python + Docker development

### Fixed
- All internal imports now use fully-qualified `containerforge.*` paths (pip-install safe)
- Removed `sys.path.insert` hack from CLI entry point
- `rich` imports moved inside functions in non-CLI modules (no heavy deps at import time)
- Stray directory artifact from build tooling removed

### Changed
- `containerforge.py` → `containerforge/cli.py` (entry point unchanged for users)
- `setup.py` kept as shim for compatibility; `pyproject.toml` is source of truth

---

## [2.0.0] — 2026-02-26

### Added
- Cloud deploy: AWS ECS Fargate, GCP Cloud Run, Azure Container Apps, Fly.io
- IaC generation: CloudFormation, Cloud Run YAML, Bicep, fly.toml
- SBOM generation (CycloneDX format via Trivy)
- Grafana dashboard pre-wired to sidecar metrics + Prometheus config
- LLM-powered analysis (`containerforge analyze`) via Anthropic API — 0–100 score, ranked issues, recommendations
- `containerforge init` — generate `containerforge.yml` from detection results
- `--ai` flag on `build` for inline analysis
- `containerforge deploy --gen-only` — write IaC without executing
- `grafana/dashboard_gen.py` — 10+ panels: health, availability, requests, errors, latency, memory, CPU, restarts

### Changed
- Complete CLI rewrite: 780-line `containerforge.py` with 11 commands
- `build` now runs a 14-step pipeline with `--with-k8s`, `--with-cicd`, `--with-dash`, `--ai` flags
- `generator/compose_gen.py` updated to accept databases list and inject service blocks

---

## [1.3.0] — 2026-02-25

### Added
- Kubernetes manifests: Namespace, ServiceAccount, ConfigMap, Secret template, Deployment, Service, NetworkPolicy, PodDisruptionBudget
- Optional Ingress with cert-manager TLS annotations
- Optional HPA with CPU/memory scaling targets
- `kustomization.yaml` for all generated manifests
- Secret management: env vars classified as secrets injected via K8s Secret + envFrom

---

## [1.2.0] — 2026-02-25

### Added
- Database auto-wiring: postgres, mysql, redis, mongodb, elasticsearch, rabbitmq, kafka
- Auto-detection from dependency files and env var patterns
- CI/CD pipeline generation: GitHub Actions, GitLab CI, Jenkinsfile
- Trivy vulnerability scanning in all three pipelines (SARIF upload, container scanning report)

---

## [1.1.0] — 2026-02-25

### Added
- Multi-language detection: Python, Node.js, Go, Java, Ruby, Rust, PHP, .NET
- 40+ framework fingerprints
- `containerforge.yml` config file support
- `vuln_scanner.py` wrapping Trivy with JSON output and severity bucketing

---

## [1.0.0] — 2026-02-25

### Added
- Initial release
- Python app detection (Flask, FastAPI, Django)
- OCI-compliant multi-stage Dockerfile generation
- Health endpoint injection for Python frameworks
- Sidecar watchdog container with Prometheus metrics
- `docker-compose.yml` generation with sidecar wiring
- Commands: `build`, `detect`, `clean`, `list-supported`
