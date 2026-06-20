"""Surface providers — pluggable backends that feed frames into Fauxnix cards."""

from .base import DisplaySourceProvider, SurfaceProvider, InputEvent
from .registry import (
    create_source,
    create_provider,
    normalize_source_spec,
    normalize_provider_spec,
    source_descriptors,
    provider_descriptors,
    source_kinds,
    provider_kinds,
    register_source,
    register_provider,
)

__all__ = [
    "DisplaySourceProvider",
    "SurfaceProvider",
    "InputEvent",
    "create_source",
    "create_provider",
    "normalize_source_spec",
    "normalize_provider_spec",
    "source_descriptors",
    "provider_descriptors",
    "source_kinds",
    "provider_kinds",
    "register_source",
    "register_provider",
]
