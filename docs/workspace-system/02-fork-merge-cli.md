# Phase 2: Fork/Merge CLI (`wsctl`)

## Objective

A command-line tool (`wsctl`) that lets the user explicitly fork, merge, snapshot, list, and restore workspaces. All mutating operations snapshot-before-acting.

## Deliverables

- `wsctl` CLI tool (Python, using `click` or `typer`)
- Manifest system for workspace metadata
- Commands: `create`, `fork`, `merge`, `snapshot`, `list`, `restore`, `delete`, `diff`
- Nix package: `packages/wsctl/`

## Package Structure

```
packages/wsctl/
├── pyproject.toml
├── default.nix
└── wsctl/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py            # Click/Typer command definitions
    ├── manifest.py       # Workspace manifest read/write
    ├── operations.py     # Fork, merge, snapshot logic
    ├── btrfs.py          # btrfs subvolume/snapshot wrappers
    └── nspawn.py         # systemd-nspawn container management
```

## Workspace Manifest Schema

Each workspace root (e.g. `/workspaces/ml-paper/`) contains `ws-manifest.toml`:

```toml
[workspace]
name = "ml-paper"
id = "a1b2c3d4e5f6"
created = "2025-07-11T10:00:00Z"

[parent]
workspace_id = "b2c3d4e5f6a1"      # null if top-level
forked_at = "2025-07-11T10:00:00Z"
forked_from_snapshot = "2025-07-11-095500"

[nix]
closure_hash = "sha256:abc123def456..."
flake_ref = "git+file:///workspaces/ml-paper/flake.nix"
profile = "win11"                    # "win11" | "macos" | "headless"

[snapshots]
current = "auto-20250711-140000"
history = [
  "auto-20250711-120000",
  "auto-20250711-100000",
  "pre-fork-20250711-095500",
]

[merged_from]
workspace_ids = []                   # workspaces previously merged into this one

[merged_into]                        # if this workspace was archived by merge
workspace_id = null

[tags]
topics = ["ml", "research", "transformers"]

[activity]
last_active = "2025-07-11T14:30:00Z"
total_session_hours = 12.5
```

## CLI Commands

### `wsctl create <name> [--profile win11|macos|headless] [--template <name>]`

```
Creates btrfs subvolume under /workspaces/<name>
Writes ws-manifest.toml
Optionally copies base config from template directory
If --template: copies /etc/wsctl/templates/<name> as Nix config base
Starts nspawn container (auto-generated container config from profile)
```

### `wsctl fork <source> <target> [--interactive]`

```
1. Snapshot <source> workspace (safety: pre-fork-<timestamp>)
2. Creates btrfs writable snapshot of <source> subvolume as <target>
3. Writes new manifest with parent = source.id
4. If --interactive: opens file picker (fzf) showing changed/new files
   - Left pane: files in source but not in target template
   - Right pane: preview of file content
   - User selects what to carry over (space to select, enter to confirm)
   - Removes unchecked files from new workspace
5. Starts the new workspace
```

### `wsctl merge <source> <target>`

```
1. Snapshots BOTH workspaces first (pre-merge-<timestamp>)
2. Closures:
   - Extracts package list from both manifests
   - Unions them (deduplicate)
   - Generates new Nix config with combined packages
3. Files:
   - Compares /shared contributions from both workspaces
   - Copies unique/new files from source → target shared dir
   - If conflict: renames source file as <name>.from-<ws-name>
4. Writes merge record in target manifest (merged_from)
5. Writes merged_into in source manifest
6. Stops source container
7. Prints merge summary (packages added, files copied, conflicts)
8. Optional: auto-deletes source workspace (user flag --prune)
```

### `wsctl snapshot <name> [--label <label>]`

```
Creates btrfs snapshot:
  /snapshots/<name>/<label>-<timestamp>
Records snapshot in manifest.snapshots.history
Updates manifest.snapshots.current
```

### `wsctl list [--running] [--all]`

```
Prints table:

NAME         STATUS    PROFILE   TOPICS              LAST ACTIVE     PARENT
ml-paper     running   win11     ml, research        2 min ago       (root)
rust-dev     stopped   headless  coding, rust        3 hours ago     ml-paper
design       running   macos     design, ui          5 min ago       (root)
```

### `wsctl restore <name> <snapshot-label>`

```
1. Stops workspace container
2. Deletes current subvolume
3. Creates writable snapshot from the restore point
4. Starts container
5. Updates manifest.snapshots.current
```

### `wsctl delete <name> [--prune-snapshots]`

```
Soft delete (default):
  1. Stops container
  2. Creates final snapshot (recovery safety)
  3. Removes systemd container unit
  4. Marks manifest as archived

With --prune-snapshots:
  Also deletes btrfs snapshots older than 30 days
```

### `wsctl diff <name1> <name2>`

```
Compares two workspaces and prints:
  - Nix closure diff (packages unique to each)
  - File diff in /shared (files unique to each)
  - Snapshot history divergence (common ancestor)
  - Activity timeline overlap
```

## Integration with Fennix

`wsctl` is called by Fennix (Phase 5) when the assistant recommends an action. The assistant generates a suggestion card that contains the exact `wsctl` command to execute.

```
Suggestion: "Workspaces 'ml-paper' and 'transformers' are 89% similar"
Action: wsctl merge ml-paper transformers --dry-run
Accept: wsctl merge ml-paper transformers
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Consistent with rest of FauxnixOS stack (fauxnix-tools, fennix, membrie) |
| CLI framework | `click` or `typer` | Lightweight, good for agentic iteration |
| Manifest format | TOML | Human-readable, nix-compatible, standard library support |
| Dry-run support | All mutating commands | Safety — user sees what will happen before it happens |
| Soft delete | Default | Can't lose data. Explicit --prune for space reclamation |

## Success Criteria

- [ ] `wsctl create test-ws --profile win11` creates bootable workspace
- [ ] `wsctl fork test-ws test-fork` creates independent copy with parent recorded
- [ ] `wsctl merge test-fork test-ws` unions closures and files without data loss
- [ ] `wsctl snapshot test-ws` creates btrfs snapshot recorded in manifest
- [ ] `wsctl list` shows all workspaces with correct status/profiles/topics
- [ ] `wsctl restore test-ws <snapshot>` reverts workspace to previous state
- [ ] `wsctl delete test-ws` soft-deletes with final snapshot
