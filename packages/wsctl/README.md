# wsctl — FauxnixOS Thread Controller

CLI tool for managing threads of continuity. 18 commands for the full thread lifecycle.

## Commands

### Thread Lifecycle
```bash
wsctl create <name> --profile win11|macos|headless --template <template>
wsctl start <name>
wsctl stop <name>
wsctl delete <name>
```

### Fork & Merge
```bash
wsctl fork <source> <target>
wsctl merge <source> <target> [--prune]
```

### Snapshots
```bash
wsctl snapshot <name> --label <label>
wsctl restore <name> <snapshot-label>
wsctl snapshots prune [--thread <name>] [--dry-run]
```

### Git
```bash
wsctl log <name> [-n 20]
wsctl commit <name> -m "message"
wsctl diff <a> <b>
```

### Monitoring
```bash
wsctl list
wsctl status <name>
wsctl dashboard [--refresh 5]
```

### Intelligence
```bash
wsctl ask "coding work" --profile win11 [--no-llm] [--dry-run]
wsctl search "attention mechanism"
wsctl profiles
```

### Interaction
```bash
wsctl attach <name> [--user chxk] [command]
wsctl clip copy --text "shared data"
wsctl clip paste
wsctl clip list
wsctl setup
```

## How it Works

wsctl manages btrfs subvolumes under `/var/lib/workspaces/`. Each thread is a btrfs subvolume created from a NixOS container template. Threads boot as systemd-nspawn containers with:

- Shared `/nix/store` (read-only bind mount — zero duplication)
- Shared `/var/lib/workspaces-shared/` (read-write bind mount — cross-thread files)
- `/run/nexus/` bind mount for Fennix→Nexus communication
- `/fauxnix-core/` bind mount for Fennix + Archivist code access

## Configuration

| Path | Purpose |
|------|---------|
| `/var/lib/workspaces/` | Thread roots (btrfs subvolumes) |
| `/var/lib/workspaces/.template/` | Clean thread template |
| `/var/lib/workspaces/.snapshots/` | Snapshot storage |
| `/var/lib/workspaces-shared/` | Cross-thread shared files |

## Dependencies

- Python 3.10+ (stdlib only — no pip packages)
- btrfs-progs
- systemd-nspawn / machinectl
- sudo
