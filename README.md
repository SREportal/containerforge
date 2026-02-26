<div align="center">

```
  ██████╗ ██████╗ ███╗  ██╗████████╗ █████╗ ██╗███╗  ██╗███████╗██████╗  ██████╗ ███████╗
 ██╔════╝██╔═══██╗████╗ ██║╚══██╔══╝██╔══██╗██║████╗ ██║██╔════╝██╔══██╗██╔════╝ ██╔════╝
 ██║     ██║   ██║██╔██╗██║   ██║   ███████║██║██╔██╗██║█████╗  ██████╔╝██║  ███╗█████╗
 ██║     ██║   ██║██║╚████║   ██║   ██╔══██║██║██║╚████║██╔══╝  ██╔══██╗██║   ██║██╔══╝
 ╚██████╗╚██████╔╝██║ ╚███║   ██║   ██║  ██║██║██║ ╚███║███████╗██║  ██║╚██████╔╝███████╗
  ╚═════╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

**Containerize anything. Ship everywhere.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://python.org)
[![Version](https://img.shields.io/badge/version-2.0.0-brightgreen)](CHANGELOG.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

[Installation](#installation) · [Quick Start](#quick-start) · [Commands](#commands) · [Config](#configuration) · [Contributing](#contributing)

</div>

---

ContainerForge detects your app's language and framework, generates an OCI-compliant multi-stage Dockerfile, wires up databases, adds a self-healing sidecar with Prometheus metrics, and ships Kubernetes manifests and CI/CD pipelines — all from a single command.

## What it does

```
containerforge build ./my-api
```

That one command:

1. **Detects** language + framework (Python/Node/Go/Java/Ruby/Rust/PHP/.NET, 40+ frameworks)
2. **Generates** an OCI-compliant multi-stage Dockerfile (distroless for Go/Rust, slim for everything else)
3. **Injects** `/health` and `/telemetry` endpoints (Python apps, zero code changes)
4. **Wires** detected databases (postgres, mysql, redis, mongo, elastic, kafka, rabbitmq) into docker-compose
5. **Deploys** a sidecar watchdog that auto-restarts failed containers and exports Prometheus metrics
6. **Scans** the built image with Trivy for CVEs before you push
7. **Builds** and launches everything with `docker compose up -d`

Optional flags unlock more:

```bash
containerforge build ./my-api --with-k8s --with-cicd --with-dash --push docker.io/myorg
```

## Installation

```bash
pip install containerforge
```

Or install from source:

```bash
git clone https://github.com/containerforge/containerforge
cd containerforge
pip install -e .
```

**Optional dependencies:**

| Feature | Requirement |
|---|---|
| Vulnerability scanning | [Trivy](https://aquasecurity.github.io/trivy/) |
| AI analysis | `ANTHROPIC_API_KEY` environment variable |
| Cloud deploy | `aws`/`gcloud`/`az`/`fly` CLIs |
| Kubernetes | `kubectl` |

## Quick Start

```bash
# Detect what you have
containerforge detect ./my-app

# Generate all files + build + run
containerforge build ./my-app

# Generate files only (no docker build)
containerforge build ./my-app --no-build

# Full pipeline: k8s + CI/CD + Grafana + push
containerforge build ./my-app \
  --with-k8s --with-cicd --with-dash \
  --push docker.io/myorg

# Write a containerforge.yml to commit to version control
containerforge init ./my-app
```

## Commands

| Command | Description |
|---|---|
| `build` | Detect + containerize + build + run |
| `detect` | Scan source dir, report language/framework/OCI metadata |
| `init` | Write a starter `containerforge.yml` |
| `scan` | Run Trivy vulnerability scan |
| `k8s` | Generate Kubernetes manifests |
| `cicd` | Generate CI/CD pipelines (GitHub Actions, GitLab CI, Jenkins) |
| `deploy` | Deploy to cloud (aws / gcp / azure / fly) |
| `dashboard` | Generate Grafana dashboard + Prometheus config |
| `analyze` | AI-powered containerization quality analysis |
| `clean` | Remove all generated files |
| `list-supported` | Show all supported languages, frameworks, clouds |

### `build`

```bash
containerforge build ./my-app [OPTIONS]

Options:
  -n, --name TEXT          Image/service name (default: directory name)
  -p, --port INT           Override detected port
  -t, --tag TEXT           Docker image tag (default: latest)
  -l, --lang TEXT          Override language detection
  -f, --framework TEXT     Override framework detection
      --platform TEXT      OCI target platform (default: linux/amd64)
      --no-inject          Skip /health endpoint injection
      --no-scan            Skip Trivy scan
      --no-build           Generate files only
      --no-run             Build image but skip compose up
      --with-k8s           Also generate Kubernetes manifests
      --with-cicd          Also generate CI/CD pipelines
      --with-dash          Also generate Grafana dashboard
      --push TEXT          Push to registry after build
      --ai                 Run LLM analysis (requires ANTHROPIC_API_KEY)
