"""
sync.py — Reads installed Homebrew formulae and casks, writes them to the DB.

Uses `brew list --versions` and `brew list --cask --versions` for speed.
Uses `brew info --json=v2` in a second pass to resolve tap names (batched).

The tap-resolution pass is best-effort: if brew info is slow or fails, we
still write the packages — just without tap metadata.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raw brew subprocess helpers
# ---------------------------------------------------------------------------

def _run(args: list[str], timeout: int = 60) -> str:
    """Run a command, return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command {args!r} failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout


def _brew_list_formulae() -> list[dict]:
    """
    Parse `brew list --versions` output.
    Each line: "package_name version1 [version2 ...]"
    We take the last (most recent) version token.

    Returns list of {"name": str, "version": str}
    """
    raw = _run(["brew", "list", "--versions", "--formula"])
    packages = []
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            packages.append({"name": parts[0], "version": parts[-1]})
    log.debug("Found %d formulae", len(packages))
    return packages


def _brew_list_casks() -> list[dict]:
    """
    Parse `brew list --cask --versions` output.
    Each line: "cask_name version"

    brew can exit non-zero on some systems (e.g. due to broken receipts or
    warnings) even when it successfully printed the cask list to stdout.
    We use stdout regardless, and log stderr at WARNING so problems are visible.
    """
    result = subprocess.run(
        ["brew", "list", "--cask", "--versions"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr_msg = result.stderr.strip()
        if stderr_msg:
            log.warning("brew list --cask --versions exited %d: %s", result.returncode, stderr_msg)
        else:
            log.warning("brew list --cask --versions exited %d (no stderr)", result.returncode)

    raw = result.stdout
    casks = []
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            casks.append({"name": parts[0], "version": parts[-1]})
        elif len(parts) == 1:
            # Cask installed but version unknown
            casks.append({"name": parts[0], "version": "unknown"})
    log.debug("Found %d casks", len(casks))
    return casks


def _brew_info_json(names: list[str], kind: str = "formula") -> dict[str, dict]:
    """
    Call `brew info --json=v2 <names...>` and return a dict keyed by package name.
    kind: "formula" or "cask"

    Returns {} on any failure (tap info is best-effort).
    """
    if not names:
        return {}

    # brew info accepts multiple names in one call — batch in chunks of 100
    # to avoid hitting ARG_MAX on large installs.
    result: dict[str, dict] = {}
    chunk_size = 100
    for i in range(0, len(names), chunk_size):
        chunk = names[i : i + chunk_size]
        flag = "--formula" if kind == "formula" else "--cask"
        try:
            raw = _run(
                ["brew", "info", "--json=v2", flag] + chunk,
                timeout=120,
            )
            data = json.loads(raw)
            key = "formulae" if kind == "formula" else "casks"
            for item in data.get(key, []):
                name = item.get("token") if kind == "cask" else item.get("name")
                if name:
                    result[name] = item
        except (RuntimeError, json.JSONDecodeError) as exc:
            log.debug("brew info failed for chunk (tap info will be missing): %s", exc)

    return result


def _extract_tap(info: dict, kind: str = "formula") -> Optional[str]:
    """
    Pull the tap name out of a brew info JSON item.
    Returns None for homebrew/core (the implicit default), so we only store
    non-core taps (meaningful signal).
    """
    if kind == "formula":
        tap = info.get("tap", "")
    else:
        tap = info.get("tap", "")

    if not tap or tap == "homebrew/core" or tap == "homebrew/cask":
        return None
    return tap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_formulae(resolve_taps: bool = True) -> list[dict]:
    """
    Return a list of installed formulae as dicts:
        {"name": str, "version": str, "tap": str | None}
    """
    packages = _brew_list_formulae()

    if resolve_taps and packages:
        names = [p["name"] for p in packages]
        info_map = _brew_info_json(names, kind="formula")
        for p in packages:
            info = info_map.get(p["name"], {})
            p["tap"] = _extract_tap(info, kind="formula") if info else None
    else:
        for p in packages:
            p.setdefault("tap", None)

    return packages


def collect_casks(resolve_taps: bool = True) -> list[dict]:
    """
    Return a list of installed casks as dicts:
        {"name": str, "version": str, "tap": str | None}
    """
    casks = _brew_list_casks()

    if resolve_taps and casks:
        names = [c["name"] for c in casks]
        info_map = _brew_info_json(names, kind="cask")
        for c in casks:
            info = info_map.get(c["name"], {})
            c["tap"] = _extract_tap(info, kind="cask") if info else None
    else:
        for c in casks:
            c.setdefault("tap", None)

    return casks


def sync_to_db(db, machine_id: int, quiet: bool = False, resolve_taps: bool = True) -> dict:
    """
    Full sync: collect formulae + casks and write to DB.
    Returns a summary dict: {"formulae": int, "casks": int}
    """
    if not quiet:
        log.info("Collecting formulae…")
    formulae = collect_formulae(resolve_taps=resolve_taps)

    if not quiet:
        log.info("Collecting casks…")
    casks = collect_casks(resolve_taps=resolve_taps)

    db.replace_formulae(machine_id, formulae)
    db.replace_casks(machine_id, casks)

    return {"formulae": len(formulae), "casks": len(casks)}
