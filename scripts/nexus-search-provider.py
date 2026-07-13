#!/usr/bin/env python3
"""Nexus GNOME Search Provider — answers in Activities search bar.

Type in GNOME shell:
  "create ml"     → "Create ml-python thread"
  "status dev"    → "Show status of dev thread"
  "resume writing" → "Resume writing thread"
  "attention"     → "Search all threads for attention"

GNOME Shell discovers this provider via DBus and the
.search-provider.ini file in the search providers directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

try:
    from gi.repository import GLib, Gio
except ImportError:
    print("python3-gobject not installed — search provider unavailable", file=sys.stderr)
    sys.exit(0)

BUS_NAME = "org.fauxnix.NexusSearchProvider"
OBJECT_PATH = "/org/fauxnix/NexusSearchProvider"
SEARCH_IFACE = "org.gnome.Shell.SearchProvider2"

TEMPLATES = [
    ("ml-python", "ML / Data Science", "PyTorch, Jupyter, NumPy"),
    ("coding", "Coding", "Python, Rust, Go, Node.js, git"),
    ("writing", "Writing", "Pandoc, Zathura, LaTeX"),
    ("research", "Research", "Chrome, Obsidian, Zotero"),
    ("documents", "Documents", "LibreOffice, Pandoc, LaTeX"),
    ("audio", "Audio Production", "Ardour, Audacity, LMMS"),
    ("image-video", "Image & Video", "GIMP, Blender, Kdenlive"),
    ("gaming", "Gaming", "Steam, Lutris, GameMode"),
    ("emulation", "Emulation", "RetroArch, Dolphin, PCSX2"),
    ("web-dev", "Web Dev", "Node.js, TypeScript, VS Code"),
    ("rust-dev", "Rust Dev", "cargo, rustc, rust-analyzer"),
    ("dvd-ripping", "DVD Ripping", "Handbrake, MakeMKV, FFmpeg"),
]


def _get_threads() -> list[dict]:
    try:
        result = subprocess.run(
            ["sudo", "machinectl", "list", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        threads = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if parts:
                threads.append({"name": parts[0], "status": "running"})
        return threads
    except Exception:
        return []


def _get_all_threads() -> list[dict]:
    ws_root = Path("/var/lib/workspaces")
    if not ws_root.exists():
        return _get_threads()

    running = {t["name"] for t in _get_threads()}
    threads = []
    for d in ws_root.iterdir():
        if d.name.startswith(".") or not d.is_dir():
            continue
        threads.append({"name": d.name, "status": "running" if d.name in running else "stopped"})
    return threads


def _match(query: str) -> list[dict]:
    results = []
    q = query.lower().strip()

    if not q or q in ("f", "fa", "fau", "faux"):
        results.append({
            "id": "create-thread",
            "name": "Create a new thread...",
            "description": "Pick a template and desktop feel",
            "action": "create-prompt",
        })
        return results

    for tid, name, desc in TEMPLATES:
        if tid in q or any(w in q for w in name.lower().split()):
            results.append({
                "id": f"create-{tid}",
                "name": f"Create {name} thread",
                "description": desc,
                "action": f"create:{tid}",
            })

    for t in _get_all_threads():
        if t["name"] in q or q in t["name"]:
            icon = "●" if t["status"] == "running" else "○"
            results.append({
                "id": f"thread-{t['name']}",
                "name": f"{icon} {t['name']}",
                "description": f"Thread — {t['status']}",
                "action": f"status:{t['name']}",
            })

    if "search" in q or len(results) < 2:
        results.append({
            "id": "search-all",
            "name": f"Search all threads for '{q}'",
            "description": "Cross-thread search across git, events, files",
            "action": f"search:{q}",
        })

    if len(results) < 2:
        results.append({
            "id": "create-ask",
            "name": f"Ask Nexus: '{query[:40]}'",
            "description": "AI-powered thread creation",
            "action": f"ask:{query}",
        })

    return results[:8]


class NexusSearchProvider:
    def __init__(self):
        self._results: dict[str, dict] = {}

    def _run_wsctl(self, args: list[str]) -> None:
        subprocess.Popen(
            ["/home/chxk/.local/bin/wsctl"] + args,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def GetInitialResultSet(self, terms: list[str], invocation=None):
        self._results.clear()
        query = " ".join(terms)
        matched = _match(query)
        ids = []
        for r in matched:
            rid = r["id"]
            self._results[rid] = r
            ids.append(rid)
        return ids

    def GetSubsearchResultSet(self, previous_results: list[str], terms: list[str], invocation=None):
        return self.GetInitialResultSet(terms, invocation)

    def GetResultMetas(self, ids: list[str], invocation=None):
        metas = []
        for rid in ids:
            r = self._results.get(rid, {})
            metas.append({
                "id": rid,
                "name": r.get("name", rid),
                "description": r.get("description", ""),
                "gicon": None,
            })
        return metas

    def ActivateResult(self, result_id: str, terms: list[str], timestamp: int, invocation=None):
        r = self._results.get(result_id, {})
        action = r.get("action", "")

        if action == "create-prompt":
            self._run_wsctl(["ask", "development work", "--profile", "win11"])
        elif action.startswith("create:"):
            template = action.split(":", 1)[1]
            self._run_wsctl(["ask", f"{template} development work", "--profile", "win11"])
        elif action.startswith("status:"):
            name = action.split(":", 1)[1]
            subprocess.Popen(
                ["gnome-terminal", "--", "wsctl", "status", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif action.startswith("search:"):
            query = action.split(":", 1)[1]
            subprocess.Popen(
                ["gnome-terminal", "--", "wsctl", "search", query],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif action.startswith("ask:"):
            query = action.split(":", 1)[1]
            self._run_wsctl(["ask", query, "--profile", "win11"])

    def LaunchSearch(self, terms: list[str], timestamp: int, invocation=None):
        subprocess.Popen(
            ["gnome-terminal", "--", "wsctl", "dashboard"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def main():
    provider = NexusSearchProvider()

    node_info = Gio.DBusNodeInfo.new_for_xml(f"""<?xml version="1.0"?>
