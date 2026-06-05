"""
cli.py — Brewster CLI.

Commands:
    brewster init               — first-time setup
    brewster sync               — snapshot this machine → DB
    brewster machines           — list all registered machines
    brewster list               — list packages (this machine or another)
    brewster diff <a> <b>       — compare packages between two machines
    brewster install-missing    — install packages from another machine
    brewster status             — show DB path, sync state, counts
    brewster config             — view/set config values
    brewster export             — export all machine DBs to JSON
    brewster import             — import machines and packages from JSON
"""

from __future__ import annotations

import json as _json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.columns import Columns

from . import __version__
from .config import (
    load_config,
    save_config,
    get_label,
    get_sync_root,
    get_databases_dir,
    get_logs_dir,
    set_label,
    set_sync_root,
    detect_sync_backends,
    CONFIG_FILE,
)
from .db import (
    BrewsterDB,
    db_path_for_machine,
    find_machine_db,
    iter_all_machines,
)
from .diff import compute_diff, DiffResult, PackageRow
from .installer import install_packages
from .machine import MachineInfo, assert_brew_available

console = Console()
err_console = Console(stderr=True)

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Shared options / helpers
# ---------------------------------------------------------------------------

def _db_path_option(f):
    return click.option(
        "--db-path",
        default=None,
        metavar="DIR",
        help="Override the sync directory (parent of databases/ and logs/).",
        envvar="BREWSTER_DB_PATH",
    )(f)


def _setup_file_logging(logs_dir: Path, hostname: str) -> None:
    """Add a per-machine file handler to the root brewster logger."""
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(logs_dir / f"{hostname}.log", encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
        )
        logger = logging.getLogger("brewster")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    except OSError as exc:
        log.debug("Could not set up file logging: %s", exc)


def _resolve_machine_db(
    databases_dir: Path, name: str
) -> tuple[BrewsterDB, object]:
    """Find a machine's DB by label or hostname. Exit with message if not found."""
    db, row = find_machine_db(databases_dir, name)
    if db is None:
        err_console.print(
            f"[red]✗[/red] Machine [bold]{name!r}[/bold] not found. "
            f"Run [bold]brewster machines[/bold] to list known machines."
        )
        sys.exit(1)
    return db, row


def _render_diff_section(diff: DiffResult, show_versions: bool = False) -> None:
    kind_label = diff.kind.capitalize()
    total_common = len(diff.common) + len(diff.version_diff)

    if not diff.has_differences:
        console.print(
            f"  [dim]{kind_label}: {total_common} in common, no differences.[/dim]"
        )
        return

    if diff.only_a or diff.only_b:
        table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            title=f"[bold]{kind_label} Differences[/bold]",
            title_style="bold white",
            min_width=60,
        )
        table.add_column(f"Only on {diff.machine_a}", style="yellow", no_wrap=True)
        table.add_column("Version", style="dim", no_wrap=True)
        table.add_column(f"Only on {diff.machine_b}", style="green", no_wrap=True)
        table.add_column("Version", style="dim", no_wrap=True)

        max_rows = max(len(diff.only_a), len(diff.only_b))
        for i in range(max_rows):
            pa = diff.only_a[i] if i < len(diff.only_a) else None
            pb = diff.only_b[i] if i < len(diff.only_b) else None
            table.add_row(
                pa.name if pa else "",
                pa.version if pa else "",
                pb.name if pb else "",
                pb.version if pb else "",
            )
        console.print(table)

    if show_versions and diff.version_diff:
        vtable = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold magenta",
            title=f"[bold]{kind_label} Version Mismatches[/bold]",
            title_style="bold white",
        )
        vtable.add_column("Package", style="bold", no_wrap=True)
        vtable.add_column(diff.machine_a, style="yellow", no_wrap=True)
        vtable.add_column(diff.machine_b, style="green", no_wrap=True)
        for pa, pb in diff.version_diff:
            vtable.add_row(pa.name, pa.version, pb.version)
        console.print(vtable)

    summary_parts = []
    if diff.only_a:
        summary_parts.append(f"[yellow]{len(diff.only_a)} only on {diff.machine_a}[/yellow]")
    if diff.only_b:
        summary_parts.append(f"[green]{len(diff.only_b)} only on {diff.machine_b}[/green]")
    if diff.version_diff:
        summary_parts.append(f"[magenta]{len(diff.version_diff)} version mismatches[/magenta]")
    if total_common:
        summary_parts.append(f"[dim]{total_common} in common[/dim]")
    console.print("  " + "  ·  ".join(summary_parts))


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="brewster")
def cli():
    """Brewster — track Homebrew packages across all your machines."""
    pass


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--label", default=None, help="Friendly name for this machine.")
@click.option("--db-path", default=None, metavar="DIR",
              help="Sync root directory (will contain databases/ and logs/).")
