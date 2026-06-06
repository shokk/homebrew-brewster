"""
installer.py — Installs missing packages on the current machine.

Uses `brew install` and `brew install --cask` via subprocess.
Supports dry-run, interactive selection, and tap-aware installs.
"""

from __future__ import annotations

import subprocess
import logging
from typing import Optional

from .diff import PackageRow

log = logging.getLogger(__name__)


class InstallResult:
    def __init__(self) -> None:
        self.succeeded: list[str] = []
        self.failed: list[tuple[str, str]] = []  # (name, error message)
        self.skipped: list[str] = []

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.failed) + len(self.skipped)


def _install_one(package: PackageRow, cask: bool = False, dry_run: bool = False) -> Optional[str]:
    """
    Install a single package. Returns an error string on failure, None on success.
    Handles tap-qualified installs (e.g. 'stripe/stripe-cli/stripe').
    """
    if dry_run:
        kind = "cask" if cask else "formula"
        log.info("[dry-run] Would install %s (%s)", package.name, kind)
        return None

    cmd = ["brew", "install"]
    if cask:
        # --adopt registers pre-existing apps (installed outside Homebrew) into
        # Homebrew's tracking so they appear in `brew list --cask` afterward.
        cmd.extend(["--cask", "--adopt"])

    # If the package comes from a non-core tap, pass the fully-qualified name
    # so brew doesn't have to search across taps.
    if package.tap:
        install_target = f"{package.tap}/{package.name}"
    else:
        install_target = package.name

    cmd.append(install_target)

    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or "Unknown error"
    return None


def install_packages(
    formulae: list[PackageRow],
    casks: list[PackageRow],
    dry_run: bool = False,
    progress_callback=None,
) -> InstallResult:
    """
    Install a list of formulae and casks.

    Args:
        formulae / casks    — packages to install
        dry_run             — if True, log but don't actually install
        progress_callback   — optional callable(name, cask, success, error)
                              called after each install attempt
    """
    result = InstallResult()

    all_packages = [(p, False) for p in formulae] + [(p, True) for p in casks]

    for package, is_cask in all_packages:
        error = _install_one(package, cask=is_cask, dry_run=dry_run)

        if dry_run:
            result.skipped.append(package.name)
        elif error:
            result.failed.append((package.name, error))
        else:
            result.succeeded.append(package.name)

        if progress_callback:
            progress_callback(
                name=package.name,
                cask=is_cask,
                success=(error is None),
                error=error,
                dry_run=dry_run,
            )

    return result
