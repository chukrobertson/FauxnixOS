from __future__ import annotations

from .adapters import AddMessage, EnsureConversation, ModelChat
from .context import EMPTY_CONTEXT, EngineContext
from .contracts import ENGINE_PLAN_SCHEMA, WORKSPACE_LABELS
from .inference import format_structured_plan, structured_plan
from .prompts import engine_system_prompt, planning_prompt


def fallback_plan(task: str, mode: str = "fauxdex") -> str:
    title = "Intelligent Admin plan:" if mode == "admin" else "Fauxdex plan:"
    return "\n".join(
        [
            title,
            "1. Inspect the current host/project state and any recent actions related to this task.",
            "2. Run a preview or dry-run first if the task touches files, folders, indexing, sources, or network setup.",
            "3. Review the proposed changes and keep chat-aware boundaries explicit.",
            "4. For app changes, create a patch proposal with affected files, verification steps, and rollback notes.",
            "5. Execute only confirmed, reversible steps through audited tool paths.",
            "",
            f"Task: {task}",
        ]
    )


def plan_fauxdex_engine_task(
    task: str,
    conversation_id: str | None = None,
    *,
    mode: str = "fauxdex",
    context: EngineContext = EMPTY_CONTEXT,
    base_system_prompt: str = "",
    model_chat: ModelChat,
    ensure_conversation: EnsureConversation,
    add_message: AddMessage,
) -> dict:
    clean_task = (task or "").strip()
    if len(clean_task) < 2:
        raise ValueError("Fauxdex task is too short")

    mode = "admin" if mode == "admin" else "fauxdex"
    conversation_id = ensure_conversation(conversation_id, clean_task)
    label = WORKSPACE_LABELS["admin"] if mode == "admin" else WORKSPACE_LABELS["fauxdex"]
    user_message_id = add_message(conversation_id, "user", f"{label} Engine request:\n{clean_task}")

    prompt = planning_prompt(
        label=label,
        task=clean_task,
        mode=mode,
        project_context=context.project_context,
        dashboard_context=context.dashboard_context,
        workspace_context=context.workspace_context,
    )

    messages = [
        {"role": "system", "content": engine_system_prompt(base_system_prompt)},
        {"role": "user", "content": prompt},
    ]

    try:
        answer = model_chat(messages, task="reasoning", fallback_task="cowriter_code")
        model_error = None
    except Exception as error:
        answer = fallback_plan(clean_task, mode=mode)
        model_error = str(error)

    plan = structured_plan(clean_task, mode, answer=answer, model_error=model_error)
    assistant_message_id = add_message(conversation_id, "assistant", answer)
    return {
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "answer": answer,
        "structured_plan": plan,
        "structured_summary": format_structured_plan(plan),
        "plan_schema": ENGINE_PLAN_SCHEMA,
        "engine": "fauxdex",
        "mode": mode,
        "model_task": "reasoning",
        "model_error": model_error,
    }
