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

Brewster stores everything in a single SQLite file. Point it at any location that syncs across your machines:

| Backend | Default path |
|---|---|
| iCloud Drive | `~/Library/Mobile Documents/com~apple~CloudDocs/Brewster/brewster.db` |
| Dropbox | `~/Dropbox/Brewster/brewster.db` |
| Google Drive | `~/Library/CloudStorage/GoogleDrive-.../My Drive/Brewster/brewster.db` |
| OneDrive | `~/OneDrive/Brewster/brewster.db` |
| Custom / NAS | Any path via `--db-path` or `brewster config --set database.path=...` |

`brewster init` detects which providers are installed and lets you choose interactively.

## Auto-Sync on Login

```bash
brew services start brewster
```

This runs `brewster sync --quiet` once at login via Homebrew Services.

## Configuration

Config lives at `~/.config/brewster/config.toml`:

```toml
[machine]
label = "work-mac"

[database]
path = "~/Library/Mobile Documents/com~apple~CloudDocs/Brewster/brewster.db"
```

Override the DB path for a single command with `--db-path PATH` or `BREWSTER_DB_PATH` env var.

## How It Works

- Each machine runs `brewster sync`, which calls `brew list --versions` + `brew list --cask --versions` and writes the results to the SQLite DB.
- The DB file is stored in your cloud sync folder. Each machine writes only its own rows (scoped by hostname), so concurrent writes are safe.
- WAL journal mode is enabled so interrupted syncs don't corrupt the file.
- `brewster diff` and `brewster install-missing` read the DB directly — they work as long as your sync provider has delivered the latest version.

## License

MIT
