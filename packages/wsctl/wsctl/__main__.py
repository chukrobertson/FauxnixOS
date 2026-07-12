from __future__ import annotations

import argparse
import sys

from wsctl import WSCI_VERSION
from wsctl.operations import (
    create_workspace,
    start_workspace,
    stop_workspace,
    fork_workspace,
    snapshot_workspace,
    restore_workspace,
    delete_workspace,
    list_workspaces,
)


def _cmd_create(args: argparse.Namespace) -> None:
    try:
        manifest = create_workspace(args.name, profile=args.profile)
        print(f"Created workspace '{args.name}' (id={manifest['workspace']['id']})")
        print(f"Profile: {args.profile}")
        print(f"Start with: wsctl start {args.name}")
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_start(args: argparse.Namespace) -> None:
    try:
        start_workspace(args.name)
        print(f"Workspace '{args.name}' started")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_stop(args: argparse.Namespace) -> None:
    try:
        stop_workspace(args.name)
        print(f"Workspace '{args.name}' stopped")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_fork(args: argparse.Namespace) -> None:
    try:
        manifest = fork_workspace(args.source, args.target)
        print(f"Forked '{args.source}' → '{args.target}' (id={manifest['workspace']['id']})")
    except (FileNotFoundError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_snapshot(args: argparse.Namespace) -> None:
    try:
        snap_name = snapshot_workspace(args.name, label=args.label)
        print(f"Snapshot created: {snap_name}")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_restore(args: argparse.Namespace) -> None:
    try:
        restore_workspace(args.name, args.snapshot)
        print(f"Workspace '{args.name}' restored from snapshot '{args.snapshot}'")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_delete(args: argparse.Namespace) -> None:
    try:
        delete_workspace(args.name)
        print(f"Workspace '{args.name}' deleted")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    workspaces = list_workspaces()
    if not workspaces:
        print("No workspaces found")
        return

    header = f"{'NAME':<20} {'STATUS':<10} {'PROFILE':<10} {'TOPICS':<20} {'PARENT':<12}"
    print(header)
    print("-" * len(header))

    for ws in workspaces:
        topics = ",".join(ws["topics"][:3]) if ws["topics"] else "-"
        parent = ws["parent"] or "(root)"
        print(
            f"{ws['name']:<20} "
            f"{ws['status']:<10} "
            f"{ws['profile']:<10} "
            f"{topics:<20} "
            f"{parent:<12}"
        )


def _cmd_setup(args: argparse.Namespace) -> None:
    import subprocess
    from pathlib import Path

    profile = args.profile
    print(f"Creating default workspace 'main' with {profile} profile...")

    try:
        manifest = create_workspace("main", profile=profile)
        print(f"Created workspace 'main' (id={manifest['workspace']['id']})")
        print()
        print("Connect to your workspace:")
        print("  ssh main.local          (from base system)")
        print("  wsctl attach main        (from base system)")
    except FileExistsError:
        print("Default workspace 'main' already exists.")


def _cmd_attach(args: argparse.Namespace) -> None:
    print(f"Attaching to workspace '{args.name}'...")
    print("(not yet implemented — use machinectl shell or nsenter)")
    import subprocess
    subprocess.run(
        ["sudo", "machinectl", "shell", f"chxk@{args.name}", "/bin/bash"],
    )


def _cmd_log(args: argparse.Namespace) -> None:
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.git import log as git_log

    ws_path = Path(WSCI_WORKSPACE_ROOT) / args.name
    if not ws_path.exists():
        print(f"Error: Workspace '{args.name}' not found", file=sys.stderr)
        sys.exit(1)

    entries = git_log(ws_path, n=args.n)
    if not entries:
        print("No commits")
        return

    for e in entries:
        print(f"{e['hash']}  {e['date'][:19]}  {e['message']}")


def _cmd_commit(args: argparse.Namespace) -> None:
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.git import commit as git_commit, status as git_status
    from wsctl.manifest import load_manifest, save_manifest

    ws_path = Path(WSCI_WORKSPACE_ROOT) / args.name
    if not ws_path.exists():
        print(f"Error: Workspace '{args.name}' not found", file=sys.stderr)
        sys.exit(1)

    st = git_status(ws_path)
    if not st and not args.allow_empty:
        print("Nothing to commit (use --allow-empty to force)")
        return

    print(f"Changes:\n{st}" if st else "(empty commit)")
    commit_hash = git_commit(ws_path, args.message)
    print(f"Committed: {commit_hash}")

    manifest = load_manifest(ws_path)
    if manifest and "git" in manifest:
        manifest["git"]["last_commit"] = commit_hash
        save_manifest(ws_path, manifest)


def _cmd_diff(args: argparse.Namespace) -> None:
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.git import diff as git_diff

    ws_a = Path(WSCI_WORKSPACE_ROOT) / args.a
    ws_b = Path(WSCI_WORKSPACE_ROOT) / args.b
    if not ws_a.exists():
        print(f"Error: Workspace '{args.a}' not found", file=sys.stderr)
        sys.exit(1)
    if not ws_b.exists():
        print(f"Error: Workspace '{args.b}' not found", file=sys.stderr)
        sys.exit(1)

    output = git_diff(ws_a, ws_b)
    if output.strip():
        print(output)
    else:
        print("No differences")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wsctl",
        description=f"FauxnixOS Workspace Controller v{WSCI_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new workspace")
    p_create.add_argument("name", help="Workspace name")
    p_create.add_argument("--profile", choices=["win11", "macos", "headless"], default="headless")
    p_create.set_defaults(func=_cmd_create)

    p_start = sub.add_parser("start", help="Start a workspace")
    p_start.add_argument("name", help="Workspace name")
    p_start.set_defaults(func=_cmd_start)

    p_stop = sub.add_parser("stop", help="Stop a workspace")
    p_stop.add_argument("name", help="Workspace name")
    p_stop.set_defaults(func=_cmd_stop)

    p_fork = sub.add_parser("fork", help="Fork a new workspace from an existing one")
    p_fork.add_argument("source", help="Source workspace name")
    p_fork.add_argument("target", help="Target workspace name")
    p_fork.set_defaults(func=_cmd_fork)

    p_snap = sub.add_parser("snapshot", help="Snapshot a workspace")
    p_snap.add_argument("name", help="Workspace name")
    p_snap.add_argument("--label", "-l", help="Snapshot label")
    p_snap.set_defaults(func=_cmd_snapshot)

    p_restore = sub.add_parser("restore", help="Restore a workspace from a snapshot")
    p_restore.add_argument("name", help="Workspace name")
    p_restore.add_argument("snapshot", help="Snapshot name")
    p_restore.set_defaults(func=_cmd_restore)

    p_delete = sub.add_parser("delete", help="Delete a workspace")
    p_delete.add_argument("name", help="Workspace name")
    p_delete.set_defaults(func=_cmd_delete)

    p_list = sub.add_parser("list", help="List all workspaces")
    p_list.set_defaults(func=_cmd_list)

    p_setup = sub.add_parser("setup", help="First-run setup wizard")
    p_setup.add_argument("--profile", choices=["win11", "macos", "headless"], default="headless")
    p_setup.set_defaults(func=_cmd_setup)

    p_attach = sub.add_parser("attach", help="Attach to a running workspace")
    p_attach.add_argument("name", help="Workspace name")
    p_attach.set_defaults(func=_cmd_attach)

    p_log = sub.add_parser("log", help="Show git log for a workspace")
    p_log.add_argument("name", help="Workspace name")
    p_log.add_argument("-n", type=int, default=20, help="Number of commits")
    p_log.set_defaults(func=_cmd_log)

    p_commit = sub.add_parser("commit", help="Commit workspace changes to git")
    p_commit.add_argument("name", help="Workspace name")
    p_commit.add_argument("-m", "--message", required=True, help="Commit message")
    p_commit.add_argument("--allow-empty", action="store_true", help="Allow empty commits")
    p_commit.set_defaults(func=_cmd_commit)

    p_diff = sub.add_parser("diff", help="Diff two workspace git repos")
    p_diff.add_argument("a", help="First workspace")
    p_diff.add_argument("b", help="Second workspace")
    p_diff.set_defaults(func=_cmd_diff)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
