"""
VulnScanner: Scans Docker images for vulnerabilities using Trivy.

Features:
  - Runs trivy against the built image
  - Parses JSON output into a structured report
  - Severity-filtered summaries (CRITICAL, HIGH, MEDIUM, LOW)
  - Blocks build on CRITICAL findings (configurable)
  - Saves scan report to .containerforge/scan-report.json
  - SBOM generation (CycloneDX/SPDX format)
"""

import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional


TRIVY_NOT_FOUND_MSG = """
[yellow]⚠  Trivy not found.[/yellow] Install it to enable vulnerability scanning:

  macOS:   brew install aquasecurity/trivy/trivy
  Linux:   curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh
  Windows: winget install aquasecurity.trivy
  Docker:  docker run aquasec/trivy image <IMAGE>

Or disable scanning:  add  scan: false  to containerforge.yml
"""

SEVERITY_COLORS = {
    "CRITICAL": "bold red",
    "HIGH":     "red",
    "MEDIUM":   "yellow",
    "LOW":      "dim",
    "UNKNOWN":  "dim",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]


@dataclass
class Vulnerability:
    pkg_name: str
    installed_version: str
    fixed_version: str
    severity: str
    vuln_id: str
    title: str
    description: str = ""
    primary_url: str = ""


@dataclass
class ScanResult:
    image: str
    scanned_at: str
    total: int = 0
    by_severity: dict = field(default_factory=dict)
    vulnerabilities: list = field(default_factory=list)
    error: Optional[str] = None
    trivy_version: str = ""


