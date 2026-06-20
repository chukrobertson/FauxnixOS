from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config import ARCHIVE_ROOT
from app.embeddings import chat_messages
from app.extractors import extract_any
from app.persona import ARCHIVIST_SYSTEM_PROMPT
from app.utils import clean_filename

CO_WRITER_DIR = ARCHIVE_ROOT / "05-Writing" / "co-writer"
WORK_DIR = CO_WRITER_DIR / "workspace"
AUTOSAVE_DIR = WORK_DIR / "autosaves"
VERSIONS_DIR = WORK_DIR / "versions"
IMPORTS_DIR = WORK_DIR / "imports"
CURRENT_FILE = WORK_DIR / "current_draft.md"
AUTOSAVE_FILE = AUTOSAVE_DIR / "current_draft.autosave.md"
SOUL_FILE = CO_WRITER_DIR / "soul.md"
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".rtf", ".csv", ".json", ".xml", ".log", ".py", ".js", ".ts", ".tsx", ".css", ".html", ".htm", ".yaml", ".yml"}
EXTRACTABLE_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".xlsx"}
CODE_INTENT_MARKERS = (
    "script",
    "code",
    "function",
    "class ",
    "debug",
    "traceback",
    "exception",
    "python",
    "powershell",
    "javascript",
    "typescript",
    "node",
    "fastapi",
    "api",
    "sqlite",
    "sql",
    "regex",
    "pytest",
    ".venv",
    "virtualenv",
    "git",
    "css",
    "html",
)
FAST_CODE_INTENT_MARKERS = (
    "quick",
    "small",
    "tiny",
    "snippet",
    "explain",
    "what does",
    "regex",
    "one-liner",
    "config",
    "syntax",
)
HEAVY_CODE_INTENT_MARKERS = (
    "script",
    "project",
    "scaffold",
    "initialize",
    "architecture",
    "refactor",
    "app",
    "pipeline",
)
CODE_LINE_PREFIXES = (
    "def ",
    "class ",
    "function ",
    "import ",
    "from ",
    "const ",
    "let ",
    "var ",
    "export ",
    "async function",
    "public ",
    "private ",
)
STRONG_CODE_LINE_PREFIXES = (
    "def ",
    "class ",
    "function ",
    "import ",
    "const ",
    "let ",
    "var ",
    "export ",
    "async function",
)

DEFAULT_DRAFT = "# Untitled Draft\n\nStart writing here."

DEFAULT_COWRITER_SOUL = """
You are Co-writer, a local LLM writing assistant living inside the Archivist.

Your job:
- Help the user write, revise, expand, clarify, and organize text.
- Preserve the user's voice.
- Never overwrite meaning unless directly asked.
- Treat selected text as the active writing surface.
- Treat the chat box as the user's instruction.
- Use line numbers only as temporary references from the current snapshot.
- Give practical writing help, not generic encouragement.
- Prefer useful prose over explanation.
- When editing selected text, return only replacement text between:
<<<REPLACEMENT>>>
and
<<<END_REPLACEMENT>>>
- When generating a full draft preview, return the complete revised document between:
<<<REVISED_DOCUMENT>>>
and
<<<END_REVISED_DOCUMENT>>>

Style:
- Thoughtful.
- Precise.
- Grounded.
- Not over-polished.
- Not corporate.
- Not melodramatic.
""".strip()