@click.option("--yes", "-y", is_flag=True, help="Accept all defaults without prompting.")
def init(label: Optional[str], db_path: Optional[str], yes: bool):
    """First-time setup: register this machine and choose a sync backend."""
    console.print(Panel.fit("[bold cyan]Brewster Setup[/bold cyan]", border_style="cyan"))

    assert_brew_available()

    cfg = load_config()
    machine = MachineInfo(label=label or get_label(cfg))

    # --- Label ---
    if not label:
        current_label = get_label(cfg) or machine.hostname
        if yes:
            resolved_label = current_label
        else:
            resolved_label = Prompt.ask("  Machine label", default=current_label)
    else:
        resolved_label = label

    machine.label = resolved_label

    # --- Sync root ---
    if db_path:
        resolved_root = Path(db_path).expanduser()
    else:
        configured_root = get_sync_root(config=cfg)
        if yes:
            resolved_root = configured_root
        else:
            backends = detect_sync_backends()
            available = [b for b in backends if b["available"]]

            console.print("\n  [bold]Detected sync locations:[/bold]")
            for i, b in enumerate(available, 1):
                marker = " [green]✓[/green]" if b["key"] != "custom" else ""
                console.print(f"    [{i}] {b['name']}{marker}")

            choice_str = Prompt.ask("  Select sync backend", default="1")
            try:
                choice_idx = int(choice_str) - 1
                chosen = available[choice_idx]
            except (ValueError, IndexError):
                err_console.print("[red]Invalid choice.[/red]")
                sys.exit(1)

            if chosen["key"] == "custom":
                custom_path = Prompt.ask("  Enter sync directory path")
                resolved_root = Path(custom_path).expanduser()
            else:
                resolved_root = chosen["path"]
                console.print(f"  [dim]Sync root: {resolved_root}[/dim]")

    databases_dir = resolved_root / "databases"
    logs_dir = resolved_root / "logs"

    # --- Save config ---
    cfg.setdefault("machine", {})["label"] = resolved_label
    cfg.setdefault("database", {})["path"] = str(resolved_root)
    save_config(cfg)

    # --- Open/init DB and register machine ---
    databases_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_path_for_machine(databases_dir, machine.hostname)
    db = BrewsterDB(db_file)
    db.open()

    # Warn if another machine already owns this label.
    existing_db, existing = find_machine_db(databases_dir, resolved_label)
    if existing and existing["hostname"] != machine.hostname:
        if existing_db:
            existing_db.close()
        err_console.print(
            f"\n  [yellow]Warning:[/yellow] Label [bold]{resolved_label!r}[/bold] is already"
            f" used by [bold]{existing['hostname']}[/bold].\n"
            f"  Duplicate labels break [cyan]brewster diff[/cyan] and"
            f" [cyan]brewster install-missing[/cyan].\n"
            f"  Run [bold]brewster machines[/bold] to see all registered machines."
        )
        if not yes:
            confirmed = Confirm.ask("  Use this label anyway?", default=False)
            if not confirmed:
                db.close()
                sys.exit(1)

    machine_id = db.upsert_machine(
        hostname=machine.hostname,
        label=machine.label,
        platform=machine.platform,
        macos_version=machine.macos_version,
        brew_prefix=machine.brew_prefix,
    )
    db.close()

    _setup_file_logging(logs_dir, machine.hostname)
    log.info("init: registered %s (%s), db=%s", machine.label, machine.hostname, db_file)

    console.print()
    console.print(f"  [green]✓[/green] Registered [bold]{machine.label}[/bold] ({machine.hostname})")
    console.print(f"  [green]✓[/green] Databases: [dim]{databases_dir}[/dim]")
    console.print(f"  [green]✓[/green] Logs:      [dim]{logs_dir}[/dim]")
    console.print()
    console.print("  Run [bold cyan]brewster sync[/bold cyan] to snapshot your packages.")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

