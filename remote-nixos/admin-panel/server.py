#!/usr/bin/env python3
"""Small Fauxnix web desktop served on the local network."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STARTED_AT = time.time()
PORT = int(os.environ.get("FAUXNIX_NODE_DESKTOP_PORT", "8765"))
HOST = os.environ.get("FAUXNIX_NODE_DESKTOP_HOST", "0.0.0.0")
ARCHIVIST_PORT = int(os.environ.get("FAUXNIX_ARCHIVIST_WEB_PORT", "8776"))
INBOX_DIR = Path(os.environ.get("FAUXNIX_INBOX", os.path.expanduser("~/Archive/INBOX"))).expanduser()
SYS_BLOCK = Path("/sys/block")
DRIVE_IMPORT_STATE = Path(tempfile.gettempdir()) / "fauxnix-drive-import.json"

LOCAL_ACTIONS = {
    "archivist": ["chromium", "--new-window", f"http://127.0.0.1:{ARCHIVIST_PORT}/"],
    "terminal": ["alacritty"],
    "workspace": ["fauxnix-workspace"],
    "fennix": ["fennix-gui"],
}

LAUNCHER_PATHS = (
    "/run/current-system/sw/bin",
    "/run/wrappers/bin",
)


def _archivist_loopback_url() -> str:
    return f"http://127.0.0.1:{ARCHIVIST_PORT}/"


def _run(args: list[str], timeout: float = 2.0) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def _readlink(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return ""


def _systemctl_active(service: str) -> str:
    if not shutil.which("systemctl"):
        return "unknown"
    value = _run(["systemctl", "is-active", service])
    return value or "unknown"


def _pgrep(pattern: str) -> list[str]:
    output = _run(["pgrep", "-af", pattern])
    return [line for line in output.splitlines() if line]


def _addresses(port: int) -> list[str]:
    output = _run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    urls = []
    for line in output.splitlines():
        fields = line.split()
        if "inet" not in fields:
            continue
        address = fields[fields.index("inet") + 1].split("/", 1)[0]
        urls.append(f"http://{address}:{port}")
    return urls


def _wayland_display(runtime_dir: Path) -> str:
    existing = os.environ.get("WAYLAND_DISPLAY")
    if existing:
        return existing
    for candidate in sorted(runtime_dir.glob("wayland-*")):
        if candidate.is_socket():
            return candidate.name
    return "wayland-1"


def _x_display() -> str:
    existing = os.environ.get("DISPLAY")
    if existing:
        return existing
    x11_dir = Path("/tmp/.X11-unix")
    if x11_dir.exists():
        for candidate in sorted(x11_dir.glob("X*")):
            suffix = candidate.name.removeprefix("X")
            if suffix.isdigit():
                return f":{suffix}"
    return ":1"


def _launcher_path(existing: str) -> str:
    parts = [path for path in existing.split(":") if path]
    for path in reversed(LAUNCHER_PATHS):
        if path not in parts:
            parts.insert(0, path)
    return ":".join(parts)


def _resolve_command(command: list[str], env: dict[str, str]) -> list[str] | None:
    if not command:
        return None
    program = command[0]
    if Path(program).is_absolute():
        return command
    resolved = shutil.which(program, path=env.get("PATH", ""))
    if resolved is None:
        return None
    return [resolved, *command[1:]]


def _launch_local(action_id: str) -> dict:
    command = LOCAL_ACTIONS.get(action_id)
    if command is None:
        return {"ok": False, "error": f"unknown action: {action_id}"}

    runtime_dir = Path(f"/run/user/{os.getuid()}")
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
    env.setdefault("WAYLAND_DISPLAY", _wayland_display(runtime_dir))
    env.setdefault("DISPLAY", _x_display())
    env.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    env.setdefault("GDK_BACKEND", "wayland,x11")
    env.setdefault("NIXOS_OZONE_WL", "1")
    env["PATH"] = _launcher_path(env.get("PATH", ""))

    resolved_command = _resolve_command(command, env)
    if resolved_command is None:
        return {"ok": False, "error": f"launcher command not found: {command[0]}"}

    try:
        subprocess.Popen(
            resolved_command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    payload = {"ok": True, "action": action_id}
    if action_id == "archivist":
        payload["url"] = _archivist_loopback_url()
    return payload


def _status(port: int) -> dict:
    usage = shutil.disk_usage("/")
    return {
        "hostname": socket.gethostname(),
        "serverUptimeSeconds": int(time.time() - STARTED_AT),
        "systemUptime": _run(["uptime", "-p"]),
        "currentSystem": _readlink("/run/current-system"),
        "lanUrls": _addresses(port),
        "loopbackUrl": f"http://127.0.0.1:{port}",
        "archivist": {
            "loopbackUrl": _archivist_loopback_url(),
            "lanUrls": _addresses(ARCHIVIST_PORT),
        },
        "disk": {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round((usage.used / usage.total) * 100, 1),
        },
        "services": {
            "display-manager": _systemctl_active("display-manager.service"),
            "fauxnix-admin-panel": _systemctl_active("fauxnix-admin-panel.service"),
            "fauxnix-archivist-web": _systemctl_active("fauxnix-archivist-web.service"),
            "ollama": _systemctl_active("ollama.service"),
            "tailscaled": _systemctl_active("tailscaled.service"),
        },
        "processes": {
            "wayfire": _pgrep("wayfire"),
            "kiosk": _pgrep("chromium.*127.0.0.1:8765"),
            "fauxd": _pgrep("fauxd.py"),
            "workspace": _pgrep("fauxnix-workspace"),
            "archivist": _pgrep("uvicorn app.main:app"),
        },
        "actions": [
            {"id": "terminal", "label": "Terminal", "localOnly": True},
            {"id": "workspace", "label": "Workspace", "localOnly": True},
            {"id": "fennix", "label": "Fennix", "localOnly": True},
        ],
    }


# ── Drive Inbox ──────────────────────────────────────────────────────


def _list_block_devices() -> list[dict]:
    if not SYS_BLOCK.is_dir():
        return []
    devices = []
    for entry in sorted(SYS_BLOCK.iterdir()):
        if not entry.is_dir():
            continue
        device = entry.name
        if device.startswith("loop") or device.startswith("ram"):
            continue
        removable = (entry / "removable").read_text().strip() == "1" if (entry / "removable").is_file() else False
        size_bytes = int((entry / "size").read_text().strip()) * 512 if (entry / "size").is_file() else 0
        model = ""
        vendor = ""
        for sub in ("device",):
            model_file = entry / sub / "model"
            vendor_file = entry / sub / "vendor"
            if model_file.is_file():
                model = model_file.read_text().strip()
            if vendor_file.is_file():
                vendor = vendor_file.read_text().strip()
        info: dict = {
            "device": f"/dev/{device}",
            "model": model or "",
            "vendor": vendor or "",
            "size": size_bytes,
            "sizeHuman": _human_size(size_bytes),
            "removable": removable,
            "partitions": [],
        }
        for part_entry in sorted(entry.iterdir()):
            pname = part_entry.name
            if pname.startswith(device):
                psize = int((part_entry / "size").read_text().strip()) * 512 if (part_entry / "size").is_file() else 0
                info["partitions"].append({"device": f"/dev/{pname}", "size": psize, "sizeHuman": _human_size(psize)})
        devices.append(info)
    return devices


def _human_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _get_mounts() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        content = Path("/proc/mounts").read_text()
        for line in content.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                result[parts[0]] = parts[1]
    except Exception:
        pass
    return result


def _mount_device(dev: str) -> dict:
    try:
        Path(INBOX_DIR).mkdir(parents=True, exist_ok=True)
        mounts = _get_mounts()
        if dev in mounts:
            return {"ok": True, "mountPoint": mounts[dev], "already": True}
        result = subprocess.run(
            ["sudo", "mount", dev, str(INBOX_DIR)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "mount failed"}
        return {"ok": True, "mountPoint": str(INBOX_DIR)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _unmount_device(dev: str) -> dict:
    try:
        result = subprocess.run(
            ["sudo", "umount", dev],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "umount failed"}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _browse_directory(path: str) -> dict:
    try:
        p = Path(path).resolve()
        if not p.is_dir():
            return {"ok": False, "error": f"not a directory: {path}"}
        entries = []
        for entry in sorted(p.iterdir()):
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "isDir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
                "sizeHuman": _human_size(entry.stat().st_size) if entry.is_file() else "",
            })
        return {"ok": True, "entries": entries, "currentPath": str(p)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _import_file(src: str) -> dict:
    try:
        src_path = Path(src).resolve()
        if not src_path.is_file():
            return {"ok": False, "error": f"not a file: {src}"}
        Path(INBOX_DIR).mkdir(parents=True, exist_ok=True)
        dest = INBOX_DIR / src_path.name
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = INBOX_DIR / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.copy2(src_path, dest)
        return {"ok": True, "dest": str(dest)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _import_files(paths: list[str]) -> dict:
    results = []
    for path in paths:
        r = _import_file(path)
        results.append(r)
    return {"ok": True, "results": results}


def _load_import_state() -> list[dict]:
    try:
        if DRIVE_IMPORT_STATE.exists():
            return json.loads(DRIVE_IMPORT_STATE.read_text())
    except Exception:
        pass
    return []


def _save_import_state(entries: list[dict]) -> None:
    DRIVE_IMPORT_STATE.write_text(json.dumps(entries, indent=2, default=str))


# ── Handler ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "FauxnixAdminPanel/0.1"

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/status":
            self._json(_status(self.server.server_port))
            return
        if path == "/api/health":
            self._json({"ok": True})
            return
        if path == "/api/drives":
            self._json({"ok": True, "devices": _list_block_devices(), "mounts": _get_mounts()})
            return
        if path == "/api/drives/imports":
            self._json({"ok": True, "imports": _load_import_state()})
            return
        if path == "/api/drives/browse":
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(pair.split("=", 1) for pair in qs.split("&") if "=" in pair)
            dir_path = unquote(params.get("path", str(INBOX_DIR)))
            self._json(_browse_directory(dir_path))
            return
        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

        # Drive endpoints — allowed from LAN
        if path == "/api/drives/mount":
            dev = body.get("device", "")
            self._json(_mount_device(dev))
            return
        if path == "/api/drives/unmount":
            dev = body.get("device", "")
            self._json(_unmount_device(dev))
            return
        if path == "/api/drives/browse":
            dir_path = body.get("path", str(INBOX_DIR))
            self._json(_browse_directory(dir_path))
            return
        if path == "/api/drives/import":
            file_path = body.get("path", "")
            result = _import_file(file_path)
            state = _load_import_state()
            if result.get("ok"):
                state.append({"src": file_path, "dest": result["dest"], "ts": time.time()})
                _save_import_state(state)
            self._json(result)
            return
        if path == "/api/drives/import-multi":
            paths = body.get("paths", [])
            result = _import_files(paths)
            state = _load_import_state()
            for r in result.get("results", []):
                if r.get("ok"):
                    state.append({"src": r.get("src", "?"), "dest": r["dest"], "ts": time.time()})
            _save_import_state(state)
            self._json(result)
            return

        # Legacy local-kiosk-only actions
        prefix = "/api/actions/"
        if not path.startswith(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            self._json({"ok": False, "error": "actions are local-kiosk only"}, HTTPStatus.FORBIDDEN)
            return
        action_id = path[len(prefix) :].strip("/")
        self._json(_launch_local(action_id))

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, request_path: str) -> None:
        rel = request_path.lstrip("/")
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fauxnix node desktop serving on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
