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
        manifest = create_workspace(args.name, profile=args.profile, template=args.template)
        print(f"Created thread '{args.name}' (id={manifest['workspace']['id']})")
        print(f"Profile: {args.profile}")
        if args.template:
            print(f"Template: {args.template}")
        print(f"Start with: wsctl start {args.name}")
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_start(args: argparse.Namespace) -> None:
    try:
        start_workspace(args.name)
        print(f"Thread '{args.name}' started")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_stop(args: argparse.Namespace) -> None:
    try:
        stop_workspace(args.name)
        print(f"Thread '{args.name}' stopped")
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


def _cmd_merge(args: argparse.Namespace) -> None:
    from wsctl.operations import merge_workspace
    try:
        summary = merge_workspace(args.source, args.target, prune=args.prune)
        print(f"Merged '{args.source}' → '{args.target}'")
        print(f"  Files copied: {summary['files_copied']}")
        print(f"  Snapshots: {summary['snapshots_created'][0]}")
        print(f"  Snapshots: {summary['snapshots_created'][1]}")
        if args.prune:
            print(f"  Thread '{args.source}' pruned")
        else:
            print(f"  Thread '{args.source}' archived (use --prune to delete)")
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


def _cmd_snapshots_prune(args: argparse.Namespace) -> None:
    import subprocess
    from pathlib import Path
    from wsctl import WSCI_SNAPSHOT_ROOT, WSCI_WORKSPACE_ROOT
    from wsctl.btrfs import list_dir, path_exists

    snap_dir = Path(WSCI_SNAPSHOT_ROOT)
    if not path_exists(snap_dir):
        print("No snapshots found")
        return

    thread = args.thread
    entries = list_dir(snap_dir)

    kept = 0
    deleted = 0
    for entry in entries:
        if thread and not entry.startswith(thread):
            continue
        if args.dry_run:
            print(f"  Would delete: {entry}")
            deleted += 1
        else:
            snap_path = snap_dir / entry
            try:
                subprocess.run(
                    ["sudo", "btrfs", "subvolume", "delete", str(snap_path)],
                    capture_output=True, text=True, timeout=10,
                    check=True,
                )
                print(f"  Deleted: {entry}")
                deleted += 1
            except subprocess.CalledProcessError:
                kept += 1

    if args.dry_run:
        print(f"\nWould delete {deleted} snapshots")
    else:
        print(f"\nDeleted {deleted} snapshots" + (f", {kept} kept" if kept else ""))


def _cmd_restore(args: argparse.Namespace) -> None:
    try:
        restore_workspace(args.name, args.snapshot)
        print(f"Thread '{args.name}' restored from snapshot '{args.snapshot}'")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_delete(args: argparse.Namespace) -> None:
    try:
        delete_workspace(args.name)
        print(f"Thread '{args.name}' deleted")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    workspaces = list_workspaces()
    if not workspaces:
        print("No threads found")
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
    import subprocess
    from wsctl.nspawn import is_running
    if not is_running(args.name):
        print(f"Error: Thread '{args.name}' is not running", file=sys.stderr)
        print(f"  Start it first: wsctl start {args.name}", file=sys.stderr)
        sys.exit(1)
    user = args.user or "chxk"
    cmd = ["sudo", "machinectl", "shell", f"{user}@{args.name}"]
    if args.command:
        cmd.extend(["/bin/sh", "-c", args.command])
    else:
        cmd.append("/bin/bash")
    subprocess.run(cmd)


def _cmd_log(args: argparse.Namespace) -> None:
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.git import log as git_log

    ws_path = Path(WSCI_WORKSPACE_ROOT) / args.name
    if not ws_path.exists():
        print(f"Error: Thread '{args.name}' not found", file=sys.stderr)
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
        print(f"Error: Thread '{args.name}' not found", file=sys.stderr)
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
        print(f"Error: Thread '{args.a}' not found", file=sys.stderr)
        sys.exit(1)
    if not ws_b.exists():
        print(f"Error: Thread '{args.b}' not found", file=sys.stderr)
        sys.exit(1)

    output = git_diff(ws_a, ws_b)
    if output.strip():
        print(output)
    else:
        print("No differences")


