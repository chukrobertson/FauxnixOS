#!/usr/bin/env python3
"""Nexus-side Faux-pass provider v0.

This is intentionally small: it exposes a tailnet HTTP API that can list a
bounded app catalog and launch those apps on the Windows Nexus machine.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


PROVIDER_ID = "nexus"
PROVIDER_NAME = "Nexus Windows Provider"
API_PREFIX = "/faux-pass"


def default_token_file() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        return os.path.join(local_app_data, "Fauxnix", "faux-pass-provider.token")
    return ""


def read_token_file(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip().lstrip("\ufeff")
    except OSError:
        return ""


@dataclass(frozen=True)
class AppSpec:
    id: str
    name: str
    command: tuple[str, ...]
    aliases: tuple[str, ...] = ()


APP_SPECS: tuple[AppSpec, ...] = (
    AppSpec("notepad", "Notepad", ("notepad.exe",)),
    AppSpec("calc", "Calculator", ("calc.exe",), ("calculator",)),
    AppSpec("powershell", "PowerShell", ("powershell.exe", "-NoExit"), ("power shell",)),
    AppSpec("vscode", "VS Code", ("code",), ("vs code", "visual studio code")),
)


def app_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": app.id,
            "name": app.name,
            "remote": True,
            "launchable": command_available(app.command[0]),
            "aliases": list(app.aliases),
        }
        for app in APP_SPECS
    ]


def command_available(command: str) -> bool:
    if shutil.which(command):
        return True
    return command.lower().endswith(".exe") and shutil.which(command) is not None


def find_app(query: str) -> AppSpec | None:
    wanted = query.strip().lower()
    for app in APP_SPECS:
        names = (app.id, app.name.lower(), *app.aliases)
        if wanted in names:
            return app
    for app in APP_SPECS:
        names = (app.id, app.name.lower(), *app.aliases)
        if any(wanted in name for name in names):
            return app
    return None


def launch_app(app: AppSpec) -> dict[str, Any]:
    command = list(app.command)
    executable = shutil.which(command[0]) or command[0]
    if executable.lower().endswith(".cmd"):
        popen_command = ["cmd.exe", "/c", executable, *command[1:]]
    else:
        popen_command = [executable, *command[1:]]

    try:
        proc = subprocess.Popen(
            popen_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        return {"ok": False, "app": app.id, "name": app.name, "error": str(exc)}

    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "app": app.id,
        "name": app.name,
        "pid": proc.pid,
    }


def response_payload(path: str) -> tuple[int, dict[str, Any]]:
    if path in {"/health", f"{API_PREFIX}/health"}:
        return HTTPStatus.OK, {"ok": True}
    if path == f"{API_PREFIX}/status":
        return HTTPStatus.OK, {
            "ok": True,
            "provider": {
                "id": PROVIDER_ID,
                "name": PROVIDER_NAME,
                "type": "windows-provider",
                "status": "available",
                "host": socket.gethostname(),
                "apps": len(APP_SPECS),
            },
        }
    if path == f"{API_PREFIX}/apps":
        return HTTPStatus.OK, {"ok": True, "provider": PROVIDER_ID, "apps": app_rows()}
    return HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"}


class Handler(BaseHTTPRequestHandler):
    server_version = "FauxPassProvider/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        status, payload = response_payload(self.path.split("?", 1)[0])
        self.write_json(status, payload)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path.split("?", 1)[0] != f"{API_PREFIX}/run":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return

        app = find_app(str(body.get("app") or ""))
        if app is None:
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown app"})
            return
        result = launch_app(app)
        self.write_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR, result)

    def authorized(self) -> bool:
        token = getattr(self.server, "token", "")  # type: ignore[attr-defined]
        if not token:
            return True
        return self.headers.get("X-Faux-Pass-Token", "") == token

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Nexus Faux-pass provider")
    parser.add_argument("--host", default=os.environ.get("FAUX_PASS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FAUX_PASS_PORT", "4433")))
    parser.add_argument("--token", default=os.environ.get("FAUX_PASS_TOKEN", ""))
    parser.add_argument("--token-file", default=os.environ.get("FAUX_PASS_TOKEN_FILE", default_token_file()))
    args = parser.parse_args()

    token = args.token or read_token_file(args.token_file)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.token = token  # type: ignore[attr-defined]
    print(f"Faux-pass provider listening on http://{args.host}:{args.port}{API_PREFIX}")
    if token:
        print("Faux-pass provider token auth enabled.")
    else:
        print("Warning: no FAUX_PASS_TOKEN is set; rely on Tailscale/firewall scoping for this v0 provider.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
