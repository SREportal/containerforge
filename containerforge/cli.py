#!/usr/bin/env python3
"""
  ██████╗ ██████╗ ███╗  ██╗████████╗ █████╗ ██╗███╗  ██╗███████╗██████╗  ██████╗ ███████╗
 ██╔════╝██╔═══██╗████╗ ██║╚══██╔══╝██╔══██╗██║████╗ ██║██╔════╝██╔══██╗██╔════╝ ██╔════╝
 ██║     ██║   ██║██╔██╗██║   ██║   ███████║██║██╔██╗██║█████╗  ██████╔╝██║  ███╗█████╗
 ██║     ██║   ██║██║╚████║   ██║   ██╔══██║██║██║╚████║██╔══╝  ██╔══██╗██║   ██║██╔══╝
 ╚██████╗╚██████╔╝██║ ╚███║   ██║   ██║  ██║██║██║ ╚███║███████╗██║  ██║╚██████╔╝███████╗
  ╚═════╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝

ContainerForge — Containerize anything. Ship everywhere.

Version   : 2.1.0
License   : Apache 2.0
Docs      : https://containerforge.dev
Source    : https://github.com/containerforge/containerforge

Commands:
  build          Detect + containerize + (optionally) build & run
  detect         Scan source directory, report language/framework/OCI metadata
  init           Write a starter containerforge.yml into an app directory
  scan           Run Trivy vulnerability scan against a built image
  k8s            Generate Kubernetes manifests (Deployment, Service, Ingress, HPA...)
  cicd           Generate CI/CD pipeline files (GitHub Actions, GitLab CI, Jenkins)
  deploy         Deploy to cloud (aws | gcp | azure | fly)
  dashboard      Generate Grafana dashboard + Prometheus config
  analyze        AI-powered analysis of containerization quality (requires ANTHROPIC_API_KEY)
  clean          Remove all ContainerForge-generated files
  list-supported Show all supported languages and frameworks
"""

import sys
import os
import json as _json
import subprocess
import shutil

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box


from analyzer.source_detector  import SourceDetector, FRAMEWORK_PATTERNS, DEFAULT_PORTS
from analyzer.app_analyzer      import AppAnalyzer
from analyzer.detection_report  import print_detection_report
from config_loader              import load_config, generate_example_config, ForgeConfig
from containerforge.generator.oci_dockerfile_gen import OCIDockerfileGenerator
from generator.compose_gen      import ComposeGenerator
from generator.sidecar_gen      import SidecarGenerator
from generator.db_wirer         import detect_databases, DB_SERVICES
from injector.health_injector   import HealthInjector
from scanner.vuln_scanner       import VulnScanner
from cicd.pipeline_gen          import CICDGenerator
from k8s.k8s_gen                import K8sGenerator
from grafana.dashboard_gen      import GrafanaGenerator
from cloud.llm_analyzer         import LLMAnalyzer
from cloud.cloud_deployer       import CloudDeployer, PROVIDERS

console = Console()

BANNER = """[bold cyan]
  ██████╗ ██████╗ ███╗  ██╗████████╗ █████╗ ██╗███╗  ██╗███████╗██████╗  ██████╗ ███████╗
 ██╔════╝██╔═══██╗████╗ ██║╚══██╔══╝██╔══██╗██║████╗ ██║██╔════╝██╔══██╗██╔════╝ ██╔════╝
 ██║     ██║   ██║██╔██╗██║   ██║   ███████║██║██╔██╗██║█████╗  ██████╔╝██║  ███╗█████╗  
 ██║     ██║   ██║██║╚████║   ██║   ██╔══██║██║██║╚████║██╔══╝  ██╔══██╗██║   ██║██╔══╝  
 ╚██████╗╚██████╔╝██║ ╚███║   ██║   ██║  ██║██║██║ ╚███║███████╗██║  ██║╚██████╔╝███████╗
  ╚═════╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
[/bold cyan]
[dim]  v2.1.0  ·  Containerize anything. Ship everywhere.  ·  apache-2.0[/dim]
[dim]  https://github.com/containerforge/containerforge[/dim]
"""

