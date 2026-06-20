from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineContext:
    project_context: str = ""
    dashboard_context: str = ""
    workspace_context: str = ""


EMPTY_CONTEXT = EngineContext()
