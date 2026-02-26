"""
LLMAnalyzer: Uses the Anthropic API to perform deep analysis of an app's
containerization setup — finds anti-patterns, security issues, optimization
opportunities, and generates a human-readable report.
"""

import json
import os
from pathlib import Path
from typing import Optional


ANALYSIS_PROMPT = """You are an expert DevOps and cloud-native engineer reviewing a containerized application.

Analyze the following application metadata and source code samples. Provide a thorough review covering:

1. **Security Issues**: hardcoded secrets, insecure defaults, missing security headers, non-root users, read-only filesystems
2. **Dockerfile Optimizations**: layer caching, image size, multi-stage builds, unnecessary packages
3. **Configuration Anti-patterns**: missing health checks, no graceful shutdown, missing resource limits
4. **Runtime Risks**: missing SIGTERM handling, no retry logic, synchronous DB connections at startup
5. **Production Readiness Score**: 0-100 with breakdown by category
6. **Top 5 Recommendations**: ranked by impact, each with a code snippet

Format your response as JSON with this exact structure:
{
  "score": <0-100>,
  "score_breakdown": {
    "security": <0-25>,
    "dockerfile": <0-25>,
    "configuration": <0-25>,
    "production_readiness": <0-25>
  },
  "issues": [
    {
      "severity": "critical|high|medium|low",
      "category": "security|dockerfile|configuration|runtime",
      "title": "<short title>",
      "description": "<detailed explanation>",
      "fix": "<code snippet or command to fix>"
    }
  ],
  "recommendations": [
    {
      "rank": 1,
      "title": "<title>",
      "impact": "high|medium|low",
      "description": "<explanation>",
      "code": "<example code>"
    }
  ],
  "summary": "<2-3 sentence overall assessment>"
}

Application metadata:
{metadata}

Source samples:
{source_samples}

Dockerfile:
{dockerfile}
"""


class LLMAnalyzer:
    def __init__(self, app_path: Path, detection: dict):
        self.app_path = Path(app_path)
        self.d = detection

    def analyze(self, api_key: Optional[str] = None) -> dict:
        """
        Run LLM analysis. Returns structured analysis dict.
        Requires ANTHROPIC_API_KEY env var or explicit api_key.
        """
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"error": "ANTHROPIC_API_KEY not set", "score": 0, "issues": [], "recommendations": []}

        metadata = self._build_metadata()
        source_samples = self._sample_sources()
        dockerfile = self._read_dockerfile()

        prompt = ANALYSIS_PROMPT.format(
            metadata=json.dumps(metadata, indent=2),
            source_samples=source_samples[:4000],
            dockerfile=dockerfile[:2000],
        )

        try:
            import urllib.request
            payload = json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())

            raw_text = data["content"][0]["text"]
            # Strip markdown fences if present
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
                clean = clean.rsplit("```", 1)[0]

            result = json.loads(clean)
            self._save_report(result)
            return result

        except Exception as e:
            return {"error": str(e), "score": 0, "issues": [], "recommendations": []}

    def _build_metadata(self) -> dict:
        return {
            "app_name": self.app_path.name,
            "language": self.d.get("language"),
            "framework": self.d.get("framework"),
            "runtime_version": self.d.get("runtime_version"),
            "port": self.d.get("port"),
            "entry_point": self.d.get("entry_point"),
            "deps_file": self.d.get("deps_file"),
            "has_env_file": self.d.get("has_env_file"),
            "env_vars": self.d.get("env_vars", []),
            "confidence": self.d.get("confidence"),
        }

    def _sample_sources(self) -> str:
        lang = self.d.get("language", "python")
        ext_map = {"python": ".py", "nodejs": ".js", "go": ".go", "ruby": ".rb"}
        ext = ext_map.get(lang, ".py")
        samples = []
        for f in list(self.app_path.glob(f"*{ext}"))[:4]:
            try:
                content = f.read_text(errors="ignore")[:800]
                samples.append(f"# --- {f.name} ---\n{content}")
            except Exception:
                pass
        return "\n\n".join(samples)

    def _read_dockerfile(self) -> str:
        from rich.table import Table; from rich.panel import Panel; from rich import box; from rich.text import Text
        df = self.app_path / "Dockerfile"
        if df.exists():
            try:
                return df.read_text(errors="ignore")
            except Exception:
                pass
        return "# Dockerfile not found"

    def _save_report(self, result: dict):
        from rich.table import Table; from rich.panel import Panel; from rich import box; from rich.text import Text
        out_dir = self.app_path / ".containerforge"
        out_dir.mkdir(exist_ok=True)
        report_path = out_dir / "llm-analysis.json"
        report_path.write_text(json.dumps(result, indent=2))

    def print_report(self, result: dict, console):
        from rich.table import Table; from rich.panel import Panel; from rich import box; from rich.text import Text

        if result.get("error"):
            console.print(f"  [yellow]⚠  LLM analysis failed: {result['error']}[/yellow]")
            return

        score = result.get("score", 0)
        score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        summary = result.get("summary", "")
        breakdown = result.get("score_breakdown", {})

        console.print(Panel(
            f"  [bold]Overall Score:[/bold] [{score_color}]{score}/100[/{score_color}]\n\n"
            f"  Security: [bold]{breakdown.get('security', '?')}/25[/bold]  "
            f"  Dockerfile: [bold]{breakdown.get('dockerfile', '?')}/25[/bold]  "
            f"  Config: [bold]{breakdown.get('configuration', '?')}/25[/bold]  "
            f"  Prod Ready: [bold]{breakdown.get('production_readiness', '?')}/25[/bold]\n\n"
            f"  [dim]{summary}[/dim]",
            title="🤖 LLM Analysis Report",
            border_style=score_color,
        ))

        issues = result.get("issues", [])
        if issues:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("Severity", width=10)
            t.add_column("Category", width=14)
            t.add_column("Issue", width=35)
            t.add_column("Fix Preview", width=30)
            colors = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "dim"}
            for issue in issues[:10]:
                sev = issue.get("severity", "low")
                color = colors.get(sev, "white")
                fix_preview = issue.get("fix", "")[:30].replace("\n", " ")
                t.add_row(
                    f"[{color}]{sev.upper()}[/{color}]",
                    issue.get("category", ""),
                    issue.get("title", ""),
                    f"[dim]{fix_preview}[/dim]",
                )
            console.print(t)

        recs = result.get("recommendations", [])
        if recs:
            console.print(f"\n  [bold]Top Recommendations:[/bold]")
            for r in recs[:3]:
                impact_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(r.get("impact", "low"), "white")
                console.print(f"  [{impact_color}]#{r.get('rank')}[/{impact_color}] [bold]{r.get('title')}[/bold]")
                console.print(f"      [dim]{r.get('description', '')[:120]}[/dim]")

        console.print(f"  [dim]Full report: .containerforge/llm-analysis.json[/dim]")