```

### `k8s`

```bash
containerforge k8s ./my-app --namespace production --replicas 3 --ingress --hpa
```

Generates `k8s/` with:
- `00-namespace.yaml` — Namespace
- `01-serviceaccount.yaml` — ServiceAccount (no token automount)
- `02-configmap.yaml` — Non-sensitive env vars
- `03-secret.yaml` — Secret template (never commit real values)
- `04-deployment.yaml` — Deployment with liveness/readiness/startup probes, resource limits, anti-affinity, seccomp
- `05-service.yaml` — ClusterIP Service
- `06-networkpolicy.yaml` — Deny-all NetworkPolicy with explicit allowances
- `07-pdb.yaml` — PodDisruptionBudget (minAvailable: 1)
- `08-ingress.yaml` — Ingress with cert-manager TLS (optional)
- `09-hpa.yaml` — HorizontalPodAutoscaler (optional)
- `kustomization.yaml` — Kustomize entry point

### `cicd`

```bash
containerforge cicd ./my-app --provider github
```

Generates pipelines with stages: **test → build → scan (Trivy/SARIF) → push → deploy**

- **GitHub Actions** — `.github/workflows/containerforge.yml`
  - Uploads Trivy results to GitHub Security tab
  - Generates + uploads SBOM artifact
  - Multi-platform builds (amd64 + arm64) on push to main
- **GitLab CI** — `.gitlab-ci.yml`
  - Container scanning report
  - Manual deploy gate to production
- **Jenkins** — `Jenkinsfile` (declarative pipeline)

### `deploy`

```bash
containerforge deploy ./my-app --provider aws --region us-east-1
```

| Provider | Service | IaC |
|---|---|---|
| `aws` | ECS Fargate | CloudFormation + deploy script |
| `gcp` | Cloud Run | Cloud Run YAML + deploy script |
| `azure` | Container Apps | Bicep + deploy script |
| `fly` | Fly.io Machines | fly.toml + deploy script |

Use `--gen-only` to write IaC files without executing the deploy.

### `analyze`

```bash
export ANTHROPIC_API_KEY=sk-ant-...
containerforge analyze ./my-app
```

Uses Claude to review your Dockerfile and source code. Returns:
- Production readiness score (0–100) with breakdown by category
- Security issues (hardcoded secrets, non-root user, missing caps)
- Dockerfile optimizations (layer caching, image size, multi-stage)
- Top 5 ranked recommendations with code snippets

## Configuration

Create `containerforge.yml` in your app directory (or run `containerforge init ./my-app`):

```yaml
# containerforge.yml — commit this to version control
name: my-api
lang: python
framework: flask
port: 5000
tag: latest
platform: linux/amd64

# Observability
sidecar_port: 9090
inject_health: true

# Security
scan: true
sbom: false

# Databases (auto-detected, or specify explicitly)
databases:
  - postgres
  - redis

# Secrets to expose as env vars
env_secrets:
  - DATABASE_URL
  - SECRET_KEY

# Registry
push_registry: docker.io/myorg

# Kubernetes
k8s:
  namespace: production
  replicas: 3
  ingress: true
  ingress_host: api.example.com
  hpa: true
  min_replicas: 2
  max_replicas: 20

# Cloud deploy
cloud:
  provider: aws
  region: us-east-1
```

CLI flags always override `containerforge.yml` values.

## Supported Languages & Frameworks

| Language | Frameworks | Runtime Image |
|---|---|---|
| Python | Flask, FastAPI, Django, Starlette, Tornado, aiohttp, Sanic, Bottle, Litestar | python:3.x-slim |
| Node.js | Express, Fastify, Next.js, NestJS, Koa, Hapi, Nuxt | node:20-alpine |
| Go | Gin, Echo, Fiber, Chi, Gorilla Mux, net/http | distroless/static |
| Java | Spring Boot, Quarkus, Micronaut, Vert.x | temurin:21-jre-alpine |
| Ruby | Rails, Sinatra, Hanami, Grape | ruby:3.x-slim |
| Rust | Actix-web, Axum, Warp, Rocket | distroless/cc |
| PHP | Laravel, Symfony, Slim, Lumen | php:8.x-fpm-alpine |
| .NET | ASP.NET Core, Blazor | dotnet/aspnet:8.0-alpine |

## Auto-detected Databases

ContainerForge scans your dependency files and env vars to detect:

| Database | Image | Auto-wired env var |
|---|---|---|
| PostgreSQL | postgres:16-alpine | DATABASE_URL |
| MySQL | mysql:8-oracle | DATABASE_URL |
| Redis | redis:7-alpine | REDIS_URL |
| MongoDB | mongo:7 | MONGODB_URI |
| Elasticsearch | elasticsearch:8.x | ELASTICSEARCH_URL |
| RabbitMQ | rabbitmq:3-management | RABBITMQ_URL |
| Apache Kafka | confluentinc/cp-kafka:7.x | KAFKA_BROKERS |

## Sidecar Watchdog

Every app gets a FastAPI sidecar container that:

- Polls `/health` every 10 seconds
- Auto-restarts the app container after 3 consecutive failures (via Docker socket)
- Exports Prometheus metrics at `:9090/sidecar/metrics`
- Serves status/history at `:9090/sidecar/status`
- Optionally sends webhook alerts (Slack/PagerDuty)

## OCI Compliance

All generated Dockerfiles follow the [OCI Image Spec](https://specs.opencontainers.org/image-spec/):

- `org.opencontainers.image.*` labels on every image
- `syntax=docker/dockerfile:1.6` BuildKit header
- `STOPSIGNAL SIGTERM` on every image
- Fixed UID/GID non-root user (`1001:1001`)
- `--platform` ARG for cross-architecture builds
- Multi-stage builds with minimal runtime layers

## Contributing

We welcome contributions of all kinds. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

**Good first issues:**

- Add a new language or framework to `analyzer/source_detector.py`
- Add a new database to `generator/db_wirer.py`
- Improve Kubernetes resource presets
- Add a new cloud provider to `cloud/cloud_deployer.py`

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

<div align="center">
Built with ❤️  by the ContainerForge community
</div>
