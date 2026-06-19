"""Command-line entrypoint for Faux-pass v0."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .registry import apps, find_app, launch, load_registry, provider_status, providers


def emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_status(args: argparse.Namespace) -> int:
    registry = load_registry()
    provider_rows = []
    for provider in providers():
        status = provider_status(provider)
        app_count = status.get("apps", len(provider.get("apps", [])))
        if isinstance(app_count, list):
            app_count = len(app_count)
        provider_rows.append(
            {
                "id": provider.get("id"),
                "name": status.get("name"),
                "type": status.get("type"),
                "status": status.get("status", "unknown"),
                "apps": app_count,
            }
        )
    payload = {"ok": True, "version": registry.get("version", 1), "providers": provider_rows}
    if args.json:
        emit(payload, True)
    else:
        print("Faux-pass v0")
        for provider in payload["providers"]:
            print(
                f"- {provider['id']}: {provider['name']} "
                f"({provider['type']}, {provider['status']}, {provider['apps']} apps)"
            )
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    payload = {"ok": True, "providers": providers()}
    emit(payload, args.json)
    return 0


def cmd_apps(args: argparse.Namespace) -> int:
    app_rows = [
        {
            "id": app_ref.app.get("id"),
            "name": app_ref.app.get("name"),
            "provider": app_ref.provider_id,
            "provider_name": app_ref.provider_name,
            "launchable": bool(app_ref.app.get("action") or app_ref.app.get("remote_launchable")),
            "remote": bool(app_ref.app.get("remote")),
        }
        for app_ref in apps()
    ]
    payload = {"ok": True, "apps": app_rows}
    if args.json:
        emit(payload, True)
    else:
        for app in app_rows:
            marker = "remote" if app["remote"] else "local"
            launchable = "launchable" if app["launchable"] else "planned"
            print(f"{app['id']:12} {app['name']:18} {app['provider']:8} {marker:6} {launchable}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    app_ref = find_app(args.app)
    if app_ref is None:
        emit({"ok": False, "error": f"unknown app: {args.app}"}, args.json)
        return 1
    result = launch(app_ref)
    if args.json:
        emit(result, True)
    elif result.get("ok"):
        print(f"Launching {result.get('name') or result.get('app')} via {result.get('provider')}")
    else:
        print(f"Cannot launch {args.app}: {result.get('error')}", file=sys.stderr)
    return 0 if result.get("ok") else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faux-pass", description="Faux-pass app provider registry")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="show provider status").set_defaults(func=cmd_status)
    sub.add_parser("providers", help="list providers").set_defaults(func=cmd_providers)
    sub.add_parser("apps", help="list apps").set_defaults(func=cmd_apps)

    run = sub.add_parser("run", help="launch an app by id or name")
    run.add_argument("app")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args.func = cmd_status
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