<node>
  <interface name="{SEARCH_IFACE}">
    <method name="GetInitialResultSet">
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="previous_results" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="ids" direction="in"/>
      <arg type="aa{sv}" name="metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="id" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>""")

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def handle_method_call(conn, sender, object_path, interface_name, method_name, params, invocation):
        args = params.unpack()
        if method_name == "GetInitialResultSet":
            result = provider.GetInitialResultSet(list(args[0]), invocation)
            invocation.return_value(GLib.Variant("(as)", (result,)))
        elif method_name == "GetSubsearchResultSet":
            result = provider.GetSubsearchResultSet(list(args[0]), list(args[1]), invocation)
            invocation.return_value(GLib.Variant("(as)", (result,)))
        elif method_name == "GetResultMetas":
            result = provider.GetResultMetas(list(args[0]), invocation)
            metas_variant = GLib.Variant("aa{sv}", (result,))
            invocation.return_value(GLib.Variant("(aa{sv})", (result,)))
        elif method_name == "ActivateResult":
            provider.ActivateResult(str(args[0]), list(args[1]), int(args[2]), invocation)
            invocation.return_value(GLib.Variant("()", ()))
        elif method_name == "LaunchSearch":
            provider.LaunchSearch(list(args[0]), int(args[1]), invocation)
            invocation.return_value(GLib.Variant("()", ()))

    for interface in node_info.interfaces:
        connection.register_object(
            OBJECT_PATH,
            interface,
            handle_method_call,
            None,
            None,
        )

    connection.call_sync(
        Gio.DBUS_SESSION_BUS,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (BUS_NAME, Gio.BusNameOwnerFlags.NONE)),
        None,
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )

    print(f"[search-provider] registered on session bus as {BUS_NAME}")
    loop = GLib.MainLoop()
    loop.run()


if __name__ == "__main__":
    main()