def _cmd_ask(args: argparse.Namespace) -> None:
    from wsctl.templates import match_template, template_description
    from wsctl.operations import create_workspace, start_workspace

    query = " ".join(args.query)
    use_llm = not args.no_llm
    template = match_template(query, use_llm=use_llm)
    desc = template_description(template)
    profile = args.profile or "headless"
    thread_name = args.name or template + "-" + _short_id()

    if args.dry_run:
        print(f"Query: {query}")
        print(f"Matched: {template} — {desc}")
        print(f"Profile: {profile}")
        _print_profile_info(profile)
        print(f"Would create: {thread_name}")
        return

    try:
        manifest = create_workspace(thread_name, profile=profile, template=template)
        print(f"Created thread '{thread_name}' (id={manifest['workspace']['id']})")
        print(f"Template: {template} — {desc}")
        print(f"Desktop feel: {profile}")
        _print_profile_info(profile)
        start_workspace(thread_name)
        print(f"Thread started — Fennix and Archivist are initializing...")
    except FileExistsError:
        print(f"Error: Thread '{thread_name}' already exists", file=sys.stderr)
        sys.exit(1)


def _print_profile_info(profile: str) -> None:
    info = {
        "win11": "  Bottom taskbar, centered launcher, acrylic blur, snap layouts",
        "macos": "  Top menu bar, bottom dock, spotlight search, frosted glass",
        "headless": "  SSH access only, no desktop environment",
    }
    print(info.get(profile, ""))


def _short_id() -> str:
    import uuid
    return uuid.uuid4().hex[:6]


def _cmd_profiles(args: argparse.Namespace) -> None:
    print("Desktop Feel Profiles:\n")
    profiles = [
        ("win11", "Windows 11", "Bottom taskbar, centered launcher, acrylic blur, snap layouts"),
        ("macos", "macOS", "Top menu bar, bottom dock, frosted glass, spotlight search"),
        ("headless", "Headless", "SSH access only, no desktop environment"),
    ]
    for pid, name, desc in profiles:
        print(f"  {pid:<10} {name:<12} {desc}")
    print()
    print("Usage:")
    print("  wsctl create <name> --profile win11")
    print("  wsctl ask 'coding work' --profile macos")


def _cmd_dashboard(args: argparse.Namespace) -> None:
    from wsctl.dashboard import run_dashboard
    run_dashboard(refresh=args.refresh)


