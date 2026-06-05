# Brewster 🍺

Track and sync your Homebrew packages across all your machines — via iCloud, Dropbox, Google Drive, OneDrive, or any shared filesystem.

```
brewster diff work-mac home-mac

  Formulae Differences
  ─────────────────────────────────────────────────────
  Only on work-mac         │  Only on home-mac
  postgresql@16  16.2      │  imagemagick   7.1.1
  redis          7.2.4     │  yt-dlp        2024.4.9
  stripe-cli     1.19.0    │

  Casks Differences
  ─────────────────────────────────────────────────────
  Only on work-mac         │  Only on home-mac
  docker         4.29      │  vlc           3.0.21
  tableplus      6.1       │

  42 formulae · 8 casks in common
```

## Installation

```bash
brew tap shokk/brewster
brew install brewster
```

## Quick Start

```bash
# First-time setup on each machine (detects iCloud, Dropbox, etc.)
brewster init --label "work-mac"

# Snapshot this machine's packages
brewster sync

# On your other machine:
brewster init --label "home-mac"
brewster sync

# Now compare:
brewster diff work-mac home-mac

# Install anything you're missing:
brewster install-missing work-mac
```

## Commands

| Command | Description |
|---|---|
| `brewster init [--label NAME] [--db-path PATH]` | First-time setup; detects sync backends |
| `brewster sync [--quiet] [--no-taps]` | Snapshot this machine → DB |
| `brewster machines` | List all registered machines |
| `brewster list [--machine NAME] [--all\|--casks\|--formulae]` | List packages |
| `brewster diff <A> <B> [--versions]` | Compare packages between two machines |
| `brewster install-missing <SOURCE> [--dry-run] [-y]` | Install packages missing from SOURCE |
| `brewster status` | DB path, sync state, row counts |
| `brewster config [--set KEY=VALUE]` | View or set config |
| `brewster export [-o FILE] [-m MACHINE]` | Export DB to JSON (stdout or file) |
| `brewster import FILE [--dry-run]` | Import machines and packages from JSON |

## Sync Backends

Brewster creates a `databases/` folder inside a sync root you choose. Each machine writes its own `.db` file — no shared file, no conflicts.

| Backend | Default sync root |
|---|---|
| iCloud Drive | `~/Library/Mobile Documents/com~apple~CloudDocs/Brewster/` |
| Dropbox | `~/Dropbox/Brewster/` |
| Google Drive | `~/Library/CloudStorage/GoogleDrive-.../My Drive/Brewster/` |
| OneDrive | `~/OneDrive/Brewster/` |
| Custom / NAS | Any directory via `--db-path` or `brewster config --set database.path=...` |

The resulting layout:
```
Brewster/
  databases/
    work-mac.db
    home-mac.db
  logs/
    work-mac.log
    home-mac.log
```

`brewster init` detects which providers are installed and lets you choose interactively.

## Auto-Sync on Login

```bash
brew services start brewster
```

This runs `brewster sync --quiet` once at login via Homebrew Services.


## How It Works

- Each machine runs `brewster sync`, which calls `brew list --versions` + `brew list --cask --versions` and writes to its own `databases/{hostname}.db` file.
- Because each machine owns exactly one file, there are no write conflicts — even if multiple machines sync simultaneously.
- WAL journal mode is enabled with a full checkpoint on every close, so no `-wal`/`-shm` sidecar files are left for the sync provider to mishandle.
- `brewster diff` and `brewster install-missing` read individual machine DB files — they work as long as your sync provider has delivered the latest versions.
- Every mutating command (`init`, `sync`, `install-missing`, `import`) appends a line to `logs/{hostname}.log` in the sync root.

## Configuration

Config lives at `~/.config/brewster/config.toml`:

```toml
[machine]
label = "work-mac"

[database]
path = "~/Library/Mobile Documents/com~apple~CloudDocs/Brewster"
```

Override the sync root for a single command with `--db-path DIR` or `BREWSTER_DB_PATH` env var.

## License

MIT
