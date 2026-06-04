"""
config.py — Persistent per-machine configuration for Brewster.

Stored at ~/.config/brewster/config.toml.
Handles label, DB path, and any future per-machine settings.

tomllib is stdlib in Python 3.11+. For 3.9/3.10 we fall back to tomli (vendored).
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# stdlib tomllib (3.11+) or vendored tomli fallback
try:
    import tomllib  # type: ignore
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

CONFIG_DIR = Path.home() / ".config" / "brewster"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# ---------------------------------------------------------------------------
# Well-known sync backend paths
# ---------------------------------------------------------------------------

ICLOUD_PATH = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "com~apple~CloudDocs"
    / "Brewster"
    / "brewster.db"
)

GOOGLE_DRIVE_BASE = Path.home() / "Library" / "CloudStorage"

DROPBOX_PATH = Path.home() / "Dropbox" / "Brewster" / "brewster.db"
ONEDRIVE_PATH = Path.home() / "OneDrive" / "Brewster" / "brewster.db"


def _detect_google_drive() -> Optional[Path]:
    """Find the first Google Drive mount under ~/Library/CloudStorage/."""
    if not GOOGLE_DRIVE_BASE.exists():
        return None
    for candidate in GOOGLE_DRIVE_BASE.iterdir():
        if candidate.name.startswith("GoogleDrive-"):
            return candidate / "My Drive" / "Brewster" / "brewster.db"
    return None


def detect_sync_backends() -> list[dict]:
    """
    Return a list of detected sync backends, each as:
        {"name": str, "key": str, "path": Path, "available": bool}
    """
    backends = []

    # iCloud
    icloud_root = ICLOUD_PATH.parents[1]
    backends.append(
        {
            "name": "iCloud Drive",
            "key": "icloud",
            "path": ICLOUD_PATH,
            "available": icloud_root.exists(),
        }
    )

    # Dropbox
    backends.append(
        {
            "name": "Dropbox",
            "key": "dropbox",
            "path": DROPBOX_PATH,
            "available": DROPBOX_PATH.parent.parent.exists(),
        }
    )

    # Google Drive
    gdrive_path = _detect_google_drive()
    if gdrive_path:
        backends.append(
            {
                "name": "Google Drive",
                "key": "gdrive",
                "path": gdrive_path,
                "available": True,
            }
        )

    # OneDrive
    backends.append(
        {
            "name": "OneDrive",
            "key": "onedrive",
            "path": ONEDRIVE_PATH,
            "available": ONEDRIVE_PATH.parent.parent.exists(),
        }
    )

    # Custom / network mount — always offered
    backends.append(
        {
            "name": "Custom path",
            "key": "custom",
            "path": None,
            "available": True,
        }
    )

    return backends


# ---------------------------------------------------------------------------
# Config read / write
# ---------------------------------------------------------------------------

def _write_toml(data: dict, path: Path) -> None:
    """
    Minimal TOML writer — avoids a tomli-w dep by hand-formatting.
    Only needs to handle the flat-ish structure Brewster actually uses.
    """
    lines = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            if val is None:
                continue
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            else:
                lines.append(f"{key} = {val}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_config() -> dict:
    """Load config from disk. Returns empty dict if file doesn't exist."""
    if not CONFIG_FILE.exists():
        return {}
    if tomllib is None:
        log.warning("No TOML parser available; config not loaded.")
        return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _write_toml(config, CONFIG_FILE)
    log.debug("Config written to %s", CONFIG_FILE)


def get_label(config: Optional[dict] = None) -> Optional[str]:
    cfg = config or load_config()
    return cfg.get("machine", {}).get("label")


def get_db_path(config: Optional[dict] = None, cli_override: Optional[str] = None) -> Path:
    """
    Resolve the DB path in priority order:
      1. --db-path CLI flag
      2. config.toml [database] path
      3. iCloud default
    """
    if cli_override:
        return Path(cli_override).expanduser()

    cfg = config or load_config()
    configured = cfg.get("database", {}).get("path")
    if configured:
        return Path(configured).expanduser()

    return ICLOUD_PATH


def set_label(label: str) -> None:
    cfg = load_config()
    cfg.setdefault("machine", {})["label"] = label
    save_config(cfg)


def set_db_path(path: str) -> None:
    cfg = load_config()
    cfg.setdefault("database", {})["path"] = str(path)
    save_config(cfg)
