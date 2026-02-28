"""
DetectionReport: Rich terminal output for source detection results.
Shows language, framework, confidence, OCI labels, detected ports, etc.
"""

from pathlib import Path
from rich.console import Console

console = Console()


def print_detection_report(detection: dict, app_path: Path):
    from rich.table import Table; from rich.panel import Panel; from rich import box; from rich.text import Text
    """Print a full detection report to the terminal."""

    lang = detection.get("language_display", detection.get("language", "?"))
    fw = detection.get("framework_display", detection.get("framework", "?"))
    confidence = detection.get("confidence", "unknown")
    confidence_color = {"high": "green", "medium": "yellow", "low": "red"}.get(confidence, "white")

    # ── Header ────────────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold]{app_path}[/bold]",
        title="[bold cyan]🔍 Source Detection Results[/bold cyan]",
        border_style="cyan",
    ))

    # ── Core Detection Table ─────────────────────────────────────────────────
    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    t.add_column("Key", style="bold cyan", width=22)
    t.add_column("Value")

    t.add_row("Language",         f"[bold]{lang}[/bold]")
    t.add_row("Framework",        f"[bold green]{fw}[/bold green]")
    t.add_row("Runtime Version",  detection.get("runtime_version", "?"))
    t.add_row("Entry Point",      detection.get("entry_point") or "[dim]not found[/dim]")
    t.add_row("App Object",       detection.get("app_object", "app"))
    t.add_row("Port",             str(detection.get("port", "?")))
    t.add_row("Start Command",    f"[dim]{detection.get('start_command', '?')}[/dim]")
    t.add_row("Build Command",    f"[dim]{detection.get('build_command', '—') or '—'}[/dim]")
    t.add_row("Dep File",         detection.get("deps_file") or "[dim]none[/dim]")
    t.add_row("Lock File",        detection.get("lock_file") or "[dim]none[/dim]")
    t.add_row("Package Manager",  detection.get("package_manager") or "[dim]unknown[/dim]")
    t.add_row("Env File",         "✅ found" if detection.get("has_env_file") else "[dim]none[/dim]")
    t.add_row("Confidence",       f"[{confidence_color}]{confidence.upper()}[/{confidence_color}]")

    console.print(t)

    # ── OCI Labels ───────────────────────────────────────────────────────────
    labels = detection.get("oci_labels", {})
    if labels:
        lt = Table(show_header=True, box=box.SIMPLE, padding=(0, 2), title="OCI Image Labels")
        lt.add_column("Label", style="dim cyan", width=45)
        lt.add_column("Value", style="white")
        for k, v in labels.items():
            lt.add_row(k, str(v))
        console.print(lt)

    # ── Env Vars Found ────────────────────────────────────────────────────────
    env_vars = detection.get("env_vars", [])
    if env_vars:
        console.print(f"\n  [bold]Detected env vars:[/bold] {', '.join(f'[cyan]{e}[/cyan]' for e in env_vars)}")

    # ── Base Images ──────────────────────────────────────────────────────────
    console.print(f"\n  [bold]Builder image:[/bold]  {detection.get('base_image_builder', '?')}")
    console.print(f"  [bold]Runtime image:[/bold]  {detection.get('base_image', '?')}")

    # ── Warning if low confidence ────────────────────────────────────────────
    if confidence == "low":
        console.print("\n  [yellow]⚠  Low detection confidence. Consider passing --lang and --framework manually.[/yellow]")
    elif detection.get("framework") == "unknown":
        console.print(f"\n  [yellow]⚠  Framework not detected. Defaulting to bare {lang} image.[/yellow]")