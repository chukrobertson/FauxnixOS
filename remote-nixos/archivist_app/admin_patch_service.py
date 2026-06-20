from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from app.config import DATA_DIR
from app.db import get_conn
from app.file_operator import latest_pending_action, load_action
from app.utils import path_is_inside, sha256_file


PATCH_ALLOWED_ROOTS = ("app/", "web/", "docs/", "Fauxdex/")
PATCH_ALLOWED_ROOT_FILES = {
    "README.md",
    "requirements.txt",
    "run_server.py",
    "run_index.py",
    ".gitattributes",
    ".gitignore",
}


def infer_development_files(task: str) -> list[str]:
    lowered = task.lower()
    files: list[str] = []
    if any(word in lowered for word in ["vanish", "vanishing", "temporary share", "share link", "tailscale", "funnel"]):
        files.extend([
            "app/vanishing_share.py",
            "app/main.py",
            "app/models.py",
            "web/index.html",
            "web/app.js",
            "web/styles.css",
            "docs/API_REFERENCE.md",
            "docs/ACTION_AUDIT_CONTRACTS.md",
            "docs/ROADMAP.md",
        ])
    if any(word in lowered for word in ["admin", "intelligent", "engine", "fauxdex", "tool", "patch"]):
        files.extend([
            "app/main.py",
            "app/admin_patch_service.py",
            "app/fauxdex.py",
            "app/fauxdex_engine/contracts.py",
            "app/fauxdex_engine/planner.py",
            "app/fauxdex_engine/inference.py",
            "app/fauxdex_engine/prompts.py",
            "web/index.html",
            "web/app.js",
            "web/styles.css",
        ])
    if any(word in lowered for word in ["timeline", "face", "person", "event", "evidence"]):
        files.extend(["app/timeline.py", "app/models.py", "app/db.py", "docs/TIMELINE_RECONSTRUCTION.md"])
    if any(word in lowered for word in ["doc", "handoff", "roadmap", "contract"]):
        files.extend(["docs/API_REFERENCE.md", "docs/ACTION_AUDIT_CONTRACTS.md", "docs/ROADMAP.md", "docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md"])
    if not files:
        files.extend(["app/main.py", "web/app.js", "web/index.html", "docs/ROADMAP.md"])
    deduped = []
    for path in files:
        if path not in deduped:
            deduped.append(path)
    return deduped