SUPPORTED_LANGS = ["python","nodejs","go","java","ruby","rust","php","dotnet","auto"]


# ─── CLI group ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option("2.1.0", prog_name="containerforge")
def cli():
    """ContainerForge — Containerize anything. Ship everywhere.\n\nRun `containerforge COMMAND --help` for detailed usage."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--name",       "-n", default=None,   help="Image/service name (default: dir name)")
@click.option("--port",       "-p", default=None, type=int, help="Override detected port")
@click.option("--tag",        "-t", default=None,   help="Docker image tag")
@click.option("--lang",       "-l", default=None,   type=click.Choice(SUPPORTED_LANGS, case_sensitive=False),
              help="Override language detection")
@click.option("--framework",  "-f", default=None,   help="Override framework detection")
@click.option("--platform",         default=None,   help="OCI target platform (default: linux/amd64)")
@click.option("--no-inject",  is_flag=True,         help="Skip health/telemetry injection (Python)")
@click.option("--no-scan",    is_flag=True,         help="Skip vulnerability scan")
@click.option("--no-build",   is_flag=True,         help="Generate files only, skip docker build")
@click.option("--no-run",     is_flag=True,         help="Skip docker compose up")
@click.option("--with-k8s",   is_flag=True,         help="Also generate Kubernetes manifests")
@click.option("--with-cicd",  is_flag=True,         help="Also generate CI/CD pipelines")
@click.option("--with-dash",  is_flag=True,         help="Also generate Grafana dashboard")
@click.option("--push",             default=None,   help="Push image to registry after build")
@click.option("--ai",         is_flag=True,         help="Run LLM analysis (requires ANTHROPIC_API_KEY)")
def build(app_path, name, port, tag, lang, framework, platform, no_inject, no_scan,
          no_build, no_run, with_k8s, with_cicd, with_dash, push, ai):
    """Detect, containerize, and optionally deploy any application.

    \b
    Reads containerforge.yml if present — CLI flags take precedence.

    \b
    Examples:
      containerforge build ./my-api
      containerforge build ./my-api --with-k8s --with-cicd
      containerforge build ./my-api --no-build --with-k8s
      containerforge build ./my-api --push docker.io/myorg --ai
    """
    console.print(BANNER)
    app_path = Path(app_path).resolve()

    # ── Load config (containerforge.yml wins, CLI flags override) ─────────────
    cfg = load_config(app_path)
    if name:      cfg.name = name
    if tag:       cfg.tag = tag
    if platform:  cfg.platform = platform
    if push:      cfg.push_registry = push
    if no_scan:   cfg.scan = False

    if not cfg.name:
        cfg.name = app_path.name.lower().replace(" ", "-").replace("_", "-")

    console.print(Panel(
        f"[bold]Source:[/bold]   {app_path}\n"
        f"[bold]Image:[/bold]    [cyan]{cfg.name}:{cfg.tag}[/cyan]\n"
        f"[bold]Platform:[/bold] {cfg.platform}",
        title="[bold cyan]🔥 ContainerForge Build[/bold cyan]",
        border_style="cyan",
    ))

    # ── 1. Detect ──────────────────────────────────────────────────────────────
    _step("1", "Detecting language & framework")
    detection = SourceDetector(app_path).detect()
    if lang and lang != "auto": _override_lang(detection, lang)
    if framework:               _override_fw(detection, framework)
    if port:                    detection["port"] = port
    if cfg.lang and cfg.lang != "auto" and not lang: _override_lang(detection, cfg.lang)
    if cfg.framework and not framework:              _override_fw(detection, cfg.framework)
    if cfg.port and not port:                        detection["port"] = cfg.port
    _print_detect_line(detection)

    # ── 2. Database detection ─────────────────────────────────────────────────
    _step("2", "Detecting databases")
    if cfg.databases:
        databases = cfg.databases
        console.print(f"  📋 Using config: [cyan]{', '.join(databases)}[/cyan]")
    else:
        databases = detect_databases(detection, app_path)
        if databases:
            console.print(f"  🗄️  Auto-detected: [cyan]{', '.join(databases)}[/cyan]")
        else:
            console.print("  [dim]No databases detected[/dim]")

    # ── 3. Health injection (Python) ──────────────────────────────────────────
    _step("3", "Health endpoint injection")
    language = detection.get("language", "unknown")
    if language == "python" and not no_inject and cfg.inject_health:
        res = HealthInjector(app_path, _to_legacy(detection)).inject()
        _ok(f"Injected /health + /telemetry → {res.get('file','')}")  if res["success"] else \
        _warn(res.get("message", "injection skipped"))
    else:
        msg = "skipped (--no-inject)" if no_inject else \
              "skipped (inject_health: false)" if not cfg.inject_health else \
              f"not needed for {detection.get('language_display', language)}"
        console.print(f"  [dim]ℹ  {msg}[/dim]")

    # ── 4. OCI Dockerfile ─────────────────────────────────────────────────────
    _step("4", "Generating OCI-compliant Dockerfile")
    OCIDockerfileGenerator(app_path, detection).generate()
    _ok(f"Dockerfile  [{detection.get('base_image_builder')} → {detection.get('base_image')}]")

    # ── 5. Sidecar ────────────────────────────────────────────────────────────
    _step("5", "Generating sidecar watchdog")
    SidecarGenerator(app_path, _to_legacy(detection), cfg.sidecar_port).generate()
    _ok("sidecar/  (Prometheus metrics + auto-restart)")

    # ── 6. Docker Compose ─────────────────────────────────────────────────────
    _step("6", "Generating docker-compose.yml")
    ComposeGenerator(app_path, _to_legacy(detection), cfg.name, cfg.tag,
                     cfg.sidecar_port, databases, cfg).generate()
    db_str = f" + {', '.join(databases)}" if databases else ""
    _ok(f"docker-compose.yml  (app + sidecar{db_str})")

    # ── 7. Optional: Kubernetes ───────────────────────────────────────────────
    if with_k8s:
        _step("7a", "Generating Kubernetes manifests")
        image_ref = f"{cfg.push_registry}/{cfg.name}:{cfg.tag}" if cfg.push_registry \
                    else f"{cfg.name}:{cfg.tag}"
        K8sGenerator(app_path, detection, cfg, image_ref).generate()
        _ok(f"k8s/  (Deployment, Service, ConfigMap, Secret, NetworkPolicy, PDB"
            f"{', Ingress' if cfg.k8s_ingress else ''}{', HPA' if cfg.k8s_hpa else ''})")

    # ── 8. Optional: CI/CD ───────────────────────────────────────────────────
    if with_cicd:
        _step("7b", "Generating CI/CD pipelines")
        CICDGenerator(app_path, detection, cfg).generate_github_actions()
        CICDGenerator(app_path, detection, cfg).generate_gitlab_ci()
        CICDGenerator(app_path, detection, cfg).generate_jenkins()
        _ok(".github/workflows/  ·  .gitlab-ci.yml  ·  Jenkinsfile")

    # ── 9. Optional: Dashboard ────────────────────────────────────────────────
    if with_dash:
        _step("7c", "Generating Grafana dashboard")
        GrafanaGenerator(app_path, cfg, detection).generate()
        _ok(".containerforge/grafana-dashboard.json  ·  grafana-compose-snippet.yml")

    # ── 10. Docker Build ──────────────────────────────────────────────────────
    if not no_build:
        _step("8", f"Building OCI image ({cfg.platform})")
        rc = subprocess.run([
            "docker", "buildx", "build",
            "--platform", cfg.platform,
            "--tag", f"{cfg.name}:{cfg.tag}",
            "--load", ".",
        ], cwd=app_path).returncode
        if rc != 0:
            console.print("  [bold red]❌ Docker build failed[/bold red]")
            raise SystemExit(1)
        _ok(f"Image built: {cfg.name}:{cfg.tag}")

        # ── 11. Vulnerability Scan ────────────────────────────────────────────
        if cfg.scan:
            _step("9", "Running vulnerability scan (Trivy)")
            scanner = VulnScanner(app_path)
            result = scanner.scan_image(f"{cfg.name}:{cfg.tag}")
            scanner.print_report(result, console)
            if scanner.has_blocking_vulns(result, ["CRITICAL"]):
                _warn("CRITICAL vulnerabilities found — review before pushing to production")

        # ── 12. Push ─────────────────────────────────────────────────────────
        if cfg.push_registry:
            registry_tag = f"{cfg.push_registry.rstrip('/')}/{cfg.name}:{cfg.tag}"
            _step("10", f"Pushing → {registry_tag}")
            subprocess.run(["docker", "tag", f"{cfg.name}:{cfg.tag}", registry_tag])
            rc = subprocess.run(["docker", "push", registry_tag]).returncode
            _ok(f"Pushed {registry_tag}") if rc == 0 else _warn("Push failed")

    # ── 13. Compose up ────────────────────────────────────────────────────────
    if not no_build and not no_run:
        _step("11", "Starting with docker compose")
        subprocess.run(["docker", "compose", "up", "-d"], cwd=app_path)

    # ── 14. LLM Analysis ─────────────────────────────────────────────────────
    if ai:
        _step("✨", "Running AI analysis (LLM)")
        analyzer = LLMAnalyzer(app_path, detection)
        result = analyzer.analyze()
        analyzer.print_report(result, console)

    _print_done(cfg, detection)


# ══════════════════════════════════════════════════════════════════════════════
#  DETECT
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def detect(app_path, as_json):
    """Scan a source directory and report detected language, framework, and OCI metadata.

    \b
    Examples:
      containerforge detect ./my-api
      containerforge detect ./my-api --json | jq .language
    """
    app_path = Path(app_path).resolve()
    result = SourceDetector(app_path).detect()
    if as_json:
        console.print_json(_json.dumps(result, indent=2, default=str))
    else:
        print_detection_report(result, app_path)


# ══════════════════════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Overwrite existing containerforge.yml")
def init(app_path, force):
    """Write a starter containerforge.yml into an app directory.

    \b
    Runs detection first, then writes a pre-populated config you can
    commit to version control for reproducible containerization.

    \b
    Example:
      containerforge init ./my-api
    """
    app_path = Path(app_path).resolve()
    out = app_path / "containerforge.yml"
    if out.exists() and not force:
        console.print(f"  [yellow]containerforge.yml already exists. Use --force to overwrite.[/yellow]")
        return
    detection = SourceDetector(app_path).detect()
    content = generate_example_config(detection, app_path)
    out.write_text(content)
    console.print(f"  ✅ [green]containerforge.yml[/green] written → {out}")
    console.print(f"  [dim]Edit it, then run: containerforge build {app_path}[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  SCAN
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--image", "-i", default=None, help="Image tag to scan (default: auto from config/dir name)")
@click.option("--sbom",  is_flag=True, help="Also generate CycloneDX SBOM")
@click.option("--fs",    is_flag=True, help="Scan filesystem (no image needed)")
@click.option("--verbose", "-v", is_flag=True, help="Show MEDIUM + LOW findings too")
def scan(app_path, image, sbom, fs, verbose):
    """Run a Trivy vulnerability scan against a built image or source tree.

    \b
    Examples:
      containerforge scan ./my-api
      containerforge scan ./my-api --image myapp:latest --sbom
      containerforge scan ./my-api --fs
    """
    app_path = Path(app_path).resolve()
    cfg = load_config(app_path)
    img = image or f"{cfg.name or app_path.name.lower()}:{cfg.tag}"

    scanner = VulnScanner(app_path)
    console.print(f"\n[bold cyan]🔍 Scanning: {img}[/bold cyan]\n")

    if fs:
        result = scanner.scan_filesystem(app_path)
    else:
        result = scanner.scan_image(img)

    scanner.print_report(result, console, verbose=verbose)

    if sbom:
        sbom_path = scanner.generate_sbom(img)
        if sbom_path:
            _ok(f"SBOM (CycloneDX) → {sbom_path}")
        else:
            _warn("SBOM generation failed (trivy required)")

    if result.total:
        console.print(f"\n  [dim]Full report: {app_path}/.containerforge/scan-report.json[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  K8S
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--image",     "-i",   default=None,  help="Full image reference (default: name:tag)")
@click.option("--namespace", "-ns",  default=None,  help="Kubernetes namespace")
@click.option("--replicas",  "-r",   default=None, type=int, help="Replica count")
@click.option("--ingress",           is_flag=True,  help="Generate Ingress resource")
@click.option("--ingress-host",      default=None,  help="Ingress hostname")
@click.option("--hpa",               is_flag=True,  help="Generate HorizontalPodAutoscaler")
def k8s(app_path, image, namespace, replicas, ingress, ingress_host, hpa):
    """Generate production-grade Kubernetes manifests.

    \b
    Outputs k8s/ with: Namespace, Deployment, Service, ConfigMap, Secret,
    NetworkPolicy, PodDisruptionBudget, and optionally Ingress + HPA.

    \b
    Examples:
      containerforge k8s ./my-api
      containerforge k8s ./my-api --namespace production --replicas 3 --ingress
      containerforge k8s ./my-api --hpa --ingress-host api.example.com
    """
    app_path = Path(app_path).resolve()
    cfg = load_config(app_path)
    if namespace:    cfg.k8s_namespace = namespace
    if replicas:     cfg.k8s_replicas = replicas
    if ingress:      cfg.k8s_ingress = True
    if ingress_host: cfg.k8s_ingress_host = ingress_host
    if hpa:          cfg.k8s_hpa = True

    detection = SourceDetector(app_path).detect()
    img = image or f"{cfg.name or app_path.name.lower()}:{cfg.tag}"

    console.print(f"\n[bold cyan]☸  Generating Kubernetes manifests[/bold cyan]")
    console.print(f"  Namespace: [bold]{cfg.k8s_namespace}[/bold]  ·  "
                  f"Replicas: [bold]{cfg.k8s_replicas}[/bold]  ·  "
                  f"Image: [bold]{img}[/bold]\n")

    k8s_dir = K8sGenerator(app_path, detection, cfg, img).generate()

    manifests = sorted(k8s_dir.glob("*.yaml"))
    for m in manifests:
        console.print(f"  ✅ [green]{m.name}[/green]")

    console.print(f"\n  [dim]Apply:  kubectl apply -f k8s/[/dim]")
    console.print(f"  [dim]Dry run: kubectl apply -f k8s/ --dry-run=client[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  CICD
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--provider", "-p",
              type=click.Choice(["github", "gitlab", "jenkins", "all"], case_sensitive=False),
              default="all", help="CI/CD provider (default: all)")
def cicd(app_path, provider):
    """Generate CI/CD pipeline configuration files.

    \b
    Generates pipelines that: run tests, build OCI image, run Trivy scan,
    push to registry, and optionally deploy to Kubernetes.

    \b
    Examples:
      containerforge cicd ./my-api
      containerforge cicd ./my-api --provider github
      containerforge cicd ./my-api --provider gitlab
    """
    app_path = Path(app_path).resolve()
    cfg = load_config(app_path)
    detection = SourceDetector(app_path).detect()

    gen = CICDGenerator(app_path, detection, cfg)
    console.print(f"\n[bold cyan]🔄 Generating CI/CD pipelines[/bold cyan]\n")

    if provider in ("github", "all"):
        p = gen.generate_github_actions()
        _ok(f".github/workflows/containerforge.yml")
    if provider in ("gitlab", "all"):
        p = gen.generate_gitlab_ci()
        _ok(f".gitlab-ci.yml")
    if provider in ("jenkins", "all"):
        p = gen.generate_jenkins()
        _ok(f"Jenkinsfile")

    console.print(f"\n  [dim]All pipelines: test → build → scan → push → deploy[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  DEPLOY
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--provider", "-p",
              type=click.Choice(PROVIDERS, case_sensitive=False),
              default=None, help="Cloud provider: aws | gcp | azure | fly")
@click.option("--region",  "-r", default=None, help="Cloud region")
@click.option("--image",   "-i", default=None, help="Image tag to deploy")
@click.option("--gen-only", is_flag=True, help="Generate IaC files only — don't execute deploy")
@click.option("--dry-run",  is_flag=True, help="Show what would be deployed, don't run")
def deploy(app_path, provider, region, image, gen_only, dry_run):
    """Deploy a containerized application to a cloud provider.

    \b
    Generates provider-specific IaC (CloudFormation, Bicep, fly.toml)
    and optionally runs the deployment.

    \b
    Examples:
      containerforge deploy ./my-api --provider aws
      containerforge deploy ./my-api --provider fly --gen-only
      containerforge deploy ./my-api --provider gcp --region us-central1
    """
    app_path = Path(app_path).resolve()
    cfg = load_config(app_path)
    if provider: cfg.cloud_provider = provider
    if region:   cfg.cloud_region = region
    if not cfg.cloud_provider:
        console.print("  [red]No cloud provider specified. Use --provider aws|gcp|azure|fly or set in containerforge.yml[/red]")
        raise SystemExit(1)

    detection = SourceDetector(app_path).detect()
    img = image or f"{cfg.name or app_path.name.lower()}:{cfg.tag}"

    console.print(f"\n[bold cyan]☁  Cloud Deploy → {cfg.cloud_provider.upper()}[/bold cyan]")
    console.print(f"  Provider: [bold]{cfg.cloud_provider}[/bold]  ·  "
                  f"Region: [bold]{cfg.cloud_region or 'default'}[/bold]  ·  "
                  f"Image: [bold]{img}[/bold]\n")

    deployer = CloudDeployer(app_path, detection, cfg, img)
    files = deployer.generate_iac()

    for fname in files:
        _ok(f".containerforge/cloud/{fname}")

    if not gen_only:
        console.print(f"\n  [cyan]Running deployment...[/cyan]")
        ok = deployer.deploy(dry_run=dry_run)
        _ok(f"Deployed to {cfg.cloud_provider}") if ok else _warn("Deploy failed — check logs")
    else:
        console.print(f"\n  [dim]IaC generated. Run deploy without --gen-only to execute.[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
def dashboard(app_path):
    """Generate a Grafana dashboard pre-wired to ContainerForge sidecar metrics.

    \b
    Outputs:
      .containerforge/grafana-dashboard.json      Import into any Grafana instance
      .containerforge/grafana-provisioning.yml    Auto-provisioning config
      .containerforge/grafana-compose-snippet.yml Add Grafana+Prometheus to compose

    \b
    Example:
      containerforge dashboard ./my-api
    """
    app_path = Path(app_path).resolve()
    cfg = load_config(app_path)
    detection = SourceDetector(app_path).detect()

    console.print(f"\n[bold cyan]📊 Generating Grafana dashboard[/bold cyan]\n")
    out = GrafanaGenerator(app_path, cfg, detection).generate()

    _ok("grafana-dashboard.json   ← import into Grafana (Dashboards → Import)")
    _ok("grafana-provisioning.yml ← auto-provision via config")
    _ok("grafana-compose-snippet.yml ← add Prometheus+Grafana to docker-compose.yml")
    console.print(f"\n  [dim]After adding to compose, open: http://localhost:3000  (admin/admin)[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYZE (LLM)
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY",
              help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
def analyze(app_path, api_key):
    """AI-powered analysis of your containerization setup.

    \b
    Uses Claude to review your Dockerfile, source code, and detected config
    for security issues, anti-patterns, and production-readiness gaps.
    Returns a 0-100 score with ranked recommendations.

    \b
    Requires: ANTHROPIC_API_KEY environment variable

    \b
    Example:
      export ANTHROPIC_API_KEY=sk-ant-...
      containerforge analyze ./my-api
    """
    app_path = Path(app_path).resolve()
    detection = SourceDetector(app_path).detect()

    if not api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("  [red]ANTHROPIC_API_KEY not set.[/red]")
        console.print("  [dim]Set it: export ANTHROPIC_API_KEY=sk-ant-...[/dim]")
        raise SystemExit(1)

    console.print(f"\n[bold cyan]🤖 Running AI analysis...[/bold cyan]\n")
    with console.status("  Asking Claude to review your setup..."):
        result = LLMAnalyzer(app_path, detection).analyze(api_key)

    LLMAnalyzer(app_path, detection).print_report(result, console)


# ══════════════════════════════════════════════════════════════════════════════
#  CLEAN
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("app_path", type=click.Path(exists=True))
@click.option("--all", "clean_all", is_flag=True, help="Also remove k8s/, .github/workflows/, .gitlab-ci.yml, Jenkinsfile, fly.toml")
def clean(app_path, clean_all):
    """Remove all ContainerForge-generated files from an app directory.

    \b
    Example:
      containerforge clean ./my-api
      containerforge clean ./my-api --all
    """
    app_path = Path(app_path).resolve()
    targets = [
        "Dockerfile", "Dockerfile.sidecar", "docker-compose.yml",
        ".dockerignore", "_cf_health.py", "_cf_health_server.py",
        "sidecar/", ".containerforge/",
    ]
    if clean_all:
        targets += [
            "k8s/", ".github/workflows/containerforge.yml",
            ".gitlab-ci.yml", "Jenkinsfile", "fly.toml",
            "containerforge.yml",
        ]

    removed, skipped = [], []
    for item in targets:
        p = app_path / item
        if p.exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            removed.append(item)
        else:
            skipped.append(item)

    if removed:
        console.print(f"[green]Removed:[/green] {', '.join(removed)}")
    else:
        console.print("[dim]Nothing to clean.[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  LIST-SUPPORTED
# ══════════════════════════════════════════════════════════════════════════════

@cli.command("list-supported")
def list_supported():
    """List all supported languages, frameworks, and cloud providers."""
    lang_names = {
        "python": "Python", "nodejs": "Node.js", "go": "Go",
        "java": "Java",     "ruby": "Ruby",       "rust": "Rust",
        "php": "PHP",       "dotnet": ".NET",
    }

    # Languages + frameworks
    t = Table(title="Supported Languages & Frameworks",
              box=box.ROUNDED, border_style="cyan", show_lines=False)
    t.add_column("Language",   style="bold cyan",  width=12)
    t.add_column("Frameworks", width=55)
    t.add_column("Base Image",  width=30)

    base_images = {
        "python":  "python:{ver}-slim",
        "nodejs":  "node:{ver}-alpine",
        "go":      "distroless/static (scratch)",
        "java":    "eclipse-temurin:{ver}-jre-alpine",
        "ruby":    "ruby:{ver}-slim",
        "rust":    "distroless/cc (scratch)",
        "php":     "php:{ver}-fpm-alpine",
        "dotnet":  "dotnet/aspnet:{ver}-alpine",
    }

    for lang, patterns in FRAMEWORK_PATTERNS.items():
        fws = [fw for fw, _, _ in patterns]
        t.add_row(
            lang_names.get(lang, lang),
            ", ".join(fws),
            base_images.get(lang, "—"),
        )
    console.print(t)

    # Databases
    t2 = Table(title="Auto-detected Databases",
               box=box.ROUNDED, border_style="cyan")
    t2.add_column("Database",      style="bold cyan", width=16)
    t2.add_column("Image",         width=28)
    t2.add_column("Port",          width=8)
    t2.add_column("Auto-wired env var",  width=28)

    db_order = ["postgres","mysql","redis","mongodb","elasticsearch","rabbitmq","kafka"]
    for name in db_order:
        spec = DB_SERVICES.get(name, {})
        env_var = list(spec.get("app_env", {}).keys())[0] if spec.get("app_env") else "—"
        t2.add_row(
            spec.get("display", name),
            spec.get("image", "—"),
            str(spec.get("port", "—")),
            env_var,
        )
    console.print(t2)

    # Cloud
    t3 = Table(title="Cloud Deploy Targets",
               box=box.ROUNDED, border_style="cyan")
    t3.add_column("Provider", style="bold cyan", width=12)
    t3.add_column("Service",  width=25)
    t3.add_column("IaC Format", width=22)
    t3.add_column("Command", width=28)
    clouds = [
        ("aws",   "ECS Fargate",          "CloudFormation YAML", "containerforge deploy --provider aws"),
        ("gcp",   "Cloud Run",            "Cloud Run YAML",      "containerforge deploy --provider gcp"),
        ("azure", "Azure Container Apps", "Bicep",               "containerforge deploy --provider azure"),
        ("fly",   "Fly.io Machines",      "fly.toml",            "containerforge deploy --provider fly"),
    ]
    for p, svc, iac, cmd in clouds:
        t3.add_row(p, svc, iac, f"[dim]{cmd}[/dim]")
    console.print(t3)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _step(n, msg):
    console.print(f"\n[bold cyan][{n}][/bold cyan] {msg}")

def _ok(msg):
    console.print(f"  ✅ [green]{msg}[/green]")

def _warn(msg):
    console.print(f"  ⚠️  [yellow]{msg}[/yellow]")

def _override_lang(d, lang):
    d["language"] = lang
    d["language_display"] = "Node.js" if lang == "nodejs" else lang.capitalize()

def _override_fw(d, fw):
    d["framework"] = fw
    d["framework_display"] = fw.capitalize()

def _print_detect_line(d):
    lang  = d.get("language_display", d.get("language", "?"))
    fw    = d.get("framework_display", d.get("framework", "?"))
    conf  = d.get("confidence", "?")
    color = {"high": "green", "medium": "yellow", "low": "red"}.get(conf, "white")
    console.print(
        f"  🧬 [bold]{lang}[/bold] / [bold green]{fw}[/bold green]"
        f"  port [bold]{d.get('port')}[/bold]"
        f"  runtime [dim]{d.get('runtime_version')}[/dim]"
        f"  confidence [{color}]{conf}[/{color}]"
    )

def _to_legacy(d):
    return {
        "language":        d.get("language", "python"),
        "framework":       d.get("framework_display", d.get("framework", "unknown")),
        "framework_key":   d.get("framework", "unknown"),
        "entry_point":     d.get("entry_point", "main.py"),
        "entry_point_abs": d.get("entry_point_abs"),
        "port":            d.get("port", 8080),
        "start_command":   d.get("start_command", ""),
        "deps_file":       d.get("deps_file"),
        "python_version":  d.get("runtime_version", "3.11"),
        "has_env_file":    d.get("has_env_file", False),
        "app_object":      d.get("app_object", "app"),
        "module_name":     d.get("module_name", "main"),
    }

def _print_done(cfg: ForgeConfig, detection: dict):
    port = detection.get("port", 8080)
    lang = detection.get("language_display", detection.get("language", "?"))
    fw   = detection.get("framework_display", detection.get("framework", "?"))
    console.print(Panel(
        f"[bold green]✅ ContainerForge complete![/bold green]\n\n"
        f"  [bold]App:[/bold]       {lang} / {fw}\n"
        f"  [bold]Image:[/bold]     {cfg.name}:{cfg.tag}\n\n"
        f"  [dim]─────────────────────────────[/dim]\n"
        f"  [bold]App:[/bold]       http://localhost:{port}\n"
        f"  [bold]Health:[/bold]    http://localhost:{port}/health\n"
        f"  [bold]Metrics:[/bold]   http://localhost:{cfg.sidecar_port}/sidecar/metrics\n"
        f"  [bold]Sidecar:[/bold]   http://localhost:{cfg.sidecar_port}/sidecar/status\n\n"
        f"  [dim]docker compose logs -f      # stream logs[/dim]\n"
        f"  [dim]docker compose down         # stop everything[/dim]\n"
        f"  [dim]containerforge scan .        # re-run vuln scan[/dim]\n"
        f"  [dim]containerforge k8s .         # generate k8s manifests[/dim]",
        title="[bold cyan]🏁 Done[/bold cyan]",
        border_style="green",
    ))


if __name__ == "__main__":
    cli()