def _cmd_status(args: argparse.Namespace) -> None:
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.operations import list_workspaces
    from wsctl.manifest import load_manifest
    from wsctl.git import log as git_log
    from wsctl.btrfs import path_exists

    ws_path = Path(WSCI_WORKSPACE_ROOT) / args.name
    if not path_exists(ws_path):
        print(f"Error: Thread '{args.name}' not found", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest(ws_path)
    threads = {t["name"]: t for t in list_workspaces()}
    info = threads.get(args.name, {})
    status = info.get("status", "unknown")
    profile = info.get("profile", "unknown")
    topics = info.get("topics", [])
    parent = info.get("parent")

    status_icon = "\033[1;32m● running\033[0m" if status == "running" else "\033[1;30m○ stopped\033[0m"

    print(f"\033[1;37m{args.name}\033[0m  {status_icon}")
    print(f"  Profile:  {profile}")
    print(f"  Template: {manifest['nix'].get('template', 'none') if manifest else 'none'}")
    print(f"  Topics:   {', '.join(topics) if topics else '-'}")
    print(f"  Parent:   {parent or '(root)'}")
    if manifest:
        print(f"  Created:  {manifest['workspace']['created'][:19]}")
        snapshots = manifest.get("snapshots", {}).get("history", [])
        print(f"  Snapshots: {len(snapshots)} ({', '.join(snapshots[-3:]) if snapshots else 'none'})")

    print()

    try:
        import sys
        sys.path.insert(0, os.path.expanduser(os.getenv("FAUXNIX_ROOT", "~/Projects/fauxnix-core") + "/packages/nexus"))
        from nexus.db import get_health, count_events, recent_events
        health = get_health(args.name)
        events_count = count_events(args.name)
        if health:
            print("\033[1;33m  Health\033[0m")
            print(f"  Events:    {events_count}")
            print(f"  Status:    {health.get('status', 'unknown')}")
            print(f"  Crashes:   {health.get('crash_count', 0)}")
            if health.get("last_cpu"):
                print(f"  CPU:       {health['last_cpu']:.1f}%")
            if health.get("last_mem"):
                print(f"  Memory:    {health['last_mem']:.1f}%")
            if health.get("started_at"):
                print(f"  Started:   {health['started_at'][:19]}")
            if health.get("last_seen"):
                print(f"  Last seen: {health['last_seen'][:19]}")
            print()

        recent = recent_events(args.name, 5)
        if recent:
            print("\033[1;33m  Recent Events\033[0m")
            for e in recent:
                src = e["source"]
                data = e["event_data"][:80]
                print(f"  [{src:10}] {data}")
            print()
    except Exception:
        pass

    commits = git_log(ws_path, n=5)
    if commits:
        print("\033[1;33m  Git History\033[0m")
        for c in commits:
            print(f"  {c['hash']}  {c['date'][:19]}  {c['message'][:60]}")
        print()

    if status == "running":
        print(f"  \033[90mwsctl attach {args.name}  — connect to this thread\033[0m")
    else:
        print(f"  \033[90mwsctl start {args.name}  — boot this thread\033[0m")


def _cmd_search(args: argparse.Namespace) -> None:
    import subprocess
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.btrfs import list_dir, path_exists

    query = " ".join(args.query)
    if not query:
        print("Usage: wsctl search <query>")
        return

    results: list[dict] = []

    _search_git(query, results)
    _search_events(query, results)
    _search_files(query, results)

    if not results:
        print(f"No results for '{query}'")
        return

    results.sort(key=lambda r: r.get("score", 0), reverse=True)

    print(f"\033[1;37mResults for '{query}'\033[0m\n")
    for r in results[:20]:
        source = r["source"]
        icon = {"git": "\033[33m⬡\033[0m", "event": "\033[36m●\033[0m", "file": "\033[32m■\033[0m"}.get(source, " ")
        thread = f"\033[1;37m[{r['thread']}]\033[0m"
        detail = r["detail"][:100]
        print(f"  {icon} {thread} {detail}")


def _search_git(query: str, results: list[dict]) -> None:
    import subprocess
    from pathlib import Path
    from wsctl import WSCI_WORKSPACE_ROOT
    from wsctl.btrfs import list_dir, path_exists

    ws_root = Path(WSCI_WORKSPACE_ROOT)
    if not path_exists(ws_root):
        return

    for name in list_dir(ws_root):
        if name.startswith("."):
            continue
        repo = ws_root / name
        try:
            result = subprocess.run(
                ["sudo", "git", "-C", str(repo), "log", "--all", "--oneline",
                 f"--grep={query}", "-20"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    results.append({
                        "source": "git",
                        "thread": name,
                        "detail": line.strip()[:100],
                        "score": 10,
                    })
        except Exception:
            pass


def _search_events(query: str, results: list[dict]) -> None:
    try:
        import sys
        sys.path.insert(0, os.path.expanduser(os.getenv("FAUXNIX_ROOT", "~/Projects/fauxnix-core") + "/packages/nexus"))
        from nexus.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT thread_name, source, event_data FROM thread_context WHERE event_data LIKE ? LIMIT 20",
            (f"%{query}%",),
        ).fetchall()
        conn.close()
        for r in rows:
            results.append({
                "source": "event",
                "thread": r["thread_name"],
                "detail": f"[{r['source']}] {r['event_data'][:80]}",
                "score": 5,
            })
    except Exception:
        pass


def _search_files(query: str, results: list[dict]) -> None:
    try:
        import sys
        sys.path.insert(0, os.path.expanduser(os.getenv("FAUXNIX_ROOT", "~/Projects/fauxnix-core") + "/packages/fauxnix-tools"))
        from fauxnix_tools.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT path FROM files WHERE path LIKE ? OR title LIKE ? LIMIT 10",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        conn.close()
        for r in rows:
            results.append({
                "source": "file",
                "thread": "shared",
                "detail": f"file: {r['path']}",
                "score": 3,
            })
    except Exception:
        pass


def _cmd_clip_copy(args: argparse.Namespace) -> None:
    import subprocess
    import socket
    from pathlib import Path

    content = args.text or _get_clipboard()
    if not content:
        print("Clipboard is empty — use --text to specify content directly")
        return
    clip_dir = Path("/var/lib/workspaces-shared/.clipboard")
    subprocess.run(["sudo", "mkdir", "-p", str(clip_dir)], check=True)
    hostname = socket.gethostname()
    clip_file = clip_dir / f"{hostname}.txt"
    subprocess.run(["sudo", "tee", str(clip_file)], input=content, text=True, capture_output=True)
    print(f"Copied {len(content)} chars to shared clipboard → {hostname}.txt")


def _cmd_clip_paste(args: argparse.Namespace) -> None:
    import subprocess
    from pathlib import Path
    clip_dir = Path("/var/lib/workspaces-shared/.clipboard")
    if not clip_dir.exists():
        print("No shared clipboard directory")
        return
    result = subprocess.run(["sudo", "find", str(clip_dir), "-name", "*.txt", "-type", "f"],
                            capture_output=True, text=True)
    files = [Path(f) for f in result.stdout.strip().split("\n") if f]
    if not files:
        print("No clips found")
        return
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    latest = files[0]
    result = subprocess.run(["sudo", "cat", str(latest)], capture_output=True, text=True)
    content = result.stdout
    _set_clipboard(content)
    print(f"Pasted {len(content)} chars from {latest.name} into clipboard")


def _cmd_clip_list(args: argparse.Namespace) -> None:
    import subprocess
    from pathlib import Path
    from datetime import datetime
    clip_dir = Path("/var/lib/workspaces-shared/.clipboard")
    if not clip_dir.exists():
        print("No shared clipboard directory")
        return
    result = subprocess.run(["sudo", "find", str(clip_dir), "-name", "*.txt", "-type", "f"],
                            capture_output=True, text=True)
    files = [Path(f) for f in result.stdout.strip().split("\n") if f]
    if not files:
        print("No clips found")
        return
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        size = f.stat().st_size
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            print(f"  {f.stem:<20} {size:>6}B  {mtime.strftime('%H:%M:%S')}")
        except Exception:
            print(f"  {f.stem:<20} {size:>6}B")


def _get_clipboard() -> str:
    import subprocess
    try:
        result = subprocess.run(["wl-paste"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    try:
        result = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def _set_clipboard(content: str) -> None:
    import subprocess
    try:
        subprocess.run(["wl-copy"], input=content, text=True, timeout=2)
    except Exception:
        pass
    try:
        subprocess.run(["xclip", "-selection", "clipboard"], input=content, text=True, timeout=2)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wsctl",
        description=f"FauxnixOS Workspace Controller v{WSCI_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new thread")
    p_create.add_argument("name", help="Workspace name")
    p_create.add_argument("--profile", choices=["win11", "macos", "headless"], default="headless")
    p_create.add_argument("--template", "-t", help="Template name (coding, research, ml-python, audio, gaming, etc.)")
    p_create.set_defaults(func=_cmd_create)

    p_start = sub.add_parser("start", help="Start a thread")
    p_start.add_argument("name", help="Workspace name")
    p_start.set_defaults(func=_cmd_start)

    p_stop = sub.add_parser("stop", help="Stop a thread")
    p_stop.add_argument("name", help="Workspace name")
    p_stop.set_defaults(func=_cmd_stop)

    p_fork = sub.add_parser("fork", help="Fork a new thread from an existing one")
    p_fork.add_argument("source", help="Source workspace name")
    p_fork.add_argument("target", help="Target workspace name")
    p_fork.set_defaults(func=_cmd_fork)

    p_merge = sub.add_parser("merge", help="Merge a thread into another")
    p_merge.add_argument("source", help="Source workspace to merge from")
    p_merge.add_argument("target", help="Target workspace to merge into")
    p_merge.add_argument("--prune", action="store_true", help="Delete source after merge")
    p_merge.set_defaults(func=_cmd_merge)

    p_snap = sub.add_parser("snapshot", help="Snapshot a thread")
    p_snap.add_argument("name", help="Workspace name")
    p_snap.add_argument("--label", "-l", help="Snapshot label")
    p_snap.set_defaults(func=_cmd_snapshot)

    p_snaps = sub.add_parser("snapshots", help="Manage snapshots")
    snaps_sub = p_snaps.add_subparsers(dest="snaps_command")

    snaps_prune = snaps_sub.add_parser("prune", help="Delete old snapshots")
    snaps_prune.add_argument("--thread", "-t", help="Only prune snapshots for this thread")
    snaps_prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    snaps_prune.set_defaults(func=_cmd_snapshots_prune)

    p_restore = sub.add_parser("restore", help="Restore a thread from a snapshot")
    p_restore.add_argument("name", help="Workspace name")
    p_restore.add_argument("snapshot", help="Snapshot name")
    p_restore.set_defaults(func=_cmd_restore)

    p_delete = sub.add_parser("delete", help="Delete a thread")
    p_delete.add_argument("name", help="Workspace name")
    p_delete.set_defaults(func=_cmd_delete)

    p_list = sub.add_parser("list", help="List all threads")
    p_list.set_defaults(func=_cmd_list)

    p_setup = sub.add_parser("setup", help="First-run setup wizard")
    p_setup.add_argument("--profile", choices=["win11", "macos", "headless"], default="headless")
    p_setup.set_defaults(func=_cmd_setup)

    p_attach = sub.add_parser("attach", help="Attach to a running workspace")
    p_attach.add_argument("name", help="Workspace name")
    p_attach.add_argument("--user", "-u", help="User to connect as (default: chxk)")
    p_attach.add_argument("command", nargs="?", help="Command to run (default: shell)")
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

    p_ask = sub.add_parser("ask", help="Create a thread from a natural language description")
    p_ask.add_argument("query", nargs="+", help="What kind of thread do you need?")
    p_ask.add_argument("--name", "-n", help="Thread name (auto-generated if not set)")
    p_ask.add_argument("--profile", "-p", choices=["win11", "macos", "headless"], default="headless",
                       help="Desktop feel (win11, macos, or headless)")
    p_ask.add_argument("--dry-run", action="store_true", help="Show what would be created")
    p_ask.add_argument("--no-llm", action="store_true", help="Skip LLM matching, use keywords only")
    p_ask.set_defaults(func=_cmd_ask)

    p_profiles = sub.add_parser("profiles", help="List available desktop feel profiles")
    p_profiles.set_defaults(func=_cmd_profiles)

    p_dash = sub.add_parser("dashboard", help="Live TUI dashboard for thread management")
    p_dash.add_argument("--refresh", "-r", type=int, default=5, help="Refresh interval in seconds")
    p_dash.set_defaults(func=_cmd_dashboard)

    p_status = sub.add_parser("status", help="Show detailed status for a thread")
    p_status.add_argument("name", help="Thread name")
    p_status.set_defaults(func=_cmd_status)

    p_search = sub.add_parser("search", help="Search across all threads")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.set_defaults(func=_cmd_search)

    p_clip = sub.add_parser("clip", help="Shared clipboard between threads")
    clip_sub = p_clip.add_subparsers(dest="clip_command")

    clip_copy = clip_sub.add_parser("copy", help="Copy clipboard to shared pool")
    clip_copy.add_argument("--text", "-t", help="Text to copy (reads system clipboard if not set)")
    clip_copy.set_defaults(func=_cmd_clip_copy)

    clip_paste = clip_sub.add_parser("paste", help="Paste latest shared clip into clipboard")
    clip_paste.set_defaults(func=_cmd_clip_paste)

    clip_list = clip_sub.add_parser("list", help="List all shared clips")
    clip_list.set_defaults(func=_cmd_clip_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