@cli.command()
@_db_path_option
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output.")
@click.option("--no-taps", is_flag=True, help="Skip tap resolution (faster).")
def sync(db_path: Optional[str], quiet: bool, no_taps: bool):
    """Snapshot this machine's installed packages into the DB."""
    from .sync import sync_to_db

    assert_brew_available()

    cfg = load_config()
    label = get_label(cfg)
    machine = MachineInfo(label=label)

    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)
    logs_dir = get_logs_dir(config=cfg, cli_override=db_path)

    _setup_file_logging(logs_dir, machine.hostname)

    databases_dir.mkdir(parents=True, exist_ok=True)
    db = BrewsterDB(db_path_for_machine(databases_dir, machine.hostname))
    db.open()

    machine_id = db.upsert_machine(
        hostname=machine.hostname,
        label=machine.label,
        platform=machine.platform,
        macos_version=machine.macos_version,
        brew_prefix=machine.brew_prefix,
    )

    if not quiet:
        console.print(
            f"[cyan]↻[/cyan] Syncing [bold]{machine.label}[/bold] ({machine.hostname})…"
        )

    resolve_taps = not no_taps
    if not quiet and resolve_taps:
        console.print("  [dim]Resolving tap information (pass --no-taps to skip)…[/dim]")

    summary = sync_to_db(db, machine_id, quiet=quiet, resolve_taps=resolve_taps)
    db.close()

    log.info(
        "sync: %s (%s) — %d formulae, %d casks",
        machine.label, machine.hostname, summary["formulae"], summary["casks"],
    )

    if not quiet:
        console.print(
            f"[green]✓[/green] Synced "
            f"[bold]{summary['formulae']}[/bold] formulae and "
            f"[bold]{summary['casks']}[/bold] casks."
        )


# ---------------------------------------------------------------------------
# machines
# ---------------------------------------------------------------------------

@cli.command()
@_db_path_option
def machines(db_path: Optional[str]):
    """List all registered machines and their last sync time."""
    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)

    rows = list(iter_all_machines(databases_dir))
    if not rows:
        console.print("[dim]No machines registered yet. Run [bold]brewster init[/bold].[/dim]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
    table.add_column("Label", style="bold")
    table.add_column("Hostname", style="dim")
    table.add_column("Platform")
    table.add_column("macOS")
    table.add_column("Brew Prefix", style="dim")
    table.add_column("Last Sync")

    for db, r in rows:
        last_seen = r["last_seen"][:19].replace("T", " ") if r["last_seen"] else "—"
        table.add_row(
            r["label"],
            r["hostname"],
            r["platform"] or "—",
            r["macos_version"] or "—",
            r["brew_prefix"] or "—",
            last_seen,
        )
        db.close()

    console.print(table)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command("list")
@_db_path_option
@click.option("--machine", "-m", default=None,
              help="Machine label or hostname (default: this machine).")
@click.option("--formulae", "kind", flag_value="formulae", default=True)
@click.option("--casks", "kind", flag_value="casks")
@click.option("--all", "kind", flag_value="all")
@click.option("--tap", default=None, help="Filter by tap name.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_packages(
    db_path: Optional[str],
    machine: Optional[str],
    kind: str,
    tap: Optional[str],
    as_json: bool,
):
    """List installed packages for a machine."""
    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)

    if machine:
        db, machine_row = _resolve_machine_db(databases_dir, machine)
    else:
        label = get_label(cfg)
        hostname = MachineInfo().hostname
        db, machine_row = find_machine_db(databases_dir, label or hostname)
        if db is None:
            err_console.print(
                "[red]✗[/red] This machine hasn't been synced yet. "
                "Run [bold]brewster sync[/bold] first."
            )
            sys.exit(1)

    machine_id = machine_row["id"]
    machine_label = machine_row["label"]

    formulae_rows = db.get_formulae(machine_id) if kind in ("formulae", "all") else []
    casks_rows = db.get_casks(machine_id) if kind in ("casks", "all") else []
    db.close()

    if tap:
        formulae_rows = [r for r in formulae_rows if r["tap"] == tap]
        casks_rows = [r for r in casks_rows if r["tap"] == tap]

    if as_json:
        output = {
            "machine": machine_label,
            "formulae": [dict(r) for r in formulae_rows],
            "casks": [dict(r) for r in casks_rows],
        }
        click.echo(_json.dumps(output, indent=2))
        return

    def _render_table(rows, title: str):
        if not rows:
            console.print(f"[dim]{title}: none.[/dim]")
            return
        table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            title=f"[bold]{title}[/bold] — {machine_label}",
        )
        table.add_column("Name", style="bold")
        table.add_column("Version", style="dim")
        table.add_column("Tap", style="dim")
        for r in rows:
            table.add_row(r["name"], r["version"], r["tap"] or "[dim]core[/dim]")
        console.print(table)

    if kind in ("formulae", "all"):
        _render_table(formulae_rows, "Formulae")
    if kind in ("casks", "all"):
        _render_table(casks_rows, "Casks")


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