def ensure_workspace() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_text(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return fallback


def load_soul() -> str:
    return read_text(SOUL_FILE, DEFAULT_COWRITER_SOUL)


def current_document() -> dict:
    ensure_workspace()
    if not CURRENT_FILE.exists():
        CURRENT_FILE.write_text(DEFAULT_DRAFT, encoding="utf-8")
    content = read_text(CURRENT_FILE, DEFAULT_DRAFT)
    autosave = read_text(AUTOSAVE_FILE, "")
    return {
        "content": content,
        "current_file": str(CURRENT_FILE),
        "autosave_file": str(AUTOSAVE_FILE),
        "has_autosave": bool(autosave and autosave != content),
    }


def timeline_item(path: Path, kind: str, label: str | None = None) -> dict | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return {
        "kind": kind,
        "label": label or kind.replace("_", " ").title(),
        "name": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "created_ts": stat.st_ctime,
        "modified_ts": stat.st_mtime,
    }


def document_timeline(limit: int = 80) -> dict:
    ensure_workspace()
    items: list[dict] = []
    for item in [
        timeline_item(CURRENT_FILE, "current", "Current Draft"),
        timeline_item(AUTOSAVE_FILE, "autosave", "Autosave"),
    ]:
        if item:
            items.append(item)

    for path in sorted(VERSIONS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        item = timeline_item(path, "version", "Saved Version")
        if item:
            items.append(item)

    for path in sorted(IMPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        item = timeline_item(path, "import", "Imported Document")
        if item:
            items.append(item)

    items.sort(key=lambda item: item["modified_ts"], reverse=True)
    return {
        "current_file": str(CURRENT_FILE),
        "autosave_file": str(AUTOSAVE_FILE),
        "versions_dir": str(VERSIONS_DIR),
        "imports_dir": str(IMPORTS_DIR),
        "items": items[:limit],
    }


def document_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in EXTRACTABLE_EXTENSIONS:
        raise ValueError(f"{ext or 'This file type'} is not supported by the Co-writer loader yet")
    if ext in TEXT_EXTENSIONS:
        return read_text(path, "")
    return extract_any(path)


def write_import_snapshot(source_name: str, content: str) -> Path:
    ensure_workspace()
    safe_name = clean_filename(source_name or "imported_document")
    stem = Path(safe_name).stem or "imported_document"
    path = IMPORTS_DIR / f"import_{timestamp()}_{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


def load_document_file(path: Path) -> dict:
    ensure_workspace()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    content = document_text(path)
    imported_file = write_import_snapshot(path.name, content)
    return {
        "content": content,
        "source_file": str(path),
        "imported_file": str(imported_file),
        "current_file": str(CURRENT_FILE),
        "autosave_file": str(AUTOSAVE_FILE),
    }


def import_uploaded_document(path: Path, original_name: str | None = None) -> dict:
    ensure_workspace()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    source_name = original_name or path.name
    content = document_text(path)
    imported_file = write_import_snapshot(source_name, content)
    return {
        "content": content,
        "source_name": source_name,
        "source_file": source_name,
        "imported_file": str(imported_file),
        "current_file": str(CURRENT_FILE),
        "autosave_file": str(AUTOSAVE_FILE),
    }


def save_document(content: str, autosave: bool = False) -> dict:
    ensure_workspace()
    target = AUTOSAVE_FILE if autosave else CURRENT_FILE
    target.write_text(content, encoding="utf-8")
    if not autosave:
        AUTOSAVE_FILE.write_text(content, encoding="utf-8")
    return {"saved_to": str(target), "autosave": autosave}


def save_version(content: str, prefix: str = "draft_version") -> dict:
    ensure_workspace()
    path = VERSIONS_DIR / f"{prefix}_{timestamp()}.md"
    path.write_text(content, encoding="utf-8")
    CURRENT_FILE.write_text(content, encoding="utf-8")
    AUTOSAVE_FILE.write_text(content, encoding="utf-8")
    return {"saved_to": str(path), "current_file": str(CURRENT_FILE)}


def make_numbered_snapshot(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))


def cowriter_system_prompt() -> str:
    return "\n\n".join(
        [
            ARCHIVIST_SYSTEM_PROMPT,
            "Co-writer operational layer:",
            load_soul(),
        ]
    )


def recent_history(chat_history: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for item in (chat_history or [])[-8:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content[:4000]})
    return out


def cowriter_task(document: str, instruction: str = "", selected_text: str = "") -> str:
    instruction_text = (instruction or "").lower()
    if (
        any(marker in instruction_text for marker in FAST_CODE_INTENT_MARKERS)
        and not any(marker in instruction_text for marker in HEAVY_CODE_INTENT_MARKERS)
    ):
        if looks_like_code("\n".join([selected_text or "", document or ""])) or any(
            marker in instruction_text for marker in CODE_INTENT_MARKERS
        ):
            return "cowriter_code_fast"
    if any(marker in instruction_text for marker in CODE_INTENT_MARKERS):
        return "cowriter_code"
    if looks_like_code("\n".join([selected_text or "", document or ""])):
        return "cowriter_code"
    return "cowriter"


def looks_like_code(text: str) -> bool:
    sample = (text or "")[:12000].lower()
    if "```" in sample or "<script" in sample or "<?php" in sample:
        return True
    hits = 0
    for raw_line in sample.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(STRONG_CODE_LINE_PREFIXES):
            return True
        if line.startswith(CODE_LINE_PREFIXES):
            hits += 1
        elif line.endswith("{") or line.endswith("};"):
            hits += 1
        elif (" = " in line or " := " in line) and any(char in line for char in ["(", ")", "[", "]", "{", "}", ";"]):
            hits += 1
        if hits >= 2:
            return True
    return False


def run_cowriter_chat(messages: list[dict[str, str]], task: str) -> str:
    return chat_messages(messages, task=task)


def ask(document: str, instruction: str, chat_history: list[dict[str, str]] | None = None) -> dict:
    numbered = make_numbered_snapshot(document)
    prompt = f"""
Current numbered snapshot:

{numbered}

User message:
{instruction}

Remember: line numbers refer only to this exact snapshot.
"""
    messages = [{"role": "system", "content": cowriter_system_prompt()}]
    messages.extend(recent_history(chat_history or []))
    messages.append({"role": "user", "content": prompt})
    task = cowriter_task(document, instruction)
    answer = run_cowriter_chat(messages, task)
    return {"answer": answer, "model_task": task}


def edit_selection(
    document: str,
    selected_text: str,
    instruction: str | None,
    chat_history: list[dict[str, str]] | None = None,
) -> dict:
    instruction = instruction or "Improve this selected text while preserving my voice."
    numbered = make_numbered_snapshot(document)
    prompt = f"""
Current numbered snapshot:

{numbered}

The user selected this text:

{selected_text}

Instruction:
{instruction}

Return only the replacement text between:
<<<REPLACEMENT>>>
and
<<<END_REPLACEMENT>>>

Do not include line numbers inside the replacement.
"""
    messages = [{"role": "system", "content": cowriter_system_prompt()}]
    messages.extend(recent_history(chat_history or []))
    messages.append({"role": "user", "content": prompt})
    task = cowriter_task(document, instruction, selected_text)
    answer = run_cowriter_chat(messages, task)
    replacement = extract_between(answer, "<<<REPLACEMENT>>>", "<<<END_REPLACEMENT>>>")
    return {"answer": answer, "replacement": replacement, "model_task": task}


def preview_draft(
    document: str,
    instruction: str | None,
    chat_history: list[dict[str, str]] | None = None,
) -> dict:
    instruction = instruction or "Consolidate the edits discussed in chat into a complete revised preview draft."
    numbered = make_numbered_snapshot(document)
    recent_chat = "\n\n".join(
        f"{item.get('role', '').upper()}:\n{item.get('content', '')}"
        for item in (chat_history or [])[-8:]
    )
    prompt = f"""
Current numbered snapshot:

{numbered}

Recent chat context:

{recent_chat}

User instruction:
{instruction}

Create a full revised preview draft that consolidates the relevant edits discussed in chat.

Return the complete revised document only between:
<<<REVISED_DOCUMENT>>>
and
<<<END_REVISED_DOCUMENT>>>

Do not include line numbers inside the revised document.
"""
    messages = [{"role": "system", "content": cowriter_system_prompt()}]
    messages.extend(recent_history(chat_history or []))
    messages.append({"role": "user", "content": prompt})
    task = cowriter_task(document, instruction)
    answer = run_cowriter_chat(messages, task)
    revised = extract_between(answer, "<<<REVISED_DOCUMENT>>>", "<<<END_REVISED_DOCUMENT>>>")
    result = {"answer": answer, "revised_document": revised, "model_task": task}
    if revised:
        result.update(save_version(revised, prefix="full_preview"))
    return result


def help_write(document: str, chat_history: list[dict[str, str]] | None = None) -> dict:
    tail = "\n".join(document.splitlines()[-25:])
    prompt = f"""
The user wants a small continuation.

Last part of the current draft:

{tail}

Write only 2 to 4 sentences that could continue from here.
Preserve the user's voice.
Do not explain.
"""
    messages = [{"role": "system", "content": cowriter_system_prompt()}]
    messages.extend(recent_history(chat_history or []))
    messages.append({"role": "user", "content": prompt})
    task = cowriter_task(document, "help write")
    return {"answer": run_cowriter_chat(messages, task), "model_task": task}


def extract_between(text: str, start_tag: str, end_tag: str) -> str:
    if start_tag not in text or end_tag not in text:
        return ""
    start = text.index(start_tag) + len(start_tag)
    end = text.index(end_tag, start)
    return text[start:end].strip()
