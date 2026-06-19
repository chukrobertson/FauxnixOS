"""Registry helpers for Faux-pass v0."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATHS = (
    Path("/etc/faux-pass/registry.json"),
    Path.home() / ".config" / "faux-pass" / "registry.json",
)


DEFAULT_REGISTRY: dict[str, Any] = {
    "version": 1,
    "providers": [
        {
            "id": "local",
            "name": "FauxnixOS",
            "type": "local",
            "status": "available",
            "apps": [
                {"id": "web", "name": "Firefox", "action": ["fauxnix-thread", "web"]},
                {"id": "terminal", "name": "Terminal", "action": ["fauxnix-thread", "terminal"]},
                {"id": "fennix", "name": "Fennix", "action": ["fennix-gui"]},
                {"id": "fauxdex", "name": "Fauxdex", "action": ["fauxnix-thread", "fauxdex"]},
                {"id": "cowriter", "name": "Cowriter", "action": ["fauxnix-thread", "cowriter"]},
            ],
        },
        {
            "id": "nexus",
            "name": "Nexus Windows Provider",
            "type": "remote-provider",
            "status": "available",
            "transport": "tailscale-http",
            "endpoint": "http://100.126.117.60:4433/faux-pass",
            "token_file": "/etc/faux-pass/nexus.token",
            "apps": [
                {"id": "notepad", "name": "Notepad", "remote": True},
                {"id": "calc", "name": "Calculator", "remote": True},
                {"id": "powershell", "name": "PowerShell", "remote": True},
                {"id": "vscode", "name": "VS Code", "remote": True},
            ],
        },
    ],
}


@dataclass(frozen=True)
class AppRef:
    provider_id: str
    provider_name: str
    provider: dict[str, Any]
    app: dict[str, Any]


def load_registry() -> dict[str, Any]:
    registry = json.loads(json.dumps(DEFAULT_REGISTRY))
    for path in CONFIG_PATHS:
        if not path.exists():
            continue
        try:
            override = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(override, dict):
            registry = merge_registry(registry, override)
    return registry


def merge_registry(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    if "providers" not in override:
        merged.update(override)
        return merged

    providers = {str(provider.get("id")): dict(provider) for provider in base.get("providers", [])}
    for provider in override.get("providers", []):
        provider_id = str(provider.get("id", "")).strip()
        if not provider_id:
            continue
        current = providers.get(provider_id, {})
        current.update(provider)
        providers[provider_id] = current
    merged["providers"] = list(providers.values())
    return merged


def providers() -> list[dict[str, Any]]:
    return list(load_registry().get("providers", []))


def provider_endpoint(provider: dict[str, Any]) -> str:
    return str(provider.get("endpoint") or "").rstrip("/")


def provider_token(provider: dict[str, Any]) -> str:
    token = str(provider.get("token") or "")
    if token:
        return token
    token_env = str(provider.get("token_env") or "")
    if token_env and os.environ.get(token_env, ""):
        return os.environ.get(token_env, "")
    token_file = str(provider.get("token_file") or "")
    if token_file:
        try:
            return Path(token_file).read_text(encoding="utf-8").strip().lstrip("\ufeff")
        except OSError:
            return ""
    return ""


def provider_request(
    provider: dict[str, Any],
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 1.8,
) -> tuple[bool, dict[str, Any] | str]:
    endpoint = provider_endpoint(provider)
    if not endpoint.startswith(("http://", "https://")):
        return False, "provider has no HTTP endpoint"

    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = provider_token(provider)
    if token:
        headers["X-Faux-Pass-Token"] = token

    request = urllib.request.Request(endpoint + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as exc:
        return False, str(exc)

    try:
        return True, json.loads(body)
    except json.JSONDecodeError:
        return False, "provider returned invalid JSON"


def provider_status(provider: dict[str, Any]) -> dict[str, Any]:
    ok, payload = provider_request(provider, "/status")
    if ok and isinstance(payload, dict):
        remote_provider = payload.get("provider")
        if isinstance(remote_provider, dict):
            merged = dict(provider)
            merged.update(remote_provider)
            return merged
    if provider_endpoint(provider).startswith(("http://", "https://")):
        unavailable = dict(provider)
        unavailable["status"] = "unreachable"
        unavailable["last_error"] = payload
        return unavailable
    return dict(provider)


def provider_apps(provider: dict[str, Any]) -> list[dict[str, Any]]:
    ok, payload = provider_request(provider, "/apps")
    if ok and isinstance(payload, dict) and isinstance(payload.get("apps"), list):
        return [
            dict(app, remote=True, remote_launchable=bool(app.get("launchable", True)))
            for app in payload["apps"]
            if isinstance(app, dict)
        ]
    fallback: list[dict[str, Any]] = []
    for app in provider.get("apps", []):
        if isinstance(app, dict):
            fallback.append(dict(app, remote_launchable=False))
    return fallback


def apps() -> list[AppRef]:
    found: list[AppRef] = []
    for provider in providers():
        provider_id = str(provider.get("id", ""))
        provider_name = str(provider.get("name", provider_id))
        candidate_apps = provider_apps(provider) if provider_endpoint(provider).startswith(("http://", "https://")) else provider.get("apps", [])
        for app in candidate_apps:
            if isinstance(app, dict):
                found.append(AppRef(provider_id, provider_name, provider, app))
    return found


def find_app(query: str) -> AppRef | None:
    wanted = query.strip().lower()
    if not wanted:
        return None
    for app_ref in apps():
        app = app_ref.app
        names = [str(app.get("id", "")), str(app.get("name", ""))]
        if any(name.lower() == wanted for name in names):
            return app_ref
    for app_ref in apps():
        app = app_ref.app
        names = [str(app.get("id", "")), str(app.get("name", ""))]
        if any(wanted in name.lower() for name in names):
            return app_ref
    return None


def launch(app_ref: AppRef) -> dict[str, Any]:
    action = app_ref.app.get("action")
    endpoint = provider_endpoint(app_ref.provider)
    if not action:
        if endpoint.startswith(("http://", "https://")):
            ok, payload = provider_request(app_ref.provider, "/run", {"app": app_ref.app.get("id")}, timeout=4.0)
            if ok and isinstance(payload, dict):
                return payload
            return {
                "ok": False,
                "provider": app_ref.provider_id,
                "app": app_ref.app.get("id"),
                "error": str(payload),
            }
        return {
            "ok": False,
            "provider": app_ref.provider_id,
            "app": app_ref.app.get("id"),
            "error": "app is registered but has no local launch action yet",
        }
    if not isinstance(action, list) or not all(isinstance(part, str) for part in action):
        return {"ok": False, "error": "invalid app action"}
    env = os.environ.copy()
    try:
        subprocess.Popen(
            action,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "provider": app_ref.provider_id,
        "app": app_ref.app.get("id"),
        "name": app_ref.app.get("name"),
        "action": action,
    }