@cli.command()
@_db_path_option
@click.argument("machine_a")
@click.argument("machine_b")
@click.option("--formulae/--no-formulae", default=True, show_default=True)
@click.option("--casks/--no-casks", default=True, show_default=True)
@click.option("--versions", is_flag=True, help="Show version mismatches for common packages.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def diff(
    db_path: Optional[str],
    machine_a: str,
    machine_b: str,
    formulae: bool,
    casks: bool,
    versions: bool,
    as_json: bool,
):
    """Show package differences between two machines."""
    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)

    db_a, row_a = _resolve_machine_db(databases_dir, machine_a)
    db_b, row_b = _resolve_machine_db(databases_dir, machine_b)

    label_a = row_a["label"]
    label_b = row_b["label"]

    formula_diff = None
    cask_diff = None

    if formulae:
        fa = db_a.get_formulae(row_a["id"])
        fb = db_b.get_formulae(row_b["id"])
        formula_diff = compute_diff(label_a, label_b, fa, fb, kind="formulae")

    if casks:
        ca = db_a.get_casks(row_a["id"])
        cb = db_b.get_casks(row_b["id"])
        cask_diff = compute_diff(label_a, label_b, ca, cb, kind="casks")

    db_a.close()
    db_b.close()

    if as_json:
        def _diff_to_dict(d: DiffResult) -> dict:
            return {
                "kind": d.kind,
                "only_a": [{"name": p.name, "version": p.version, "tap": p.tap} for p in d.only_a],
                "only_b": [{"name": p.name, "version": p.version, "tap": p.tap} for p in d.only_b],
                "common_count": len(d.common),
                "version_mismatches": [
                    {"name": pa.name, machine_a: pa.version, machine_b: pb.version}
                    for pa, pb in d.version_diff
                ],
            }
        out = {"machine_a": label_a, "machine_b": label_b}
        if formula_diff:
            out["formulae"] = _diff_to_dict(formula_diff)
        if cask_diff:
            out["casks"] = _diff_to_dict(cask_diff)
        click.echo(_json.dumps(out, indent=2))
        return

    console.print()
    console.print(
        Panel.fit(
            f"[bold white]Diff:[/bold white] "
            f"[yellow]{label_a}[/yellow] [dim]vs[/dim] [green]{label_b}[/green]",
            border_style="dim",
        )
    )
    console.print()

    if formula_diff:
        _render_diff_section(formula_diff, show_versions=versions)
        console.print()

    if cask_diff:
        _render_diff_section(cask_diff, show_versions=versions)
        console.print()

    any_diff = (formula_diff and formula_diff.has_differences) or (
        cask_diff and cask_diff.has_differences
    )
    if any_diff:
        console.print(
            f"  [dim]Tip: run [bold]brewster install-missing {label_a}[/bold] "
            f"to install packages from {label_a} that are missing here.[/dim]"
        )


