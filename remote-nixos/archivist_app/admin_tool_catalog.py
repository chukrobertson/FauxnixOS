from __future__ import annotations


ADMIN_ENGINE_TOOLS = [
    {
        "id": "index.status",
        "label": "Index status",
        "mode": "run",
        "prompt": "index status",
        "safety": "safe immediate",
        "summary": "Report the active or latest archive index run.",
    },
    {
        "id": "index.embedding_status",
        "label": "Embedding status",
        "mode": "run",
        "prompt": "embedding status",
        "safety": "safe immediate",
        "summary": "Report the semantic embedding rebuild state.",
    },
    {
        "id": "index.rebuild_embeddings",
        "label": "Preview embedding rebuild",
        "mode": "run",
        "prompt": "rebuild embeddings",
        "safety": "confirmation required",
        "summary": "Create a pending rebuild action that must be confirmed before it starts.",
    },
    {
        "id": "admin.host_stats",
        "label": "Host stats",
        "mode": "run",
        "prompt": "host system stats",
        "safety": "safe immediate",
        "summary": "Report CPU, system RAM, GPU, VRAM, temperature, and configured telemetry thresholds.",
    },
    {
        "id": "admin.development_tasks.list",
        "label": "Development queue",
        "mode": "run",
        "prompt": "development task queue",
        "safety": "safe immediate",
        "summary": "List the persisted ArchivistOS development task queue and current next task.",
    },
    {
        "id": "admin.development_tasks.next",
        "label": "Next dev task",
        "mode": "run",
        "prompt": "next development task",
        "safety": "safe immediate",
        "summary": "Select the highest-priority non-done Admin development task.",
    },
    {
        "id": "admin.development_tasks.seed",
        "label": "Seed queue",
        "mode": "run",
        "prompt": "seed development queue",
        "safety": "safe immediate",
        "summary": "Create the default Admin development tasks for patch apply, command runner, project memory, and task/action links.",
    },
    {
        "id": "admin.engine_plan_schema",
        "label": "Engine plan schema",
        "mode": "run",
        "prompt": "engine plan schema",
        "safety": "safe immediate",
        "summary": "Show the structured engine plan contract used by Intelligent Admin and future engine consumers.",
    },
    {
        "id": "admin.health_check",
        "label": "Admin health check",
        "mode": "run",
        "prompt": "admin health check",
        "safety": "safe immediate",
        "summary": "Summarize runtime, indexing, source, media, and recent failure state.",
    },
    {
        "id": "admin.codex_handoff",
        "label": "Codex handoff",
        "mode": "run",
        "prompt": "codex handoff",
        "safety": "safe immediate",
        "summary": "Build a concise next-pass handoff from current project docs.",
    },
    {
        "id": "admin.self_development_status",
        "label": "Self-development status",
        "mode": "run",
        "prompt": "self development status",
        "safety": "safe immediate",
        "summary": "Explain what Intelligent Admin can and cannot do for its own development.",
    },
    {
        "id": "admin.codebase_inspection",
        "label": "Codebase inspection",
        "mode": "run",
        "prompt": "inspect codebase for Intelligent Admin tooling",
        "safety": "read only",
        "summary": "Inspect project files and likely source/doc touch points without editing anything.",
    },
    {
        "id": "admin.verification_checks",
        "label": "Verification checks",
        "mode": "run",
        "prompt": "run admin verification checks",
        "safety": "fixed commands",
        "summary": "Run the fixed frontend and Python syntax checks used after development changes.",
    },
    {
        "id": "admin.patch_proposal",
        "label": "Patch proposal",
        "mode": "run",
        "prompt": "stage patch proposal for Intelligent Admin tool buildout",
        "safety": "proposal only",
        "summary": "Create an audited development proposal; exact unified-diff proposals can proceed to snapshot/readiness/apply gates.",
    },
    {
        "id": "admin.project_status",
        "label": "Project status",
        "mode": "run",
        "prompt": "project status for vanishing share",
        "safety": "audit grounded",
        "summary": "Report project progress only from audited actions and explicitly flag missing patch artifacts.",
    },
    {
        "id": "admin.project_brief",
        "label": "Project brief",
        "mode": "run",
        "prompt": "project manager brief",
        "safety": "audit grounded",
        "summary": "Create a grounded ArchivistOS project-management brief from docs, audit state, and current engine gates.",
    },
    {
        "id": "admin.engine_profile",
        "label": "Engine profile",
        "mode": "run",
        "prompt": "engine profile",
        "safety": "safe immediate",
        "summary": "Show the current Fauxdex Engine definitions, model routes, and extraction direction.",
    },
    {
        "id": "admin.diff_validation",
        "label": "Diff validation",
        "mode": "run",
        "prompt": "validate latest patch proposal",
        "safety": "read only",
        "summary": "Check whether the latest patch proposal draft hunks still match current file context.",
    },
    {
        "id": "admin.apply_readiness",
        "label": "Apply readiness",
        "mode": "run",
        "prompt": "apply readiness report",
        "safety": "read only",
        "summary": "Report whether the latest proposal has enough validated evidence to consider a future apply step.",
    },
    {
        "id": "admin.patch_apply",
        "label": "Apply request",
        "mode": "run",
        "prompt": "apply latest patch proposal",
        "safety": "confirmation gated",
        "summary": "Apply a validated, snapshotted unified-diff proposal only after a separate confirmation.",
    },
    {
        "id": "admin.patch_snapshot",
        "label": "Patch snapshot",
        "mode": "run",
        "prompt": "snapshot latest patch proposal",
        "safety": "backup only",
        "summary": "Copy a proposal's affected files into a data snapshot before any future apply step.",
    },
    {
        "id": "admin.patch_rollback",
        "label": "Patch rollback",
        "mode": "run",
        "prompt": "rollback latest patch",
        "safety": "confirmation gated",
        "summary": "Restore files from a trusted Admin patch snapshot manifest, then run fixed verification.",
    },
    {
        "id": "admin.intelligent_admin.plan",
        "label": "Plan workspace change",
        "mode": "plan",
        "prompt": "Plan the next safe ArchivistOS upgrade I can test.",
        "safety": "safe planning",
        "summary": "Use the admin planning context to stage a change plan.",
    },
]


def admin_engine_tools_payload() -> dict:
    return {"workspace": "intelligent_admin", "powered_by": "fauxdex_engine", "tools": ADMIN_ENGINE_TOOLS}


def format_admin_tool_catalog() -> str:
    lines = ["Intelligent Admin tools for ArchivistOS maintenance and development:"]
    for tool in ADMIN_ENGINE_TOOLS:
        lines.append(f"- {tool['label']} ({tool['mode']}): {tool['summary']} Trigger: `{tool['prompt']}`.")
    return "\n".join(lines)


__all__ = [
    "ADMIN_ENGINE_TOOLS",
    "admin_engine_tools_payload",
    "format_admin_tool_catalog",
]
