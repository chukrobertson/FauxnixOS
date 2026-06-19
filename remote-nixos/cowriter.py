#!/usr/bin/env python3
"""Cowriter workspace helper for Fennix.

This is intentionally file-first: Markdown is the source of truth, and the CLI
only helps create, inspect, and search the workspace.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WORKSPACE = Path("/home/chvk/Fauxnix/Cowriter")
KINDS = {
    "draft": "drafts",
    "note": "notes",
    "session": "sessions",
    "outline": "outlines",
    "inbox": "inbox",
}


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def readme(self) -> Path:
        return self.root / "README.md"

    def kind_dir(self, kind: str) -> Path:
        return self.root / KINDS[kind]


def workspace_from_env() -> Workspace:
    raw = os.environ.get("FAUXNIX_COWRITER_WORKSPACE")
    return Workspace(Path(raw).expanduser() if raw else DEFAULT_WORKSPACE)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:64] or "untitled"


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def init_workspace(ws: Workspace) -> None:
    ws.root.mkdir(parents=True, exist_ok=True)
    for directory in KINDS.values():
        (ws.root / directory).mkdir(parents=True, exist_ok=True)

    if not ws.readme.exists():
        ws.readme.write_text(
            """# Cowriter Workspace

This workspace is shared by Fennix and the Fauxnix project.

## Folders

- `drafts/` prose, responses, articles, letters, plans
- `notes/` durable observations and research notes
- `sessions/` working logs from conversations
- `outlines/` structured plans before drafting
- `inbox/` unsorted fragments to process later

Use `cowriter new`, `cowriter capture`, `cowriter list`, `cowriter read`, and
`cowriter search` to work here from the terminal.
""",
            encoding="utf-8",
        )


def front_matter(kind: str, title: str) -> str:
    created = time.strftime("%Y-%m-%d %H:%M:%S %z")
    return (
        "---\n"
        f"title: {title}\n"
        f"kind: {kind}\n"
        f"created: {created}\n"
        "status: active\n"
        "tags: []\n"
        "---\n\n"
    )


def create_document(ws: Workspace, kind: str, title: str, body: str = "") -> Path:
    init_workspace(ws)
    name = f"{timestamp()}-{slugify(title)}.md"
    path = ws.kind_dir(kind) / name
    content = front_matter(kind, title)
    content += f"# {title}\n\n"
    if body.strip():
        content += body.strip() + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def iter_markdown(ws: Workspace, kind: str | None = None) -> list[Path]:
    init_workspace(ws)
    roots = [ws.kind_dir(kind)] if kind else [ws.root / directory for directory in KINDS.values()]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(root.glob("*.md"))
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def print_relative(ws: Workspace, path: Path) -> None:
    print(path.relative_to(ws.root))


def resolve_doc(ws: Workspace, selector: str) -> Path:
    candidate = (ws.root / selector).resolve()
    try:
        candidate.relative_to(ws.root.resolve())
    except ValueError as exc:
        raise SystemExit("path escapes cowriter workspace") from exc
    if candidate.exists():
        return candidate

    matches = [
        path for path in iter_markdown(ws)
        if selector.lower() in str(path.relative_to(ws.root)).lower()
    ]
    if not matches:
        raise SystemExit(f"no document matched: {selector}")
    if len(matches) > 1:
        print("multiple matches:", file=sys.stderr)
        for path in matches[:20]:
            print(path.relative_to(ws.root), file=sys.stderr)
        raise SystemExit(2)
    return matches[0]


def cmd_init(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    init_workspace(ws)
    print(ws.root)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    init_workspace(ws)
    print(f"workspace: {ws.root}")
    for kind, directory in KINDS.items():
        count = len(list((ws.root / directory).glob("*.md")))
        print(f"{kind}: {count}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    path = create_document(ws, args.kind, args.title, args.body or "")
    print_relative(ws, path)
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    body = sys.stdin.read()
    if not body.strip():
        raise SystemExit("capture needs content on stdin")
    path = create_document(ws, args.kind, args.title, body)
    print_relative(ws, path)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    for path in iter_markdown(ws, args.kind):
        print_relative(ws, path)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    path = resolve_doc(ws, args.selector)
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    ws = Workspace(args.workspace)
    init_workspace(ws)
    needle = args.query.lower()
    for path in iter_markdown(ws, args.kind):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        matches = [
            (index, line.strip())
            for index, line in enumerate(text.splitlines(), start=1)
            if needle in line.lower()
        ]
        for index, line in matches[: args.per_file]:
            print(f"{path.relative_to(ws.root)}:{index}: {line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Fennix Cowriter workspace")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=workspace_from_env().root,
        help="Cowriter workspace path",
    )
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init", help="create the workspace folders")
    init.set_defaults(func=cmd_init)

    status = sub.add_parser("status", help="show workspace counts")
    status.set_defaults(func=cmd_status)

    new = sub.add_parser("new", help="create an empty document")
    new.add_argument("kind", choices=sorted(KINDS))
    new.add_argument("title")
    new.add_argument("--body", default="")
    new.set_defaults(func=cmd_new)

    capture = sub.add_parser("capture", help="create a document from stdin")
    capture.add_argument("kind", choices=sorted(KINDS))
    capture.add_argument("title")
    capture.set_defaults(func=cmd_capture)

    listing = sub.add_parser("list", help="list documents")
    listing.add_argument("kind", choices=sorted(KINDS), nargs="?")
    listing.set_defaults(func=cmd_list)

    read = sub.add_parser("read", help="read a document by relative path or substring")
    read.add_argument("selector")
    read.set_defaults(func=cmd_read)

    search = sub.add_parser("search", help="search documents")
    search.add_argument("query")
    search.add_argument("--kind", choices=sorted(KINDS))
    search.add_argument("--per-file", type=int, default=5)
    search.set_defaults(func=cmd_search)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