def clean_patch_task(query: str) -> str:
    cleaned = re.sub(r"\b(stage|create|make|draft|prepare)\b", "", query, flags=re.I)
    cleaned = re.sub(r"\b(patch|proposal|flow)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*,\s*,+", ",", cleaned)
    cleaned = re.sub(r",\s+and\b", " and", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :.-")
    return cleaned or query.strip() or "Continue Intelligent Admin tooling buildout"


def patch_preview_for_file(path: str, task: str) -> dict:
    lowered = f"{task} {path}".lower()
    if path.endswith("app/main.py"):
        intent = "Add or route an audited backend tool contract for the requested Admin/Fauxdex capability."
        edit_type = "backend route/runtime handler"
        preview = [
            "@@ app/main.py",
            "+ Register the tool in the Admin tool catalog.",
            "+ Add a payload/formatter helper for the tool result.",
            "+ Add a guarded branch in the runtime dispatcher.",
            "+ Write an action_audit row with explicit safety/result metadata.",
        ]
    elif path.endswith("app/admin_patch_service.py"):
        intent = "Extend the focused Admin patch proposal, validation, snapshot, or apply-gate service."
        edit_type = "admin patch service"
        preview = [
            "@@ app/admin_patch_service.py",
            "+ Add proposal/readiness/snapshot behavior in the focused patch service.",
            "+ Keep direct source modification blocked until unified diffs and rollback are implemented.",
        ]
    elif path.endswith("app/fauxdex.py"):
        intent = "Update Fauxdex Engine planning context or prompts when the capability changes engine behavior."
        edit_type = "engine context/prompt"
        preview = [
            "@@ app/fauxdex.py",
            "+ Include the new capability boundary in engine planning context if needed.",
            "+ Keep self-development language preview-first and confirmation-gated.",
        ]
    elif path.endswith("web/index.html"):
        intent = "Expose the capability in the Intelligent Admin surface."
        edit_type = "UI markup"
        preview = [
            "@@ web/index.html",
            "+ Add or update an Admin quick action or panel section.",
            "+ Preserve the Fauxdex Engine badge on Admin chat surfaces.",
        ]
    elif path.endswith("web/app.js"):
        intent = "Connect the UI to the new tool and render its action detail clearly."
        edit_type = "frontend behavior"
        preview = [
            "@@ web/app.js",
            "+ Load or invoke the tool through the Admin run/plan path.",
            "+ Render structured action details instead of relying only on raw JSON.",
            "+ Refresh action history after tool execution.",
        ]
    elif path.endswith("web/styles.css"):
        intent = "Style any new action detail sections or controls."
        edit_type = "frontend styling"
        preview = [
            "@@ web/styles.css",
            "+ Add compact review styles for any new detail blocks.",
            "+ Keep cards readable on narrow viewports.",
        ]
    elif path.endswith(".md"):
        intent = "Document the capability, safety contract, and roadmap state."
        edit_type = "documentation"
        preview = [
            f"@@ {path}",
            "+ Add/update API, action contract, roadmap, or knowledgebase notes.",
            "+ State what the tool can do and what it must not claim.",
        ]
    elif any(word in lowered for word in ["timeline", "face", "person", "event", "evidence"]):
        intent = "Extend timeline/face/evidence structures or docs for reconstruction workflows."
        edit_type = "timeline feature"
        preview = [
            f"@@ {path}",
            "+ Add fields/routes/UI needed to connect people, faces, media, and event evidence.",
            "+ Preserve uncertainty and missing-source notes.",
        ]
    else:
        intent = "Review this file as a likely touch point for the requested development task."
        edit_type = "inspection"
        preview = [
            f"@@ {path}",
            "+ Inspect current implementation before drafting exact hunks.",
            "+ Keep the final edit scoped to the requested capability.",
        ]
    return {
        "path": path,
        "edit_type": edit_type,
        "intent": intent,
        "preview_kind": "pseudo_diff",
        "preview_lines": preview,
        "applies_cleanly": None,
    }


def draft_comment_for_path(path: str, task: str) -> str:
    message = f"Draft intent: {task}"
    if path.endswith(".py"):
        return f"# {message}"
    if path.endswith(".js") or path.endswith(".css"):
        return f"// {message}"
    if path.endswith(".html") or path.endswith(".md"):
        return f"<!-- {message} -->"
    return message


def exact_diff_anchor_patterns(path: str) -> list[str]:
    normalized = path.replace("\\", "/")
    if path.endswith("app/main.py"):
        return ["def handle_runtime_chat_tool", "def admin_health_check_payload", "from app.admin_patch_service import"]
    if path.endswith("app/admin_patch_service.py"):
        return ["def admin_patch_proposal_payload", "def admin_apply_readiness_payload", "PATCH_SNAPSHOT_ROOT"]
    if path.endswith("app/fauxdex.py"):
        return ["ENGINE_CONTEXT_FILES = [", "def archivist_engine_context", "def plan_fauxdex_engine_task"]
    if "app/fauxdex_engine/" in normalized:
        return ["ENGINE_PLAN_SCHEMA", "def plan_fauxdex_engine_task", "def structured_plan", "Engine rules:"]
    if path.endswith("web/index.html"):
        return ["data-card-id=\"intelligent-admin\"", "admin-quick-actions", "adminEngineToolList"]
    if path.endswith("web/app.js"):
        return ["function renderPatchProposalDetail", "function renderSpecialActionDetail", "async function sendAdminEngine"]
    if path.endswith("web/styles.css"):
        return [".fauxdex-preview-code", ".admin-engine-tools", ".fauxdex-detail-section"]
    if path.endswith("docs/ACTION_AUDIT_CONTRACTS.md"):
        return ["### `admin.patch_proposal`", "## Intelligent Admin Contracts"]
    if path.endswith("docs/ROADMAP.md"):
        return ["### Chat Tools And Fauxdex", "Add pseudo-diff preview blocks"]
    if path.endswith("docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md"):
        return ["Current self-development boundary", "Fauxdex Engine"]
    return []


def exact_diff_draft_for_file(path: str, task: str, fallback: dict) -> dict:
    rel_path = Path(path)
    result = {
        **fallback,
        "preview_kind": "exact_draft",
        "generated_from_current_file": False,
        "anchor_line": None,
        "applies_cleanly": False,
    }
    if not rel_path.exists() or not rel_path.is_file():
        result["preview_lines"] = [
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ file missing in current workspace @@",
            f"+ {draft_comment_for_path(path, task)}",
        ]
        return result
    try:
        lines = rel_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as error:
        result["preview_lines"] = [
            f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ unable to read file: {error} @@",
        ]
        return result
    anchor_index = 0
    patterns = exact_diff_anchor_patterns(path)
    for pattern in patterns:
        for index, line in enumerate(lines):
            if pattern in line:
                anchor_index = index
                break
        else:
            continue
        break
    start = max(0, anchor_index - 2)
    end = min(len(lines), anchor_index + 3)
    context = lines[start:end] or [""]
    insert = draft_comment_for_path(path, task)
    hunk = [
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -{start + 1},{len(context)} +{start + 1},{len(context) + 1} @@",
    ]
    hunk.extend(f" {line}" for line in context)
    hunk.append(f"+{insert}")
    result.update(
        {
            "preview_lines": hunk,
            "generated_from_current_file": True,
            "anchor_line": anchor_index + 1,
            "anchor_text": lines[anchor_index] if lines else "",
            "draft_note": "This is an exact, current-file-anchored draft hunk for review. It is not an apply-ready patch.",
        }
    )
    return result


def extract_unified_diff_text(text: str) -> str:
    raw = text or ""
    fenced = re.findall(r"```(?:diff|patch)?\s*\n(.*?)```", raw, flags=re.I | re.S)
    for block in fenced:
        if "\n@@ " in f"\n{block}" and "\n--- " in f"\n{block}" and "\n+++ " in f"\n{block}":
            return block.strip()
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- "):
            candidate = "\n".join(lines[index:]).strip()
            if "\n@@ " in f"\n{candidate}" and "\n--- " in f"\n{candidate}" and "\n+++ " in f"\n{candidate}":
                return candidate
    return ""


def _clean_diff_path(raw_path: str) -> str:
    path = (raw_path or "").strip().split("\t", 1)[0].strip()
    if path in {"", "/dev/null"}:
        raise ValueError("New and deleted files are not supported by this apply milestone.")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    normalized = path.replace("\\", "/").strip("/")
    candidate = Path(normalized)
    if candidate.is_absolute() or candidate.drive or any(part in {"", ".."} for part in candidate.parts):
        raise ValueError(f"Unsafe diff path: {raw_path}")
    if normalized not in PATCH_ALLOWED_ROOT_FILES and not normalized.startswith(PATCH_ALLOWED_ROOTS):
        raise ValueError(f"Diff path is outside allowed project roots: {normalized}")
    return normalized


def parse_unified_diff(diff_text: str) -> dict:
    lines = (diff_text or "").splitlines()
    files = []
    errors = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git ") or line.startswith("index ") or line.startswith("new file mode ") or line.startswith("deleted file mode "):
            index += 1
            continue
        if not line.startswith("--- "):
            index += 1
            continue
        try:
            old_path = _clean_diff_path(line[4:])
        except ValueError as error:
            errors.append(str(error))
            index += 1
            continue
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            errors.append(f"Missing +++ path after {old_path}.")
            continue
        try:
            new_path = _clean_diff_path(lines[index][4:])
        except ValueError as error:
            errors.append(str(error))
            index += 1
            continue
        if old_path != new_path:
            errors.append(f"Renames are not supported by this apply milestone: {old_path} -> {new_path}.")
        file_patch = {"path": new_path, "old_path": old_path, "hunks": []}
        index += 1
        while index < len(lines):
            hunk_header = lines[index]
            if hunk_header.startswith("--- ") or hunk_header.startswith("diff --git "):
                break
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", hunk_header)
            if not match:
                index += 1
                continue
            hunk = {
                "old_start": int(match.group(1)),
                "old_count": int(match.group(2) or "1"),
                "new_start": int(match.group(3)),
                "new_count": int(match.group(4) or "1"),
                "lines": [],
                "header": hunk_header,
            }
            index += 1
            while index < len(lines):
                hunk_line = lines[index]
                if hunk_line.startswith(("--- ", "diff --git ")) or re.match(r"^@@ -\d+", hunk_line):
                    break
                if hunk_line.startswith("\\ No newline"):
                    index += 1
                    continue
                if not hunk_line.startswith((" ", "+", "-")):
                    errors.append(f"Unsupported hunk line in {new_path}: {hunk_line[:80]}")
                    index += 1
                    continue
                hunk["lines"].append({"op": hunk_line[:1], "text": hunk_line[1:]})
                index += 1
            file_patch["hunks"].append(hunk)
        files.append(file_patch)
    if not files and not errors:
        errors.append("No unified diff file sections found.")
    return {"files": files, "errors": errors}


def _line_counts_for_hunk(hunk: dict) -> tuple[int, int]:
    old_count = sum(1 for item in hunk.get("lines") or [] if item.get("op") in {" ", "-"})
    new_count = sum(1 for item in hunk.get("lines") or [] if item.get("op") in {" ", "+"})
    return old_count, new_count


def _validate_file_hunks(file_patch: dict, workspace_root: Path) -> dict:
    rel_path = file_patch.get("path") or ""
    src = (workspace_root / rel_path).resolve(strict=False)
    result = {"path": rel_path, "ok": False, "reason": "", "hunks": []}
    if src != workspace_root and not path_is_inside(src, workspace_root):
        result["reason"] = "Path is outside workspace."
        return result
    if not src.exists() or not src.is_file():
        result["reason"] = "Only existing files can be patched by this apply milestone."
        return result
    try:
        current_lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as error:
        result["reason"] = f"Unable to read file: {error}"
        return result
    for hunk in file_patch.get("hunks") or []:
        expected_old, expected_new = _line_counts_for_hunk(hunk)
        hunk_result = {
            "header": hunk.get("header"),
            "old_start": hunk.get("old_start"),
            "old_count": hunk.get("old_count"),
            "new_count": hunk.get("new_count"),
            "ok": False,
            "reason": "",
        }
        if hunk.get("old_count") != expected_old or hunk.get("new_count") != expected_new:
            hunk_result["reason"] = "Hunk line counts do not match the header."
            result["hunks"].append(hunk_result)
            continue
        start = int(hunk.get("old_start") or 1) - 1
        old_lines = [item["text"] for item in hunk.get("lines") or [] if item.get("op") in {" ", "-"}]
        window = current_lines[start : start + len(old_lines)]
        if start < 0 or window != old_lines:
            hunk_result["reason"] = "Current file content does not exactly match hunk context."
            result["hunks"].append(hunk_result)
            continue
        hunk_result["ok"] = True
        hunk_result["reason"] = "Hunk matches current file exactly."
        result["hunks"].append(hunk_result)
    result["ok"] = bool(result["hunks"]) and all(item.get("ok") for item in result["hunks"])
    result["reason"] = "All hunks match current file exactly." if result["ok"] else "One or more hunks failed validation."
    return result


def validate_unified_diff_text(diff_text: str, workspace_root: Path | None = None) -> dict:
    root = workspace_root or Path.cwd().resolve(strict=False)
    parsed = parse_unified_diff(diff_text)
    validations = [_validate_file_hunks(file_patch, root) for file_patch in parsed.get("files") or []]
    errors = list(parsed.get("errors") or [])
    ok = bool(validations) and not errors and all(item.get("ok") for item in validations)
    return {
        "ok": ok,
        "validation_kind": "unified_diff",
        "files": [item.get("path") for item in parsed.get("files") or []],
        "validations": validations,
        "errors": errors,
        "parsed": parsed,
    }


def _apply_file_hunks(file_patch: dict, workspace_root: Path) -> dict:
    rel_path = file_patch.get("path") or ""
    src = (workspace_root / rel_path).resolve(strict=False)
    before_hash = sha256_file(src)
    raw_text = src.read_text(encoding="utf-8", errors="ignore")
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    had_trailing_newline = raw_text.endswith(("\n", "\r\n"))
    lines = raw_text.splitlines()
    offset = 0
    for hunk in file_patch.get("hunks") or []:
        start = int(hunk.get("old_start") or 1) - 1 + offset
        old_lines = [item["text"] for item in hunk.get("lines") or [] if item.get("op") in {" ", "-"}]
        new_lines = [item["text"] for item in hunk.get("lines") or [] if item.get("op") in {" ", "+"}]
        lines[start : start + len(old_lines)] = new_lines
        offset += len(new_lines) - len(old_lines)
    output = newline.join(lines)
    if had_trailing_newline:
        output += newline
    src.write_text(output, encoding="utf-8")
    return {
        "path": rel_path,
        "before_sha256": before_hash,
        "after_sha256": sha256_file(src),
        "hunks_applied": len(file_patch.get("hunks") or []),
    }


def apply_unified_diff_text(diff_text: str, workspace_root: Path | None = None) -> dict:
    root = workspace_root or Path.cwd().resolve(strict=False)
    validation = validate_unified_diff_text(diff_text, root)
    if not validation.get("ok"):
        return {"applied": False, "validation": validation, "files": [], "error": "Unified diff did not validate."}
    files = [_apply_file_hunks(file_patch, root) for file_patch in validation.get("parsed", {}).get("files") or []]
    return {"applied": True, "validation": validation, "files": files, "error": ""}


def unified_diff_preview_blocks(diff_text: str) -> list[dict]:
    validation = validate_unified_diff_text(diff_text)
    parsed_files = {item.get("path"): item for item in validation.get("parsed", {}).get("files") or []}
    validation_by_path = {item.get("path"): item for item in validation.get("validations") or []}
    blocks = []
    for path, file_patch in parsed_files.items():
        validation_item = validation_by_path.get(path) or {}
        blocks.append(
            {
                "path": path,
                "edit_type": "unified_diff",
                "intent": "Apply exact unified diff hunks after validation, snapshot, and confirmation.",
                "preview_kind": "unified_diff",
                "hunks": len(file_patch.get("hunks") or []),
                "applies_cleanly": bool(validation_item.get("ok")),
                "reason": validation_item.get("reason", ""),
            }
        )
    return blocks


def admin_unified_diff_proposal_payload(query: str) -> dict:
    diff_text = extract_unified_diff_text(query)
    validation = validate_unified_diff_text(diff_text) if diff_text else {
        "ok": False,
        "files": [],
        "validations": [],
        "errors": ["No unified diff block found."],
    }
    affected = validation.get("files") or []
    return {
        "task": clean_patch_task(query.split("```", 1)[0] if "```" in query else "Stage unified diff patch"),
        "capability_level": "proposal_with_apply_ready_unified_diff" if validation.get("ok") else "proposal_with_invalid_unified_diff",
        "affected_files": affected,
        "diff_preview": unified_diff_preview_blocks(diff_text) if diff_text else [],
        "diff_preview_kind": "unified_diff",
        "diff_text": diff_text,
        "unified_diff_validation": validation,
        "safety_gates": [
            "Unified diff must validate exactly against current files.",
            "Affected files must be snapshotted before apply.",
            "Apply requires a separate pending confirmation action.",
            "Post-apply verification must run and be logged.",
            "Rollback must use the snapshot manifest if verification fails.",
        ],
        "implementation_steps": [
            "Validate unified diff against current files.",
            "Snapshot affected files.",
            "Request apply readiness.",
            "Create a confirmation-gated apply action.",
            "Confirm apply, then run fixed verification.",
        ],
        "verification": [
            "Unified diff validation passes.",
            "Patch snapshot exists for affected files.",
            "Post-apply `node --check web\\app.js` and Python compileall pass.",
        ],
        "rollback": [
            "Restore touched files from the patch snapshot manifest.",
            "Re-run fixed verification after restore.",
        ],
        "handoff": "This proposal can be applied by Intelligent Admin only after validation, snapshot, readiness, and confirmation all pass.",
    }


def admin_patch_proposal_payload(task: str) -> dict:
    clean_task = clean_patch_task(task)
    files = infer_development_files(clean_task)
    preview_blocks = [exact_diff_draft_for_file(path, clean_task, patch_preview_for_file(path, clean_task)) for path in files]
    return {
        "task": clean_task,
        "capability_level": "proposal_with_exact_diff_drafts",
        "affected_files": files,
        "diff_preview": preview_blocks,
        "diff_preview_kind": "exact_draft",
        "safety_gates": [
            "No source files are edited by this action.",
            "Codex reviews the proposal and inspects current files before editing.",
            "Exact draft hunks are anchored to current file text, but are still not apply-ready patches.",
            "Any future in-app apply path must validate exact unified diffs before confirmation.",
            "Verification commands must run after implementation.",
        ],
        "implementation_steps": [
            "Inspect the listed files and current action contracts.",
            "Implement the smallest useful backend contract first.",
            "Expose the tool in the Intelligent Admin catalog and quick actions.",
            "Update API/action-contract/roadmap docs in the same pass.",
            "Run syntax checks and targeted API smoke tests.",
        ],
        "verification": [
            "node --check web\\app.js",
            ".venv\\Scripts\\python.exe -m compileall app run_server.py run_index.py",
            "FastAPI TestClient smoke test for any new endpoint or runtime phrase.",
        ],
        "rollback": [
            "Revert only the touched files from the patch if verification fails.",
            "Cancel the audit action if the proposal is no longer wanted.",
            "Keep database migrations additive until a tested rollback exists.",
        ],
        "handoff": "Codex should implement this proposal from the shared workspace, then report changed files and verification results.",
    }


def parse_validation_action_id(query: str, conversation_id: str) -> int | None:
    match = re.search(r"(?:action|proposal)\s+#?(\d+)", query, re.I)
    if match:
        return int(match.group(1))
    action = latest_pending_action(conversation_id)
    if action and action.get("tool") == "admin.patch_proposal":
        return int(action["id"])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM action_audit
        WHERE tool = 'admin.patch_proposal'
        ORDER BY created_ts DESC, id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return int(row["id"]) if row else None


def validate_draft_block(block: dict) -> dict:
    path = str(block.get("path") or "")
    preview_lines = block.get("preview_lines") or []
    result = {
        "path": path,
        "ok": False,
        "anchor_line": block.get("anchor_line"),
        "generated_from_current_file": bool(block.get("generated_from_current_file")),
        "reason": "",
    }
    if block.get("preview_kind") != "exact_draft":
        result["reason"] = "Preview block is not an exact draft hunk."
        return result
    rel_path = Path(path)
    if not rel_path.exists() or not rel_path.is_file():
        result["reason"] = "File does not exist."
        return result
    try:
        current_lines = rel_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as error:
        result["reason"] = f"Unable to read file: {error}"
        return result
    context_lines = [line[1:] for line in preview_lines if line.startswith(" ") and not line.startswith(" +++")]
    if not context_lines:
        result["reason"] = "No context lines found in draft hunk."
        return result
    anchor_line = block.get("anchor_line")
    if isinstance(anchor_line, int) and anchor_line > 0:
        start = max(0, anchor_line - 3)
        end = min(len(current_lines), start + len(context_lines) + 4)
        window = current_lines[start:end]
    else:
        window = current_lines
    joined_context = "\n".join(context_lines)
    joined_window = "\n".join(window)
    joined_file = "\n".join(current_lines)
    if joined_context in joined_window or joined_context in joined_file:
        result["ok"] = True
        result["reason"] = "Context matched current file."
    else:
        result["reason"] = "Context no longer matches current file."
    return result


def admin_diff_validation_payload(query: str, conversation_id: str) -> dict:
    action_id = parse_validation_action_id(query, conversation_id)
    if not action_id:
        return {"ok": False, "action_id": None, "error": "No patch proposal action found to validate.", "validations": []}
    action = load_action(action_id)
    if not action:
        return {"ok": False, "action_id": action_id, "error": "Patch proposal action not found.", "validations": []}
    if action.get("tool") != "admin.patch_proposal":
        return {"ok": False, "action_id": action_id, "error": "Action is not an Admin patch proposal.", "validations": []}
    action_result = action.get("result") or {}
    if action_result.get("diff_preview_kind") == "unified_diff":
        validation = validate_unified_diff_text(action_result.get("diff_text") or "")
        return {
            "ok": bool(validation.get("ok")),
            "action_id": action_id,
            "validated_tool": action.get("tool"),
            "validation_kind": "unified_diff",
            "validations": validation.get("validations") or [],
            "errors": validation.get("errors") or [],
            "error": "" if validation.get("ok") else "; ".join(validation.get("errors") or ["Unified diff did not validate."]),
        }
    blocks = action_result.get("diff_preview") or []
    validations = [validate_draft_block(block) for block in blocks]
    return {
        "ok": bool(validations) and all(item.get("ok") for item in validations),
        "action_id": action_id,
        "validated_tool": action.get("tool"),
        "validation_kind": "exact_draft",
        "validations": validations,
        "error": "" if validations else "Patch proposal has no draft hunks to validate.",
    }


def format_admin_diff_validation(payload: dict) -> str:
    action_id = payload.get("action_id")
    if payload.get("error"):
        return f"Diff validation: {payload.get('error')}"
    lines = [
        f"Diff validation for action #{action_id}:",
        f"- Overall: {'passed' if payload.get('ok') else 'failed'}.",
    ]
    for item in payload.get("validations") or []:
        status = "passed" if item.get("ok") else "failed"
        anchor = f" line {item.get('anchor_line')}" if item.get("anchor_line") else ""
        lines.append(f"- {item.get('path')}{anchor}: {status} - {item.get('reason')}")
    return "\n".join(lines)


def latest_action_by_tool(tool: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM action_audit
        WHERE tool = ?
        ORDER BY created_ts DESC, id DESC
        LIMIT 1
        """,
        (tool,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["params"] = json.loads(item.get("params_json") or "{}")
    item["result"] = json.loads(item.get("result_json") or "{}")
    return item


def latest_validation_for_proposal(proposal_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM action_audit
        WHERE tool = 'admin.diff_validation'
        ORDER BY created_ts DESC, id DESC
        LIMIT 25
        """
    )
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        item["params"] = json.loads(item.get("params_json") or "{}")
        item["result"] = json.loads(item.get("result_json") or "{}")
        if int((item.get("result") or {}).get("action_id") or 0) == proposal_id:
            return item
    return None


def latest_snapshot_for_proposal(proposal_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM action_audit
        WHERE tool = 'admin.patch_snapshot'
        ORDER BY created_ts DESC, id DESC
        LIMIT 25
        """
    )
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        item["params"] = json.loads(item.get("params_json") or "{}")
        item["result"] = json.loads(item.get("result_json") or "{}")
        if int((item.get("result") or {}).get("proposal_action_id") or 0) == proposal_id:
            return item
    return None


def latest_apply_action() -> dict | None:
    return latest_action_by_tool("admin.patch_apply")


def _load_snapshot_manifest_from_payload(snapshot_payload: dict) -> dict:
    manifest_path_text = str(snapshot_payload.get("manifest_path") or "").strip()
    snapshot_dir_text = str(snapshot_payload.get("snapshot_dir") or "").strip()
    if not manifest_path_text and snapshot_dir_text:
        manifest_path_text = str(Path(snapshot_dir_text) / "manifest.json")
    if not manifest_path_text:
        raise ValueError("Snapshot manifest path is missing.")
    manifest_path = Path(manifest_path_text).resolve(strict=False)
    root = PATCH_SNAPSHOT_ROOT.resolve(strict=False)
    if manifest_path != root and not path_is_inside(manifest_path, root):
        raise ValueError("Snapshot manifest is outside the Admin patch snapshot root.")
    if not manifest_path.exists() or not manifest_path.is_file():
        raise ValueError("Snapshot manifest file was not found.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Snapshot manifest is not valid JSON: {error}") from error
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _snapshot_action_from_any_action(action: dict | None) -> dict | None:
    if not action:
        return None
    if action.get("tool") == "admin.patch_snapshot":
        return action
    if action.get("tool") == "admin.patch_proposal":
        return latest_snapshot_for_proposal(int(action.get("id") or 0))
    if action.get("tool") == "admin.patch_apply":
        result = action.get("result") or {}
        readiness = result.get("readiness") or {}
        snapshot_id = readiness.get("snapshot_action_id")
        if snapshot_id:
            snapshot = load_action(int(snapshot_id))
            if snapshot and snapshot.get("tool") == "admin.patch_snapshot":
                return snapshot
        proposal_id = result.get("proposal_action_id")
        if proposal_id:
            return latest_snapshot_for_proposal(int(proposal_id))
    return None


def parse_rollback_snapshot_action_id(query: str, conversation_id: str) -> tuple[int | None, str]:
    match = re.search(r"(?:snapshot|action|apply|proposal)\s+#?(\d+)", query, re.I)
    if match:
        action = load_action(int(match.group(1)))
        snapshot = _snapshot_action_from_any_action(action)
        return (int(snapshot["id"]), f"Resolved from action #{match.group(1)}.") if snapshot else (None, "Referenced action has no related patch snapshot.")
    pending = latest_pending_action(conversation_id)
    snapshot = _snapshot_action_from_any_action(pending)
    if snapshot:
        return int(snapshot["id"]), "Resolved from latest pending action."
    apply_action = latest_apply_action()
    snapshot = _snapshot_action_from_any_action(apply_action)
    if snapshot:
        return int(snapshot["id"]), "Resolved from latest patch apply action."
    snapshot = latest_action_by_tool("admin.patch_snapshot")
    if snapshot:
        return int(snapshot["id"]), "Resolved from latest patch snapshot action."
    return None, "No patch snapshot action found."


def _rollback_preview_for_file(file_item: dict, workspace_root: Path, snapshot_root: Path) -> dict:
    rel_path = str(file_item.get("path") or "").replace("\\", "/").strip("/")
    snapshot_path = Path(str(file_item.get("snapshot_path") or "")).resolve(strict=False)
    dest = (workspace_root / rel_path).resolve(strict=False)
    item = {
        "path": rel_path,
        "snapshot_path": str(snapshot_path),
        "ok": False,
        "reason": "",
        "current_sha256": None,
        "snapshot_sha256": None,
        "expected_snapshot_sha256": file_item.get("sha256"),
        "will_restore": False,
    }
    try:
        _clean_diff_path(rel_path)
    except ValueError as error:
        item["reason"] = str(error)
        return item
    if snapshot_path != snapshot_root and not path_is_inside(snapshot_path, snapshot_root):
        item["reason"] = "Snapshot file is outside the selected snapshot directory."
        return item
    if dest != workspace_root and not path_is_inside(dest, workspace_root):
        item["reason"] = "Destination is outside the workspace."
        return item
    if not snapshot_path.exists() or not snapshot_path.is_file():
        item["reason"] = "Snapshot file is missing."
        return item
    if not dest.exists() or not dest.is_file():
        item["reason"] = "Destination file is missing; rollback currently restores existing files only."
        return item
    snapshot_hash = sha256_file(snapshot_path)
    current_hash = sha256_file(dest)
    item["snapshot_sha256"] = snapshot_hash
    item["current_sha256"] = current_hash
    if item["expected_snapshot_sha256"] and item["expected_snapshot_sha256"] != snapshot_hash:
        item["reason"] = "Snapshot file hash does not match manifest."
        return item
    item["ok"] = True
    item["will_restore"] = current_hash != snapshot_hash
    item["reason"] = "Ready to restore from snapshot." if item["will_restore"] else "Current file already matches snapshot."
    return item


def admin_patch_rollback_payload(query: str, conversation_id: str) -> dict:
    snapshot_action_id, resolution = parse_rollback_snapshot_action_id(query, conversation_id)
    if not snapshot_action_id:
        return {
            "ready_to_rollback": False,
            "snapshot_action_id": None,
            "resolution": resolution,
            "files": [],
            "blockers": [resolution],
            "warnings": [],
        }
    snapshot_action = load_action(snapshot_action_id)
    if not snapshot_action or snapshot_action.get("tool") != "admin.patch_snapshot":
        return {
            "ready_to_rollback": False,
            "snapshot_action_id": snapshot_action_id,
            "resolution": "Resolved action is not a patch snapshot.",
            "files": [],
            "blockers": ["Resolved action is not a patch snapshot."],
            "warnings": [],
        }
    try:
        manifest = _load_snapshot_manifest_from_payload(snapshot_action.get("result") or {})
    except ValueError as error:
        return {
            "ready_to_rollback": False,
            "snapshot_action_id": snapshot_action_id,
            "resolution": resolution,
            "files": [],
            "blockers": [str(error)],
            "warnings": [],
        }
    workspace_root = Path.cwd().resolve(strict=False)
    snapshot_dir = Path(str(manifest.get("snapshot_dir") or "")).resolve(strict=False)
    snapshot_root = PATCH_SNAPSHOT_ROOT.resolve(strict=False)
    blockers = []
    if snapshot_dir != snapshot_root and not path_is_inside(snapshot_dir, snapshot_root):
        blockers.append("Snapshot directory is outside the Admin patch snapshot root.")
    files = [_rollback_preview_for_file(item, workspace_root, snapshot_dir) for item in manifest.get("files") or []]
    if not files:
        blockers.append("Snapshot manifest has no files.")
    failed = [item for item in files if not item.get("ok")]
    if failed:
        blockers.append("One or more snapshot files cannot be restored safely.")
    changed = [item for item in files if item.get("will_restore")]
    warnings = []
    if files and not changed and not failed:
        warnings.append("All current files already match the snapshot.")
    ready = bool(files) and not blockers
    return {
        "ready_to_rollback": ready,
        "snapshot_action_id": snapshot_action_id,
        "proposal_action_id": manifest.get("proposal_action_id"),
        "resolution": resolution,
        "manifest_path": manifest.get("manifest_path"),
        "snapshot_dir": manifest.get("snapshot_dir"),
        "files": files,
        "restore_count": len(changed),
        "blockers": blockers,
        "warnings": warnings,
        "safeguards": [
            "No files are restored until this rollback action is confirmed.",
            "Only files listed in the snapshot manifest are eligible.",
            "Snapshot hashes are checked before restore.",
            "Destinations must stay inside allowed project roots.",
            "Fixed verification checks run after restore.",
        ],
    }


def execute_admin_patch_rollback_action(action: dict) -> dict:
    result = action.get("result") or {}
    if action.get("tool") != "admin.patch_rollback":
        return {"rolled_back": False, "error": "Action is not an Admin patch rollback action.", "files": []}
    if not result.get("ready_to_rollback"):
        return {"rolled_back": False, "error": "Rollback action is not marked ready.", "files": []}
    snapshot_action = load_action(int(result.get("snapshot_action_id") or 0))
    if not snapshot_action or snapshot_action.get("tool") != "admin.patch_snapshot":
        return {"rolled_back": False, "error": "Snapshot action not found.", "files": []}
    try:
        manifest = _load_snapshot_manifest_from_payload(snapshot_action.get("result") or {})
    except ValueError as error:
        return {"rolled_back": False, "error": str(error), "files": []}
    workspace_root = Path.cwd().resolve(strict=False)
    snapshot_dir = Path(str(manifest.get("snapshot_dir") or "")).resolve(strict=False)
    preview = [_rollback_preview_for_file(item, workspace_root, snapshot_dir) for item in manifest.get("files") or []]
    if not preview or any(not item.get("ok") for item in preview):
        return {"rolled_back": False, "error": "Rollback preview no longer validates.", "files": preview}
    restored = []
    for item in preview:
        if not item.get("will_restore"):
            restored.append({**item, "restored": False, "reason": "Already matched snapshot."})
            continue
        src = Path(item["snapshot_path"]).resolve(strict=False)
        dest = (workspace_root / item["path"]).resolve(strict=False)
        shutil.copy2(src, dest)
        restored.append({**item, "restored": True, "restored_sha256": sha256_file(dest)})
    return {
        "rolled_back": True,
        "snapshot_action_id": result.get("snapshot_action_id"),
        "proposal_action_id": result.get("proposal_action_id"),
        "files": restored,
        "restored_count": sum(1 for item in restored if item.get("restored")),
        "error": "",
    }


def format_admin_patch_rollback(payload: dict) -> str:
    lines = [
        f"Patch rollback for snapshot #{payload.get('snapshot_action_id') or 'n/a'}:",
        f"- Ready to rollback: {'yes' if payload.get('ready_to_rollback') else 'no'}.",
    ]
    if payload.get("resolution"):
        lines.append(f"- Resolution: {payload.get('resolution')}")
    if payload.get("manifest_path"):
        lines.append(f"- Manifest: {payload.get('manifest_path')}")
    if payload.get("restore_count") is not None:
        lines.append(f"- Files that would be restored: {payload.get('restore_count')}")
    if payload.get("blockers"):
        lines.append("- Blockers:")
        lines.extend(f"  - {item}" for item in payload.get("blockers") or [])
    if payload.get("warnings"):
        lines.append("- Warnings:")
        lines.extend(f"  - {item}" for item in payload.get("warnings") or [])
    files = payload.get("files") or []
    if files:
        lines.append("- Files:")
        for item in files[:8]:
            lines.append(f"  - {item.get('path')}: {item.get('reason')}")
    rollback_result = payload.get("rollback_result") or {}
    if rollback_result:
        lines.append(f"- Rollback result: {'restored' if rollback_result.get('rolled_back') else 'not restored'}.")
        if rollback_result.get("error"):
            lines.append(f"- Error: {rollback_result.get('error')}")
        for item in rollback_result.get("files") or []:
            lines.append(f"  - {item.get('path')}: {'restored' if item.get('restored') else item.get('reason')}")
    verification = payload.get("post_rollback_verification") or {}
    if verification:
        lines.append(f"- Post-rollback verification: {'passed' if verification.get('ok') else 'failed'}.")
    return "\n".join(lines)


def parse_readiness_action_id(query: str, conversation_id: str) -> int | None:
    match = re.search(r"(?:action|proposal)\s+#?(\d+)", query, re.I)
    if match:
        return int(match.group(1))
    action = latest_pending_action(conversation_id)
    if action and action.get("tool") == "admin.patch_proposal":
        return int(action["id"])
    action = latest_action_by_tool("admin.patch_proposal")
    return int(action["id"]) if action else None


def admin_apply_readiness_payload(query: str, conversation_id: str) -> dict:
    proposal_id = parse_readiness_action_id(query, conversation_id)
    gates = []
    blockers = []
    warnings = []
    if not proposal_id:
        return {"ready": False, "proposal_action_id": None, "gates": [], "blockers": ["No patch proposal found."], "warnings": []}
    proposal = load_action(proposal_id)
    if not proposal or proposal.get("tool") != "admin.patch_proposal":
        return {"ready": False, "proposal_action_id": proposal_id, "gates": [], "blockers": ["Action is not an Admin patch proposal."], "warnings": []}
    result = proposal.get("result") or {}
    has_hunks = bool(result.get("diff_preview"))
    validation_label = "Unified diff validated" if result.get("diff_preview_kind") == "unified_diff" else "Draft hunks validated"
    gates.append({"name": "Patch proposal exists", "ok": True, "detail": f"Action #{proposal_id} found."})
    gates.append({"name": "Patch hunks present", "ok": has_hunks, "detail": f"{len(result.get('diff_preview') or [])} hunk(s)."})
    if not has_hunks:
        blockers.append("Patch proposal has no draft hunks.")
    validation = latest_validation_for_proposal(proposal_id)
    validation_ok = bool(validation and (validation.get("result") or {}).get("ok"))
    gates.append({
        "name": validation_label,
        "ok": validation_ok,
        "detail": f"Validation action #{validation['id']} passed." if validation_ok else "No passing validation action found.",
    })
    if not validation_ok:
        blockers.append("Run diff validation for this proposal before any apply step.")
    verification = latest_action_by_tool("admin.verification_checks")
    verification_ok = bool(verification and (verification.get("result") or {}).get("ok"))
    gates.append({
        "name": "Verification checks passed",
        "ok": verification_ok,
        "detail": f"Verification action #{verification['id']} passed." if verification_ok else "No passing verification check action found.",
    })
    if not verification_ok:
        warnings.append("Run fixed verification checks before implementation and again after any future apply.")
    snapshot = latest_snapshot_for_proposal(proposal_id)
    snapshot_ok = bool(snapshot and (snapshot.get("result") or {}).get("ok"))
    gates.append({
        "name": "Affected files snapshotted",
        "ok": snapshot_ok,
        "detail": f"Snapshot action #{snapshot['id']} captured current files." if snapshot_ok else "No successful patch snapshot found.",
    })
    if not snapshot_ok:
        blockers.append("Create a patch snapshot before any future apply step.")
    applyable_diff = result.get("diff_preview_kind") == "unified_diff" and all(
        block.get("preview_kind") == "unified_diff" for block in result.get("diff_preview") or []
    )
    gates.append({"name": "Apply request tool exists", "ok": True, "detail": "Apply requests are routed through a guarded audit tool."})
    gates.append({
        "name": "Apply-ready unified diffs",
        "ok": applyable_diff,
        "detail": "Proposal contains unified diffs." if applyable_diff else "Proposal contains review drafts, not apply-ready unified diffs.",
    })
    if not applyable_diff:
        blockers.append("Current proposal cannot be applied because it does not contain apply-ready unified diffs.")
    ready = not blockers and applyable_diff and validation_ok and snapshot_ok
    return {
        "ready": ready,
        "proposal_action_id": proposal_id,
        "proposal_status": proposal.get("status"),
        "validation_action_id": validation.get("id") if validation else None,
        "verification_action_id": verification.get("id") if verification else None,
        "snapshot_action_id": snapshot.get("id") if snapshot else None,
        "gates": gates,
        "blockers": blockers,
        "warnings": warnings,
        "next_step": "Create confirmation-gated apply action." if ready else "Resolve blockers, then rerun apply readiness.",
    }


def format_admin_apply_readiness(payload: dict) -> str:
    lines = [
        f"Apply readiness for proposal #{payload.get('proposal_action_id') or 'n/a'}:",
        f"- Ready to apply: {'yes' if payload.get('ready') else 'no'}.",
    ]
    if payload.get("gates"):
        lines.append("- Gates:")
        for gate in payload.get("gates") or []:
            lines.append(f"  - {'pass' if gate.get('ok') else 'block'}: {gate.get('name')} - {gate.get('detail')}")
    if payload.get("blockers"):
        lines.append("- Blockers:")
        lines.extend(f"  - {item}" for item in payload.get("blockers") or [])
    if payload.get("warnings"):
        lines.append("- Warnings:")
        lines.extend(f"  - {item}" for item in payload.get("warnings") or [])
    if payload.get("next_step"):
        lines.append(f"- Next step: {payload.get('next_step')}")
    return "\n".join(lines)


def admin_patch_apply_payload(query: str, conversation_id: str) -> dict:
    proposal_id = parse_readiness_action_id(query, conversation_id)
    readiness = admin_apply_readiness_payload(query, conversation_id)
    blockers = list(readiness.get("blockers") or [])
    if not proposal_id:
        return {
            "applied": False,
            "proposal_action_id": None,
            "blocked": True,
            "blockers": blockers or ["No patch proposal found."],
            "safeguards": ["No files were modified."],
            "readiness": readiness,
        }
    proposal = load_action(proposal_id)
    proposal_result = (proposal or {}).get("result") or {}
    diff_kind = proposal_result.get("diff_preview_kind")
    if diff_kind != "unified_diff":
        blockers.insert(0, f"Proposal #{proposal_id} has `{diff_kind or 'unknown'}` preview blocks, not apply-ready unified diffs.")
    if readiness.get("ready") and not blockers:
        return {
            "applied": False,
            "ready_to_apply": True,
            "proposal_action_id": proposal_id,
            "blocked": False,
            "requires_confirmation": True,
            "blockers": [],
            "safeguards": [
                "No source files are modified until this apply action is confirmed.",
                "Unified diff validation has passed.",
                "Affected files have a snapshot action.",
                "Fixed verification checks will run after apply.",
            ],
            "readiness": readiness,
            "negotiation": "Confirm this apply action to modify the validated files.",
        }
    return {
        "applied": False,
        "ready_to_apply": False,
        "proposal_action_id": proposal_id,
        "blocked": True,
        "blockers": blockers,
        "safeguards": [
            "No source files were modified.",
            "No shell commands were executed.",
            "The request was recorded for audit/history only.",
            "Codex remains the implementation bridge until apply-ready unified diffs and rollback snapshots exist.",
        ],
        "readiness": readiness,
        "negotiation": "Intelligent Admin can ask Codex to implement the proposal from the shared workspace; it cannot directly modify source files yet.",
    }


def format_admin_patch_apply(payload: dict) -> str:
    lines = [
        f"Apply request for proposal #{payload.get('proposal_action_id') or 'n/a'}:",
        f"- Applied: {'yes' if payload.get('applied') else 'no'}.",
        f"- Ready to apply: {'yes' if payload.get('ready_to_apply') else 'no'}.",
    ]
    if payload.get("blockers"):
        lines.append("- Blockers:")
        lines.extend(f"  - {item}" for item in payload.get("blockers") or [])
    if payload.get("safeguards"):
        lines.append("- Safeguards:")
        lines.extend(f"  - {item}" for item in payload.get("safeguards") or [])
    if payload.get("negotiation"):
        lines.append(f"- Negotiation note: {payload.get('negotiation')}")
    apply_result = payload.get("apply_result") or {}
    if apply_result:
        lines.append(f"- Apply result: {'applied' if apply_result.get('applied') else 'not applied'}.")
        for item in apply_result.get("files") or []:
            lines.append(f"  - {item.get('path')}: {item.get('hunks_applied')} hunk(s)")
    verification = payload.get("post_apply_verification") or {}
    if verification:
        lines.append(f"- Post-apply verification: {'passed' if verification.get('ok') else 'failed'}.")
    return "\n".join(lines)


def execute_admin_patch_apply_action(action: dict) -> dict:
    result = action.get("result") or {}
    if action.get("tool") != "admin.patch_apply":
        return {"applied": False, "error": "Action is not an Admin patch apply action.", "files": []}
    if not result.get("ready_to_apply"):
        return {"applied": False, "error": "Apply action is not marked ready.", "files": []}
    proposal_id = int(result.get("proposal_action_id") or 0)
    proposal = load_action(proposal_id) if proposal_id else None
    if not proposal or proposal.get("tool") != "admin.patch_proposal":
        return {"applied": False, "error": "Patch proposal action not found.", "files": []}
    proposal_result = proposal.get("result") or {}
    if proposal_result.get("diff_preview_kind") != "unified_diff":
        return {"applied": False, "error": "Patch proposal is not an apply-ready unified diff.", "files": []}
    return apply_unified_diff_text(proposal_result.get("diff_text") or "")


PATCH_SNAPSHOT_ROOT = DATA_DIR / "admin_patch_snapshots"


def admin_patch_snapshot_payload(query: str, conversation_id: str) -> dict:
    proposal_id = parse_readiness_action_id(query, conversation_id)
    if not proposal_id:
        return {"ok": False, "proposal_action_id": None, "error": "No patch proposal found.", "snapshot_dir": "", "files": []}
    proposal = load_action(proposal_id)
    if not proposal or proposal.get("tool") != "admin.patch_proposal":
        return {"ok": False, "proposal_action_id": proposal_id, "error": "Action is not an Admin patch proposal.", "snapshot_dir": "", "files": []}
    affected = (proposal.get("result") or {}).get("affected_files") or []
    if not affected:
        return {"ok": False, "proposal_action_id": proposal_id, "error": "Patch proposal has no affected files.", "snapshot_dir": "", "files": []}
    workspace_root = Path.cwd().resolve(strict=False)
    snapshot_dir = PATCH_SNAPSHOT_ROOT / f"proposal_{proposal_id}_{time.strftime('%Y%m%d_%H%M%S')}"
    files = []
    errors = []
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for rel in affected:
        rel_text = str(rel).replace("\\", "/").strip("/")
        src = (workspace_root / rel_text).resolve(strict=False)
        if src != workspace_root and not path_is_inside(src, workspace_root):
            errors.append({"path": rel_text, "error": "Path is outside workspace."})
            continue
        if not src.exists() or not src.is_file():
            errors.append({"path": rel_text, "error": "File not found."})
            continue
        dest = snapshot_dir / rel_text
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        files.append({
            "path": rel_text,
            "snapshot_path": str(dest),
            "size_bytes": dest.stat().st_size,
            "sha256": sha256_file(src),
        })
    manifest = {
        "proposal_action_id": proposal_id,
        "created_ts": time.time(),
        "snapshot_dir": str(snapshot_dir),
        "files": files,
        "errors": errors,
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "ok": bool(files) and not errors,
        "proposal_action_id": proposal_id,
        "snapshot_dir": str(snapshot_dir),
        "manifest_path": str(manifest_path),
        "files": files,
        "errors": errors,
    }


def format_admin_patch_snapshot(payload: dict) -> str:
    if payload.get("error"):
        return f"Patch snapshot: {payload.get('error')}"
    lines = [
        f"Patch snapshot for proposal #{payload.get('proposal_action_id')}:",
        f"- Result: {'completed' if payload.get('ok') else 'completed with issues'}.",
        f"- Snapshot dir: {payload.get('snapshot_dir')}",
        f"- Files copied: {len(payload.get('files') or [])}.",
    ]
    if payload.get("errors"):
        lines.append("- Issues:")
        lines.extend(f"  - {item.get('path')}: {item.get('error')}" for item in payload.get("errors") or [])
    return "\n".join(lines)


def format_admin_patch_proposal(payload: dict) -> str:
    lines = [
        "Patch proposal staged:",
        f"- Task: {payload.get('task')}",
        f"- Capability level: {payload.get('capability_level')}",
        "- Affected files:",
    ]
    lines.extend(f"  - {path}" for path in payload.get("affected_files") or [])
    if payload.get("diff_preview"):
        lines.append("- Preview blocks:")
        for block in (payload.get("diff_preview") or [])[:5]:
            lines.append(f"  - {block.get('path')}: {block.get('edit_type')} | {block.get('intent')}")
    lines.append("- Implementation steps:")
    lines.extend(f"  {index}. {step}" for index, step in enumerate(payload.get("implementation_steps") or [], start=1))
    lines.append("- Verification:")
    lines.extend(f"  - {step}" for step in payload.get("verification") or [])
    lines.append("")
    if payload.get("diff_preview_kind") == "unified_diff":
        lines.append("Confirming this action marks the unified-diff proposal ready for snapshot/readiness/apply gates; it does not apply source changes.")
    else:
        lines.append("Confirming this action only marks the proposal ready for Codex; it does not apply source changes.")
    return "\n".join(lines)


__all__ = [
    "admin_apply_readiness_payload",
    "admin_diff_validation_payload",
    "admin_patch_apply_payload",
    "admin_patch_proposal_payload",
    "admin_patch_rollback_payload",
    "admin_patch_snapshot_payload",
    "admin_unified_diff_proposal_payload",
    "execute_admin_patch_apply_action",
    "execute_admin_patch_rollback_action",
    "format_admin_apply_readiness",
    "format_admin_diff_validation",
    "format_admin_patch_apply",
    "format_admin_patch_proposal",
    "format_admin_patch_rollback",
    "format_admin_patch_snapshot",
    "validate_unified_diff_text",
]
