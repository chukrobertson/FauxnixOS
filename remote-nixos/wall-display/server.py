#!/usr/bin/env python3
"""Fauxnix Wall Display — family calendar kiosk UI served on the local network."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STARTED_AT = time.time()
PORT = int(os.environ.get("FAUXNIX_WALL_PORT", "8780"))
HOST = os.environ.get("FAUXNIX_WALL_HOST", "0.0.0.0")

# ── Settings ────────────────────────────────────────────────────────────

SETTINGS_PATH = Path(
    os.environ.get(
        "FAUXNIX_WALL_SETTINGS",
        os.path.expanduser("~/.config/fauxnix/wall-settings.json"),
    )
)

DEFAULT_SETTINGS = {
    "zipcode": "",
    "calendar_ics_url": "",
    "calendar_sync_interval_hours": 6,
    "last_sync": None,
    "sync_status": "never",
}


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            raw = SETTINGS_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def _save_settings(s: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")


# ── Calendar data ──────────────────────────────────────────────────────

CALENDAR_PATH = Path(
    os.environ.get(
        "FAUXNIX_WALL_CALENDAR",
        os.path.expanduser("~/.config/fauxnix/wall-calendar.json"),
    )
)


def _default_events() -> list[dict]:
    today = date.today()
    return [
        {"date": today.isoformat(), "time": "08:00", "title": "Breakfast", "color": "#ff7800"},
        {"date": today.isoformat(), "time": "12:00", "title": "Lunch", "color": "#00c8ff"},
        {"date": today.isoformat(), "time": "18:00", "title": "Dinner", "color": "#4fe18a"},
    ]


def _load_events() -> list[dict]:
    if CALENDAR_PATH.exists():
        try:
            raw = CALENDAR_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data.get("events", [])
        except Exception:
            pass
    return _default_events()


# ── Weather ────────────────────────────────────────────────────────────

def _fetch_weather(zipcode: str) -> dict:
    if not zipcode:
        return {"temp": None, "icon": "\u2601", "condition": "no zipcode set", "zipcode": ""}
    try:
        url = f"https://wttr.in/{zipcode}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        cc = data.get("current_condition", [{}])[0]
        temp = cc.get("temp_F")
        desc = cc.get("weatherDesc", [{}])[0].get("value", "")
        code = cc.get("weatherCode", 0)
        icon_map = {
            113: "\u2600", 116: "\u26c5", 119: "\u2601", 122: "\u2601",
            143: "\u2591", 176: "\u2614", 179: "\u2603", 182: "\u2603",
            185: "\u2603", 200: "\u26c8", 227: "\u2603", 230: "\u2603",
            248: "\u2591", 260: "\u2591", 263: "\u2614", 266: "\u2614",
            281: "\u2614", 284: "\u2614", 293: "\u2614", 296: "\u2614",
            299: "\u2614", 302: "\u2614", 305: "\u2614", 308: "\u2614",
            311: "\u2614", 314: "\u2614", 317: "\u2614", 320: "\u2603",
            323: "\u2603", 326: "\u2603", 329: "\u2603", 332: "\u2603",
            335: "\u2603", 338: "\u2603", 350: "\u2614", 353: "\u2614",
            356: "\u2614", 359: "\u2614", 362: "\u2614", 365: "\u2614",
            368: "\u2603", 371: "\u2603", 374: "\u2614", 377: "\u2614",
            386: "\u26c8", 389: "\u26c8", 392: "\u26c8", 395: "\u26c8",
        }
        icon = icon_map.get(code, "\u2601")
        return {
            "temp": temp,
            "icon": icon,
            "condition": desc,
            "zipcode": zipcode,
            "feels_like": cc.get("FeelsLikeF"),
            "humidity": cc.get("humidity"),
            "wind_speed": cc.get("windspeedMiles"),
        }
    except Exception as e:
        return {"temp": None, "icon": "\u26a0", "condition": f"error: {e}", "zipcode": zipcode}


# ── Calendar sync (stub) ──────────────────────────────────────────────

def _sync_ical(ics_url: str) -> dict:
    if not ics_url:
        return {"ok": False, "error": "no calendar URL configured"}
    try:
        req = urllib.request.Request(ics_url, headers={"User-Agent": "FauxnixWall/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        events = _parse_ics(raw)
        cal_data = {"version": 2, "updated": datetime.now().isoformat(), "events": events}
        CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALENDAR_PATH.write_text(json.dumps(cal_data, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "event_count": len(events)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _parse_ics(raw: str) -> list[dict]:
    events = []
    current = {}
    in_event = False
    for line in raw.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            in_event = True
        elif line == "END:VEVENT":
            in_event = False
            if current.get("SUMMARY") and current.get("DTSTART"):
                dtstart = current["DTSTART"]
                date_part = dtstart[:10] if len(dtstart) >= 8 else ""
                time_part = ""
                if len(dtstart) > 8:
                    t = dtstart[9:13] if "T" in dtstart else ""
                    time_part = f"{t[:2]}:{t[2:]}" if len(t) >= 4 else ""
                if date_part:
                    events.append({
                        "date": date_part,
                        "time": time_part,
                        "title": current.get("SUMMARY", "").replace("\\,", ","),
                        "color": "#00c8ff",
                    })
            current = {}
        elif in_event and ":" in line:
            key, _, value = line.partition(":")
            if key in ("DTSTART", "DTSTART;VALUE=DATE"):
                current["DTSTART"] = value.strip()
            elif key == "SUMMARY":
                current["SUMMARY"] = value.strip()
            elif key == "DESCRIPTION":
                current["DESCRIPTION"] = value.strip()
    return events


# ── Helpers ────────────────────────────────────────────────────────────

def _run(args: list[str], timeout: float = 3.0) -> str:
    try:
        completed = subprocess.run(
            args, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=timeout,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def _pgrep(pattern: str) -> bool:
    return bool(_run(["pgrep", "-af", pattern]))


def _systemctl_active(service: str) -> str:
    if not shutil.which("systemctl"):
        return "unknown"
    return _run(["systemctl", "is-active", service]) or "unknown"


# ── Handlers ───────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "FauxnixWall/0.1"

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])

        if path == "/api/calendar":
            self._json({"events": _load_events()})
            return

        if path == "/api/weather":
            settings = _load_settings()
            self._json(_fetch_weather(settings.get("zipcode", "")))
            return

        if path == "/api/settings":
            self._json(_load_settings())
            return

        if path == "/api/status":
            usage = shutil.disk_usage("/")
            self._json({
                "hostname": socket.gethostname(),
                "uptimeSeconds": int(time.time() - STARTED_AT),
                "serverTime": datetime.now().isoformat(),
                "disk": {
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": round((usage.used / usage.total) * 100, 1),
                },
                "services": {
                    "wall-display": "active",
                    "archivist": _systemctl_active("fauxnix-archivist-web.service"),
                    "ollama": _systemctl_active("ollama.service"),
                    "tailscaled": _systemctl_active("tailscaled.service"),
                },
                "processes": {
                    "wayfire": _pgrep("wayfire"),
                    "chromium": _pgrep("chromium"),
                },
            })
            return

        if path == "/api/health":
            self._json({"ok": True})
            return

        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/settings":
            current = _load_settings()
            for key in ("zipcode", "calendar_ics_url", "calendar_sync_interval_hours"):
                if key in payload:
                    current[key] = payload[key]
            _save_settings(current)
            self._json({"ok": True, "settings": current})
            return

        if path == "/api/calendar/sync":
            settings = _load_settings()
            result = _sync_ical(settings.get("calendar_ics_url", ""))
            settings["last_sync"] = datetime.now().isoformat()
            settings["sync_status"] = "ok" if result.get("ok") else "error"
            _save_settings(settings)
            self._json(result)
            return

        self._json({"ok": False, "error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        # Allow any local/tailnet origin (the node-desktop kiosk on a different port)
        if origin and ("127.0.0.1" in origin or "::1" in origin or "localhost" in origin or origin.startswith("http://100.")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
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
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache, max-age=60")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ── Entry point ────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Fauxnix Wall Display server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fauxnix Wall Display serving on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