# ---------------------------------------------------------------------------
# install-missing
# ---------------------------------------------------------------------------

@cli.command()
@_db_path_option
@click.argument("source_machine")
@click.option("--formulae/--no-formulae", default=True, show_default=True)
@click.option("--casks/--no-casks", default=True, show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
def install_missing(
    db_path: Optional[str],
    source_machine: str,
    formulae: bool,
    casks: bool,
    dry_run: bool,
    yes: bool,
):
    """Install packages from SOURCE_MACHINE that are missing on this machine."""
    assert_brew_available()

    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)
    logs_dir = get_logs_dir(config=cfg, cli_override=db_path)

    db_source, source_row = _resolve_machine_db(databases_dir, source_machine)

    hostname = MachineInfo().hostname
    label = get_label(cfg)
    db_this, this_row = find_machine_db(databases_dir, label or hostname)
    if db_this is None:
        err_console.print(
            "[red]✗[/red] This machine hasn't been synced yet. "
            "Run [bold]brewster sync[/bold] first."
        )
        db_source.close()
        sys.exit(1)

    _setup_file_logging(logs_dir, hostname)

    source_label = source_row["label"]
    this_label = this_row["label"]

    formula_diff = None
    cask_diff = None

    if formulae:
        fa = db_source.get_formulae(source_row["id"])
        fb = db_this.get_formulae(this_row["id"])
        formula_diff = compute_diff(source_label, this_label, fa, fb, kind="formulae")

    if casks:
        ca = db_source.get_casks(source_row["id"])
        cb = db_this.get_casks(this_row["id"])
        cask_diff = compute_diff(source_label, this_label, ca, cb, kind="casks")

    db_source.close()
    db_this.close()

    missing_formulae: list[PackageRow] = formula_diff.missing_on_b() if formula_diff else []
    missing_casks: list[PackageRow] = cask_diff.missing_on_b() if cask_diff else []

    if not missing_formulae and not missing_casks:
        console.print(
            f"[green]✓[/green] No missing packages — this machine already has everything from "
            f"[bold]{source_label}[/bold]."
        )
        return

    console.print()
    console.print(
        Panel.fit(
            f"Packages on [bold yellow]{source_label}[/bold yellow] "
            f"missing from [bold green]{this_label}[/bold green]",
            border_style="dim",
        )
    )

    if missing_formulae:
        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
        table.add_column("Formula", style="bold")
        table.add_column("Version", style="dim")
        table.add_column("Tap", style="dim")
        for p in missing_formulae:
            table.add_row(p.name, p.version, p.tap or "[dim]core[/dim]")
        console.print(table)

    if missing_casks:
        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
        table.add_column("Cask", style="bold")
        table.add_column("Version", style="dim")
        table.add_column("Tap", style="dim")
        for p in missing_casks:
            table.add_row(p.name, p.version, p.tap or "[dim]core[/dim]")
        console.print(table)

    console.print()

    if dry_run:
        console.print("[dim]Dry run — nothing will be installed.[/dim]")
        install_packages(missing_formulae, missing_casks, dry_run=True)
        return

    if not yes:
        proceed = Confirm.ask(
            f"  Install [bold]{len(missing_formulae) + len(missing_casks)}[/bold] "
            f"missing package(s)?",
            default=False,
        )
        if not proceed:
            console.print("[dim]Aborted.[/dim]")
            return

    def _on_progress(name, cask, success, error, dry_run):
        kind = "cask" if cask else "formula"
        if success:
            console.print(f"  [green]✓[/green] {name} ({kind})")
        else:
            console.print(f"  [red]✗[/red] {name} ({kind}) — {error}")

    result = install_packages(
        missing_formulae,
        missing_casks,
        dry_run=False,
        progress_callback=_on_progress,
    )

    installed_names = [n for n, _ in result.succeeded] if hasattr(result, "succeeded") else []
    log.info(
        "install-missing: installed %d package(s) from %s: %s",
        len(result.succeeded), source_label,
        ", ".join(n for n, _ in result.succeeded) or "none",
    )

    console.print()
    console.print(
        f"[green]✓[/green] Done — "
        f"[bold]{len(result.succeeded)}[/bold] installed, "
        f"[red]{len(result.failed)}[/red] failed."
    )

    if result.failed:
        console.print("\n  [red]Failed:[/red]")
        for name, err in result.failed:
            console.print(f"    [bold]{name}[/bold]: {err}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
@_db_path_option
def status(db_path: Optional[str]):
    """Show sync directory, machine DBs found, and row counts."""
    cfg = load_config()
    sync_root = get_sync_root(config=cfg, cli_override=db_path)
    databases_dir = sync_root / "databases"
    logs_dir = sync_root / "logs"

    console.print()
    console.print(Panel.fit("[bold cyan]Brewster Status[/bold cyan]", border_style="cyan"))
    console.print()

    console.print(f"  Config file:   [dim]{CONFIG_FILE}[/dim]")
    console.print(f"  Sync root:     [dim]{sync_root}[/dim]")
    console.print(f"  Databases:     [dim]{databases_dir}[/dim]")
    console.print(f"  Logs:          [dim]{logs_dir}[/dim]")

    if not databases_dir.exists():
        console.print(f"\n  [red]Databases directory not found.[/red] Run [bold]brewster init[/bold].")
        return

    all_machines = list(iter_all_machines(databases_dir))
    if not all_machines:
        console.print("\n  [dim]No machines registered yet.[/dim]")
        return

    hostname = MachineInfo().hostname
    total_f = total_c = 0

    console.print()
    console.print("  [bold]Machines:[/bold]")
    for db, m in all_machines:
        stats = db.stats()
        total_f += stats["formulae"]
        total_c += stats["casks"]
        is_this = m["hostname"] == hostname
        marker = " [cyan]← this machine[/cyan]" if is_this else ""
        last = m["last_seen"][:10] if m["last_seen"] else "never"
        console.print(
            f"    [bold]{m['label']}[/bold] ({m['hostname']}) "
            f"— {stats['formulae']} formulae, {stats['casks']} casks "
            f"— last sync {last}{marker}"
        )
        db.close()

    console.print()
    console.print(f"  Total formulae: [bold]{total_f}[/bold]")
    console.print(f"  Total casks:    [bold]{total_c}[/bold]")
    console.print()


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.command("config")
@click.option("--set", "set_value", metavar="KEY=VALUE", help="Set a config value.")
@click.option("--json", "as_json", is_flag=True, help="Output config as JSON.")
def config_cmd(set_value: Optional[str], as_json: bool):
    """View or set Brewster configuration values.

    \b
    Keys:
      machine.label     — friendly name for this machine
      database.path     — sync root directory path
    """
    if set_value:
        if "=" not in set_value:
            err_console.print("[red]✗[/red] Use KEY=VALUE format, e.g. [bold]machine.label=home-mac[/bold]")
            sys.exit(1)
        key, _, value = set_value.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "machine.label":
            set_label(value)
            console.print(f"[green]✓[/green] Set [bold]machine.label[/bold] = [bold]{value}[/bold]")
        elif key == "database.path":
            set_sync_root(value)
            console.print(f"[green]✓[/green] Set [bold]database.path[/bold] = [bold]{value}[/bold]")
        else:
            err_console.print(f"[red]✗[/red] Unknown key [bold]{key!r}[/bold].")
            sys.exit(1)
        return

    cfg = load_config()

    if as_json:
        click.echo(_json.dumps(cfg, indent=2))
        return

    console.print()
    console.print(f"  [dim]Config file: {CONFIG_FILE}[/dim]")
    console.print()

    if not cfg:
        console.print("  [dim]No config set. Run [bold]brewster init[/bold].[/dim]")
        return

    for section, values in cfg.items():
        console.print(f"  [bold cyan][{section}][/bold cyan]")
        for k, v in values.items():
            console.print(f"    {k} = [dim]{v}[/dim]")
        console.print()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command("export")
@_db_path_option
@click.option("--output", "-o", default=None, metavar="FILE",
              help="Write to FILE instead of stdout.")
@click.option("--machine", "-m", default=None,
              help="Export only this machine (label or hostname).")
def export_db(db_path: Optional[str], output: Optional[str], machine: Optional[str]):
    """Export all machine databases to a single JSON file."""
    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)

    if machine:
        db, row = _resolve_machine_db(databases_dir, machine)
        sources = [(db, row)]
    else:
        sources = list(iter_all_machines(databases_dir))

    machines_out = []
    for db, row in sources:
        formulae = db.get_formulae(row["id"])
        casks = db.get_casks(row["id"])
        machines_out.append({
            "hostname": row["hostname"],
            "label": row["label"],
            "platform": row["platform"],
            "macos_version": row["macos_version"],
            "brew_prefix": row["brew_prefix"],
            "last_seen": row["last_seen"],
            "formulae": [{"name": r["name"], "version": r["version"], "tap": r["tap"]} for r in formulae],
            "casks": [{"name": r["name"], "version": r["version"], "tap": r["tap"]} for r in casks],
        })
        db.close()

    payload = {
        "brewster_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "machines": machines_out,
    }
    json_str = _json.dumps(payload, indent=2)

    if output:
        out_path = Path(output).expanduser()
        out_path.write_text(json_str)
        console.print(
            f"[green]✓[/green] Exported [bold]{len(machines_out)}[/bold] machine(s) "
            f"to [dim]{out_path}[/dim]"
        )
    else:
        click.echo(json_str)


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

