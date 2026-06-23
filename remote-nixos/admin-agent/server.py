#!/usr/bin/env python3
"""Fauxnix Admin Agent HTTP service — chat with the system manager."""

from __future__ import annotations

import json
import os
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

# Ensure package directory is on sys.path for imports
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from kb import MODULE_KB_MAP, init_default_kbs, list_kbs  # noqa: E402
from llm import config_from_env, list_ollama_models  # noqa: E402
from manager import (  # noqa: E402
    apply_change,
    chat,
    get_kb,
    rebuild_and_switch,
    test_config,
    update_kb,
)

ROOT = Path(__file__).resolve().parent
STARTED_AT = time.time()
PORT = int(os.environ.get("FAUXNIX_ADMIN_AGENT_PORT", "8757"))
HOST = os.environ.get("FAUXNIX_ADMIN_AGENT_HOST", "127.0.0.1")

init_default_kbs()


class Handler(BaseHTTPRequestHandler):
    server_version = "FauxnixAdminAgent/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def do_OPTIONS(self) -> None:
        self._cors_headers()
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/status":
            self._json({
                "ok": True,
                "uptime": int(time.time() - STARTED_AT),
                "models": list_ollama_models(),
                "kb_count": len(list_kbs()),
            })
            return
        if path == "/api/kb":
            self._json(get_kb(None))
            return
        if path == "/api/models":
            self._json({"ok": True, "models": list_ollama_models()})
            return
        if path == "/api/config":
            cfg = config_from_env()
            self._json({
                "ok": True,
                "backend": cfg.backend,
                "model": cfg.model,
                "ollama_url": cfg.ollama_url,
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
            })
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

        if path == "/api/chat":
            self._json(self._handle_chat(body))
            return
        if path == "/api/apply":
            self._json(self._handle_apply(body))
            return
        if path == "/api/test":
            self._json(test_config())
            return
        if path == "/api/rebuild":
            self._json(rebuild_and_switch())
            return
        if path == "/api/kb":
            self._json(self._handle_kb_update(body))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_chat(self, body: dict) -> dict:
        message = body.get("message", "")
        history = body.get("history", [])
        if not message:
            return {"ok": False, "error": "message is required"}
        try:
            cfg = config_from_env()
            if body.get("model"):
                cfg.model = body["model"]
            response = chat(message, history, cfg)
            return {"ok": True, "response": response}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _handle_apply(self, body: dict) -> dict:
        filepath = body.get("filepath", "")
        content = body.get("content", "")
        if not filepath or not content:
            return {"ok": False, "error": "filepath and content are required"}
        return apply_change(filepath, "", content)

    def _handle_kb_update(self, body: dict) -> dict:
        module = body.get("module", "")
        content = body.get("content", "")
        if not module or not content:
            return {"ok": False, "error": "module and content are required"}
        return update_kb(module, content)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fauxnix Admin Agent serving on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
