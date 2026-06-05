"""
config.py — Persistent per-machine configuration for Brewster.

Stored at ~/.config/brewster/config.toml.

Layout on the sync filesystem:
    {sync_root}/
        databases/   ← one .db per machine, named by hostname
        logs/        ← one .log per machine, named by hostname

The config key [database] path stores the sync root directory.
Migration: if an old config points to a .db file, the parent directory
is used as the sync root automatically.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

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
# Well-known sync backend root directories
# ---------------------------------------------------------------------------

ICLOUD_ROOT = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "com~apple~CloudDocs"
    / "Brewster"
)

GOOGLE_DRIVE_BASE = Path.home() / "Library" / "CloudStorage"
DROPBOX_ROOT = Path.home() / "Dropbox" / "Brewster"
ONEDRIVE_ROOT = Path.home() / "OneDrive" / "Brewster"


def _detect_google_drive_root() -> Optional[Path]:
    if not GOOGLE_DRIVE_BASE.exists():
        return None
    for candidate in GOOGLE_DRIVE_BASE.iterdir():
        if candidate.name.startswith("GoogleDrive-"):
            return candidate / "My Drive" / "Brewster"
    return None


def detect_sync_backends() -> list[dict]:
    """
    Return detected sync backends as:
        {"name": str, "key": str, "path": Path (sync root), "available": bool}
    """
    backends = []

    backends.append({
        "name": "iCloud Drive",
        "key": "icloud",
        "path": ICLOUD_ROOT,
        "available": ICLOUD_ROOT.parent.exists(),
    })

    backends.append({
        "name": "Dropbox",
        "key": "dropbox",
        "path": DROPBOX_ROOT,
        "available": DROPBOX_ROOT.parent.exists(),
    })

    gdrive = _detect_google_drive_root()
    if gdrive:
        backends.append({
            "name": "Google Drive",
            "key": "gdrive",
            "path": gdrive,
            "available": True,
        })

    backends.append({
        "name": "OneDrive",
        "key": "onedrive",
        "path": ONEDRIVE_ROOT,
        "available": ONEDRIVE_ROOT.parent.exists(),
    })

    backends.append({
        "name": "Custom path",
        "key": "custom",
        "path": None,
        "available": True,
    })

    return backends


# ---------------------------------------------------------------------------
# Config read / write
# ---------------------------------------------------------------------------

def _write_toml(data: dict, path: Path) -> None:
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


def get_sync_root(
    config: Optional[dict] = None,
    cli_override: Optional[str] = None,
) -> Path:
    """
    Resolve the sync root directory (contains databases/ and logs/).

    Priority:
      1. --db-path CLI flag
      2. [database] path in config.toml
      3. iCloud default

    Migration: if the stored path ends in .db (old single-file config),
    the parent directory is used as the sync root.
    """
    if cli_override:
        p = Path(cli_override).expanduser()
        return p.parent if p.suffix == ".db" else p

    cfg = config or load_config()
    configured = cfg.get("database", {}).get("path")
    if configured:
        p = Path(configured).expanduser()
        return p.parent if p.suffix == ".db" else p

    return ICLOUD_ROOT


def get_databases_dir(
    config: Optional[dict] = None,
    cli_override: Optional[str] = None,
) -> Path:
    return get_sync_root(config, cli_override) / "databases"


def get_logs_dir(
    config: Optional[dict] = None,
    cli_override: Optional[str] = None,
) -> Path:
    return get_sync_root(config, cli_override) / "logs"


# kept for backwards-compat callers; now returns the databases dir
def get_db_path(
    config: Optional[dict] = None,
    cli_override: Optional[str] = None,
) -> Path:
    return get_databases_dir(config, cli_override)


def set_label(label: str) -> None:
    cfg = load_config()
    cfg.setdefault("machine", {})["label"] = label
    save_config(cfg)


def set_sync_root(path: str) -> None:
    cfg = load_config()
    cfg.setdefault("database", {})["path"] = str(path)
    save_config(cfg)


def set_db_path(path: str) -> None:
    set_sync_root(path)
