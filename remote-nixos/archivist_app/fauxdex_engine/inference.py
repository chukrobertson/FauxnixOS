from __future__ import annotations

import re

from .contracts import ENGINE_PLAN_SCHEMA


def dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def task_terms(task: str) -> list[str]:
    stop = {"the", "and", "for", "with", "this", "that", "from", "into", "admin", "fauxdex", "engine", "please", "lets"}
    return [word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", task.lower()) if word not in stop][:8]


def infer_intent(task: str, mode: str) -> str:
    lowered = task.lower()
    if any(word in lowered for word in ["apply", "patch", "diff", "rollback"]):
        return "stage_safe_source_change"
    if any(word in lowered for word in ["queue", "task", "project manager", "next"]):
        return "manage_development_queue"
    if any(word in lowered for word in ["inspect", "status", "health", "stats", "gpu", "cpu"]):
        return "inspect_system_state"
    if any(word in lowered for word in ["timeline", "face", "person", "event", "evidence"]):
        return "expand_archive_reconstruction"
    if mode == "admin":
        return "maintain_host_project"
    return "plan_coding_work"


def infer_files(task: str, mode: str) -> list[str]:
    lowered = task.lower()
    files = []
    if mode == "admin" or any(word in lowered for word in ["admin", "intelligent", "maintenance"]):
        files.extend(["app/main.py", "app/admin_development.py", "web/index.html", "web/app.js", "web/styles.css"])
    if any(word in lowered for word in ["engine", "fauxdex", "structured", "plan", "model", "reasoning"]):
        files.extend(
            [
                "app/fauxdex.py",
                "app/fauxdex_engine/contracts.py",
                "app/fauxdex_engine/planner.py",
                "app/fauxdex_engine/inference.py",
                "app/fauxdex_engine/prompts.py",
                "docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md",
                "docs/API_REFERENCE.md",
            ]
        )
    if any(word in lowered for word in ["patch", "diff", "apply", "rollback", "snapshot"]):
        files.extend(["app/main.py", "app/file_operator.py", "app/admin_development.py", "docs/ACTION_AUDIT_CONTRACTS.md"])
    if any(word in lowered for word in ["timeline", "face", "person", "event", "evidence"]):
        files.extend(["app/timeline.py", "app/models.py", "app/db.py", "web/index.html", "web/app.js", "docs/TIMELINE_RECONSTRUCTION.md"])
    if any(word in lowered for word in ["stats", "gpu", "cpu", "ram", "host", "temperature"]):
        files.extend(["app/admin_controls.py", "web/index.html", "web/app.js", "web/styles.css"])
    if any(word in lowered for word in ["docs", "roadmap", "contract", "schema"]):
        files.extend(["docs/API_REFERENCE.md", "docs/ACTION_AUDIT_CONTRACTS.md", "docs/ROADMAP.md"])
    if not files:
        files = ["app/main.py", "web/app.js", "docs/ROADMAP.md"]
    return dedupe(files)


def suggest_tools(task: str, mode: str) -> list[dict]:
    lowered = task.lower()
    tools = []
    if mode == "admin":
        tools.append({"id": "admin.development_tasks.next", "label": "Next development task", "prompt": "next development task", "mode": "run"})
        tools.append({"id": "admin.codebase_inspection", "label": "Inspect codebase", "prompt": f"inspect codebase for {task}", "mode": "run"})
    if any(word in lowered for word in ["patch", "diff", "apply", "source", "code", "build"]):
        tools.extend(
            [
                {"id": "admin.patch_proposal", "label": "Stage patch proposal", "prompt": f"stage patch proposal for {task}", "mode": "run"},
                {"id": "admin.diff_validation", "label": "Validate diff", "prompt": "validate latest patch proposal", "mode": "run"},
                {"id": "admin.patch_snapshot", "label": "Snapshot patch", "prompt": "snapshot latest patch proposal", "mode": "run"},
                {"id": "admin.apply_readiness", "label": "Apply readiness", "prompt": "apply readiness report", "mode": "run"},
                {"id": "admin.verification_checks", "label": "Run checks", "prompt": "run admin verification checks", "mode": "run"},
            ]
        )
    if "rollback" in lowered or "restore" in lowered:
        tools.append({"id": "admin.patch_rollback", "label": "Rollback patch", "prompt": "rollback latest patch", "mode": "run"})
    if any(word in lowered for word in ["status", "health", "stats", "gpu", "cpu"]):
        tools.extend(
            [
                {"id": "admin.health_check", "label": "Health check", "prompt": "admin health check", "mode": "run"},
                {"id": "admin.host_stats", "label": "Host stats", "prompt": "host system stats", "mode": "run"},
            ]
        )
    if any(word in lowered for word in ["handoff", "tokens", "continue"]):
        tools.append({"id": "admin.codex_handoff", "label": "Codex handoff", "prompt": "codex handoff", "mode": "run"})
    seen = set()
    out = []
    for tool in tools:
        key = tool["id"]
        if key not in seen:
            seen.add(key)
            out.append(tool)
    return out[:8]


def risk_level(task: str, mode: str) -> str:
    lowered = task.lower()
    if any(word in lowered for word in ["apply", "delete", "wipe", "move", "rollback", "restart", "stop"]):
        return "high"
    if any(word in lowered for word in ["patch", "source", "code", "schema", "database"]):
        return "medium"
    return "low" if mode == "fauxdex" else "medium"


def structured_plan(task: str, mode: str, answer: str | None = None, model_error: str | None = None) -> dict:
    intent = infer_intent(task, mode)
    risk = risk_level(task, mode)
    files = infer_files(task, mode)
    tools = suggest_tools(task, mode)
    gates = [
        "Separate planning claims from audited actions.",
        "Use preview/dry-run before broad filesystem, index, or source changes.",
    ]
    if risk in {"medium", "high"}:
        gates.extend(["Validate file context before edits.", "Snapshot affected files before any apply step.", "Run fixed verification checks after changes."])
    if risk == "high":
        gates.append("Require explicit confirmation and rollback notes before execution.")
    steps = [
        "Confirm intent and scope from the task.",
        "Inspect likely files and current audit/development queue state.",
        "Stage a structured proposal with affected files, risks, verification, and rollback.",
    ]
    if tools:
        steps.append(f"Run suggested tool: {tools[0]['id']}.")
    steps.append("Update the development queue or action audit with the result.")
    verification = ["Review action audit output.", "Run `node --check web\\app.js` when frontend code changes.", "Run Python compileall when backend code changes."]
    rollback = ["Keep source changes behind patch proposals until snapshots exist.", "Use snapshot manifest to restore touched files before re-running verification."]
    missing = []
    if "SEARCH_TERM" in task or not task_terms(task):
        missing.append("More specific target terms may improve file/tool selection.")
    if model_error:
        missing.append("Model-backed reasoning was unavailable; deterministic engine structure was used.")
    return {
        "schema": ENGINE_PLAN_SCHEMA["schema"],
        "workspace": "intelligent_admin" if mode == "admin" else "fauxdex_lab",
        "task": task,
        "intent": intent,
        "risk_level": risk,
        "likely_files": files,
        "suggested_tools": tools,
        "safety_gates": dedupe(gates),
        "implementation_steps": steps,
        "verification": dedupe(verification),
        "rollback": dedupe(rollback),
        "handoff": f"{intent}: inspect {', '.join(files[:4])}; then use {tools[0]['id'] if tools else 'manual review'}." if files else intent,
        "missing_inputs": missing,
        "terms": task_terms(task),
        "model_summary": (answer or "")[:600],
    }


def format_structured_plan(plan: dict) -> str:
    lines = [
        "Structured engine plan:",
        f"- Schema: {plan.get('schema')}",
        f"- Workspace: {plan.get('workspace')}",
        f"- Intent: {plan.get('intent')} | risk: {plan.get('risk_level')}",
    ]
    files = plan.get("likely_files") or []
    if files:
        lines.append("- Likely files: " + ", ".join(files[:6]))
    tools = plan.get("suggested_tools") or []
    if tools:
        lines.append("- Suggested tools: " + ", ".join(tool.get("id", "") for tool in tools[:6]))
    if plan.get("handoff"):
        lines.append(f"- Handoff: {plan.get('handoff')}")
    return "\n".join(lines)