@cli.command("import")
@_db_path_option
@click.argument("file")
@click.option("--dry-run", is_flag=True, help="Show what would be imported without writing.")
def import_db(db_path: Optional[str], file: str, dry_run: bool):
    """Import machines and packages from a JSON export file."""
    src = Path(file).expanduser()
    if not src.exists():
        err_console.print(f"[red]✗[/red] File not found: [dim]{src}[/dim]")
        sys.exit(1)

    try:
        payload = _json.loads(src.read_text())
    except _json.JSONDecodeError as exc:
        err_console.print(f"[red]✗[/red] Invalid JSON: {exc}")
        sys.exit(1)

    machines = payload.get("machines")
    if not isinstance(machines, list):
        err_console.print("[red]✗[/red] Invalid export file: missing 'machines' list.")
        sys.exit(1)

    if not machines:
        console.print("[dim]Nothing to import — file contains no machines.[/dim]")
        return

    if dry_run:
        console.print(f"[dim]Dry run — would import {len(machines)} machine(s):[/dim]")
        for m in machines:
            nf = len(m.get("formulae") or [])
            nc = len(m.get("casks") or [])
            console.print(
                f"  [bold]{m.get('label')}[/bold] ({m.get('hostname')}) "
                f"— {nf} formulae, {nc} casks"
            )
        return

    cfg = load_config()
    databases_dir = get_databases_dir(config=cfg, cli_override=db_path)
    logs_dir = get_logs_dir(config=cfg, cli_override=db_path)
    databases_dir.mkdir(parents=True, exist_ok=True)

    hostname = MachineInfo().hostname
    _setup_file_logging(logs_dir, hostname)

    for m in machines:
        # Warn about label collisions with a different hostname.
        existing_db, existing = find_machine_db(databases_dir, m.get("label", ""))
        if existing and existing["hostname"] != m.get("hostname"):
            err_console.print(
                f"  [yellow]Warning:[/yellow] Label [bold]{m['label']!r}[/bold] is already "
                f"used by [bold]{existing['hostname']}[/bold] — "
                f"it will be reassigned to [bold]{m['hostname']}[/bold]."
            )
        if existing_db:
            existing_db.close()

        db_file = db_path_for_machine(databases_dir, m["hostname"])
        db = BrewsterDB(db_file)
        db.open()
        mid = db.upsert_machine(
            hostname=m["hostname"],
            label=m["label"],
            platform=m.get("platform") or "",
            macos_version=m.get("macos_version"),
            brew_prefix=m.get("brew_prefix"),
        )
        db.replace_formulae(mid, m.get("formulae") or [])
        db.replace_casks(mid, m.get("casks") or [])
        db.close()

    log.info("import: imported %d machine(s) from %s", len(machines), src)
    console.print(
        f"[green]✓[/green] Imported [bold]{len(machines)}[/bold] machine(s) "
        f"from [dim]{src}[/dim]"
    )
