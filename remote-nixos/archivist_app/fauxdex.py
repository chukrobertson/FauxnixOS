from __future__ import annotations

from app.config import BASE_DIR
from app.dashboard import dashboard_context, format_dashboard_context
from app.embeddings import chat_messages
from app.fauxdex_engine import ENGINE_PLAN_SCHEMA, EngineContext, format_structured_plan
from app.fauxdex_engine.planner import plan_fauxdex_engine_task as plan_engine_task
from app.memory import add_message, ensure_conversation
from app.notes import format_workspace_context


ENGINE_CONTEXT_FILES = [
    "README.md",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/ACTION_AUDIT_CONTRACTS.md",
    "docs/API_REFERENCE.md",
    "docs/TIMELINE_RECONSTRUCTION.md",
    "docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md",
    "docs/FAUXDEX_ENGINE_EXTRACTION.md",
]


def _read_engine_context(max_chars: int = 18000) -> str:
    chunks = []
    remaining = max_chars
    for rel_path in ENGINE_CONTEXT_FILES:
        if remaining <= 0:
            break
        path = (BASE_DIR / rel_path).resolve(strict=False)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if not text:
            continue
        excerpt = text[:remaining]
        chunks.append(f"## {rel_path}\n{excerpt}")
        remaining -= len(excerpt)
    return "\n\n".join(chunks)


def archivist_engine_context(*, include_user_context: bool = False) -> EngineContext:
    return EngineContext(
        project_context=_read_engine_context(),
        dashboard_context=format_dashboard_context(dashboard_context()) if include_user_context else "",
        workspace_context=format_workspace_context() if include_user_context else "",
    )


def plan_fauxdex_engine_task(task: str, conversation_id: str | None = None, *, mode: str = "fauxdex") -> dict:
    scope = "admin" if mode == "admin" else "fauxdex"

    def engine_model_chat(messages: list[dict], *, task: str, fallback_task: str | None = None) -> str:
        return chat_messages(messages, task=task, fallback_task=fallback_task, apply_personality=False)

    return plan_engine_task(
        task,
        conversation_id,
        mode=mode,
        context=archivist_engine_context(include_user_context=False),
        base_system_prompt="",
        model_chat=engine_model_chat,
        ensure_conversation=lambda current_id, title_seed: ensure_conversation(current_id, title_seed, scope=scope),
        add_message=add_message,
    )


def plan_fauxdex_task(task: str, conversation_id: str | None = None) -> dict:
    return plan_fauxdex_engine_task(task, conversation_id, mode="fauxdex")


def plan_intelligent_admin_task(task: str, conversation_id: str | None = None) -> dict:
    return plan_fauxdex_engine_task(task, conversation_id, mode="admin")


__all__ = [
    "ENGINE_CONTEXT_FILES",
    "ENGINE_PLAN_SCHEMA",
    "archivist_engine_context",
    "format_structured_plan",
    "plan_fauxdex_engine_task",
    "plan_fauxdex_task",
    "plan_intelligent_admin_task",
]
