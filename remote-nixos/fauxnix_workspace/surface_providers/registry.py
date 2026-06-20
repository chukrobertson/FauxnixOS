"""Registry and factory for pluggable Display card sources.

The older public names use "provider"; the product model is now "Display card
as monitor" plus "DisplaySource plugged into it". Keep provider aliases so
restored sessions and tests continue to work while new code can speak source.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Callable

from .base import SurfaceProvider


ProviderFactory = Callable[[dict], SurfaceProvider]


@dataclass(frozen=True)
class SurfaceProviderDescriptor:
    kind: str
    label: str
    description: str = ""
    required: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "required": list(self.required),
        }


_FACTORIES: dict[str, ProviderFactory] = {}
_DESCRIPTORS: dict[str, SurfaceProviderDescriptor] = {}


DisplaySourceDescriptor = SurfaceProviderDescriptor


def register_provider(
    kind: str,
    *,
    label: str | None = None,
    description: str = "",
    required: tuple[str, ...] = (),
):
    """Register a provider factory under a stable kind string."""
    key = _normalize_kind(kind)

    def decorator(factory: ProviderFactory) -> ProviderFactory:
        _FACTORIES[key] = factory
        _DESCRIPTORS[key] = SurfaceProviderDescriptor(
            kind=key,
            label=label or key,
            description=description,
            required=required,
        )
        return factory

    return decorator


register_source = register_provider


def _normalize_kind(kind: str) -> str:
    return str(kind).strip().lower().replace("_", "-")


def normalize_provider_spec(spec) -> dict:
    """Return a normalized DisplaySource descriptor dict.

    The descriptor is intentionally plain JSON-shaped data so any future plugin,
    VM bridge, or Fauxpass service can hand it to a Display card.
    """
    if isinstance(spec, str):
        spec = {"kind": spec}
    if not isinstance(spec, dict):
        raise ValueError("source spec must be a dict or source kind string")
    normalized = dict(spec)
    kind = (
        normalized.get("kind")
        or normalized.get("source_kind")
        or normalized.get("display_source")
        or normalized.get("provider_kind")
        or normalized.get("provider")
        or normalized.get("backend")
        or normalized.get("type")
    )
    if not kind:
        raise ValueError("source spec is missing kind")
    normalized["kind"] = _normalize_kind(kind)
    normalized["source_kind"] = normalized["kind"]
    return normalized


normalize_source_spec = normalize_provider_spec


def provider_descriptors() -> list[dict]:
    return [descriptor.as_dict() for descriptor in sorted(_DESCRIPTORS.values(), key=lambda d: d.kind)]


source_descriptors = provider_descriptors


def provider_kinds() -> list[str]:
    return sorted(_FACTORIES)


source_kinds = provider_kinds


def create_provider(spec) -> SurfaceProvider:
    normalized = normalize_provider_spec(spec)
    kind = normalized["kind"]
    factory = _FACTORIES.get(kind)
    if factory is None:
        available = ", ".join(source_kinds()) or "none"
        raise ValueError(f"unknown display source kind '{kind}' (available: {available})")
    return factory(normalized)


create_source = create_provider


def _argv_from_spec(spec: dict) -> list[str]:
    argv = spec.get("argv")
    if argv is None:
        argv = spec.get("args")
    if argv is None:
        argv = spec.get("command")
    if argv is None:
        argv = spec.get("exec")
    if isinstance(argv, str):
        argv = shlex.split(argv)
    if not isinstance(argv, list) or not argv:
        raise ValueError("xwayland-per-app provider requires argv, command, or exec")
    return [str(item) for item in argv]


@register_provider(
    "xwayland-per-app",
    label="Xwayland Per App",
    description="Runs one X11 app inside a private rootful Xwayland surface.",
    required=("argv",),
)
def _create_xwayland_per_app(spec: dict) -> SurfaceProvider:
    from .xwayland_per_app import XwaylandPerApp

    env = spec.get("env") or {}
    if not isinstance(env, dict):
        raise ValueError("xwayland-per-app env must be a dict")
    width = int(spec.get("width", spec.get("w", 800)))
    height = int(spec.get("height", spec.get("h", 600)))
    return XwaylandPerApp(
        argv=_argv_from_spec(spec),
        env={str(k): str(v) for k, v in env.items()},
        width=max(1, width),
        height=max(1, height),
        source_kind=str(spec.get("_source_kind") or spec.get("source_kind") or spec.get("kind") or ""),
        source_name=str(spec.get("source_name") or spec.get("surface_name") or spec.get("name") or ""),
    )


@register_provider(
    "local-app",
    label="Local App",
    description="Runs one local desktop app inside a private display source.",
    required=("argv",),
)
def _create_local_app(spec: dict) -> SurfaceProvider:
    aliased = dict(spec)
    aliased["_source_kind"] = "local-app"
    aliased["kind"] = "xwayland-per-app"
    return _create_xwayland_per_app(aliased)


@register_provider(
    "xwayland",
    label="Xwayland Per App",
    description="Alias for xwayland-per-app.",
    required=("argv",),
)
def _create_xwayland_alias(spec: dict) -> SurfaceProvider:
    aliased = dict(spec)
    aliased["kind"] = "xwayland-per-app"
    return _create_xwayland_per_app(aliased)


@register_provider(
    "fauxpass-app",
    label="Faux-pass App",
    description="Launches a local or remote faux-pass app source from a Display card.",
    required=("app",),
)
def _create_fauxpass_app(spec: dict) -> SurfaceProvider:
    from .fauxpass_app import FauxPassAppProvider

    app = spec.get("app") or spec.get("app_id") or spec.get("id")
    if not app:
        raise ValueError("fauxpass-app provider requires app or app_id")
    width = int(spec.get("width", spec.get("w", 800)))
    height = int(spec.get("height", spec.get("h", 600)))
    return FauxPassAppProvider(
        app=str(app),
        provider_id=str(spec.get("provider_id") or spec.get("source") or ""),
        width=max(1, width),
        height=max(1, height),
    )