class VulnScanner:
    def __init__(self, app_path: Path):
        self.app_path = Path(app_path)
        self.report_dir = app_path / ".containerforge"
        self.report_dir.mkdir(exist_ok=True)

    def trivy_available(self) -> bool:
        return shutil.which("trivy") is not None

    def scan_image(self, image_tag: str, fail_on: list = ["CRITICAL"]) -> ScanResult:
        """
        Scan a Docker image with trivy.
        Returns ScanResult with parsed vulnerabilities.
        fail_on: list of severities that should be treated as build-blocking.
        """
        if not self.trivy_available():
            return ScanResult(
                image=image_tag,
                scanned_at=datetime.utcnow().isoformat(),
                error="trivy_not_found",
            )

        report_path = self.report_dir / "scan-report.json"

        cmd = [
            "trivy", "image",
            "--format", "json",
            "--output", str(report_path),
            "--quiet",
            image_tag,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return ScanResult(image=image_tag, scanned_at=datetime.utcnow().isoformat(),
                              error="scan_timeout")
        except Exception as e:
            return ScanResult(image=image_tag, scanned_at=datetime.utcnow().isoformat(),
                              error=str(e))

        result = self._parse_report(image_tag, report_path)
        self._save_summary(result)
        return result

    def generate_sbom(self, image_tag: str, fmt: str = "cyclonedx") -> Optional[Path]:
        """Generate SBOM in CycloneDX or SPDX format."""
        if not self.trivy_available():
            return None

        ext = "json" if fmt == "cyclonedx" else "spdx"
        out_path = self.report_dir / f"sbom.{ext}"

        trivy_fmt = "cyclonedx" if fmt == "cyclonedx" else "spdx-json"

        cmd = [
            "trivy", "image",
            "--format", trivy_fmt,
            "--output", str(out_path),
            "--quiet",
            image_tag,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=300)
            return out_path if out_path.exists() else None
        except Exception:
            return None

    def scan_filesystem(self, path: Optional[Path] = None) -> ScanResult:
        """Scan the source directory (no image needed — catches secrets, misconfigs)."""
        target = str(path or self.app_path)
        report_path = self.report_dir / "fs-scan-report.json"

        if not self.trivy_available():
            return ScanResult(image=target, scanned_at=datetime.utcnow().isoformat(),
                              error="trivy_not_found")

        cmd = [
            "trivy", "fs",
            "--format", "json",
            "--output", str(report_path),
            "--scanners", "vuln,secret,misconfig",
            "--quiet",
            target,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except Exception as e:
            return ScanResult(image=target, scanned_at=datetime.utcnow().isoformat(), error=str(e))

        return self._parse_report(target, report_path)

    def _parse_report(self, target: str, report_path: Path) -> ScanResult:
        result = ScanResult(
            image=target,
            scanned_at=datetime.utcnow().isoformat(),
            by_severity={s: 0 for s in SEVERITY_ORDER},
        )

        if not report_path.exists():
            result.error = "no_report_generated"
            return result

        try:
            data = json.loads(report_path.read_text())
        except Exception as e:
            result.error = f"parse_error: {e}"
            return result

        result.trivy_version = data.get("SchemaVersion", "")

        for target_entry in data.get("Results", []):
            vulns = target_entry.get("Vulnerabilities") or []
            for v in vulns:
                severity = v.get("Severity", "UNKNOWN").upper()
                vuln = Vulnerability(
                    pkg_name=v.get("PkgName", ""),
                    installed_version=v.get("InstalledVersion", ""),
                    fixed_version=v.get("FixedVersion", ""),
                    severity=severity,
                    vuln_id=v.get("VulnerabilityID", ""),
                    title=v.get("Title", ""),
                    description=v.get("Description", "")[:200],
                    primary_url=v.get("PrimaryURL", ""),
                )
                result.vulnerabilities.append(vuln)
                result.by_severity[severity] = result.by_severity.get(severity, 0) + 1
                result.total += 1

        return result

    def _save_summary(self, result: ScanResult):
        summary = {
            "image": result.image,
            "scanned_at": result.scanned_at,
            "total": result.total,
            "by_severity": result.by_severity,
            "top_critical": [
                {"id": v.vuln_id, "pkg": v.pkg_name, "fix": v.fixed_version, "title": v.title}
                for v in result.vulnerabilities if v.severity == "CRITICAL"
            ][:10],
        }
        summary_path = self.report_dir / "scan-summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))

    def has_blocking_vulns(self, result: ScanResult, fail_on: list = ["CRITICAL"]) -> bool:
        return any(result.by_severity.get(s, 0) > 0 for s in fail_on)

    def print_report(self, result: ScanResult, console, verbose: bool = False):
        from rich.table import Table; from rich.panel import Panel; from rich import box; from rich.text import Text
        """Print scan results to rich console."""

        if result.error == "trivy_not_found":
            console.print(TRIVY_NOT_FOUND_MSG)
            return

        if result.error:
            console.print(f"  [yellow]⚠  Scan error: {result.error}[/yellow]")
            return

        if result.total == 0:
            console.print("  ✅ [green]No vulnerabilities found![/green]")
            return

        # Summary line
        parts = []
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = result.by_severity.get(sev, 0)
            if count:
                color = SEVERITY_COLORS[sev]
                parts.append(f"[{color}]{sev}: {count}[/{color}]")
        console.print("  📊 " + "  ".join(parts))

        # Detail table for CRITICAL + HIGH (or all if verbose)
        show_sevs = SEVERITY_ORDER if verbose else ["CRITICAL", "HIGH"]
        show = [v for v in result.vulnerabilities if v.severity in show_sevs]

        if show:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("Severity", width=10)
            t.add_column("Package", width=20)
            t.add_column("Installed", width=14)
            t.add_column("Fixed", width=14)
            t.add_column("CVE", width=18)
            t.add_column("Title", width=35)
            for v in show[:25]:
                color = SEVERITY_COLORS.get(v.severity, "white")
                t.add_row(
                    f"[{color}]{v.severity}[/{color}]",
                    v.pkg_name, v.installed_version,
                    v.fixed_version or "[dim]no fix[/dim]",
                    v.vuln_id, v.title[:35],
                )
            console.print(t)
            if len(show) > 25:
                console.print(f"  [dim]...and {len(show)-25} more. See .containerforge/scan-report.json[/dim]")