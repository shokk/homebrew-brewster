"""
machine.py — Machine identity detection for Brewster.

Resolves hostname, CPU architecture, macOS version, and Homebrew prefix.
Label is read from config (set via `brewster init --label`), falling back
to the hostname if not yet configured.
"""

from __future__ import annotations

import platform
import socket
import subprocess
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def get_hostname() -> str:
    """Return the machine's short hostname (not FQDN)."""
    return socket.gethostname().split(".")[0]


def get_platform() -> str:
    """Return 'arm64' or 'x86_64'."""
    machine = platform.machine()
    # platform.machine() returns 'arm64' on Apple Silicon, 'x86_64' on Intel
    return machine if machine else "unknown"


def get_macos_version() -> Optional[str]:
    """Return macOS version string, e.g. '14.5', or None if not macOS."""
    if platform.system() != "Darwin":
        return None
    return platform.mac_ver()[0] or None


def get_brew_prefix() -> Optional[str]:
    """
    Return the Homebrew prefix path (e.g. /opt/homebrew on ARM, /usr/local on Intel).
    Returns None if brew is not found.
    """
    try:
        result = subprocess.run(
            ["brew", "--prefix"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def assert_brew_available() -> None:
    """Raise a clear error if brew is not on PATH."""
    if get_brew_prefix() is None:
        raise EnvironmentError(
            "Homebrew not found on PATH. "
            "Install it from https://brew.sh before using Brewster."
        )


class MachineInfo:
    """
    Snapshot of this machine's identity.

    Attributes:
        hostname     — system hostname (auto-detected, immutable key)
        label        — human-friendly name (user-set, defaults to hostname)
        platform     — 'arm64' or 'x86_64'
        macos_version — e.g. '14.5'
        brew_prefix  — e.g. '/opt/homebrew'
    """

    def __init__(
        self,
        label: Optional[str] = None,
    ) -> None:
        self.hostname: str = get_hostname()
        self.label: str = label or self.hostname
        self.platform: str = get_platform()
        self.macos_version: Optional[str] = get_macos_version()
        self.brew_prefix: Optional[str] = get_brew_prefix()

    def __repr__(self) -> str:
        return (
            f"MachineInfo("
            f"hostname={self.hostname!r}, "
            f"label={self.label!r}, "
            f"platform={self.platform!r}, "
            f"macos={self.macos_version!r})"
        )

    def as_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "label": self.label,
            "platform": self.platform,
            "macos_version": self.macos_version,
            "brew_prefix": self.brew_prefix,
        }
