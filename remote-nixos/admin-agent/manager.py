from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from kb import (  # noqa: E402
    KB_DIR,
    MANAGER_KB,
    MODULE_DESCRIPTIONS,
    MODULE_KB_MAP,
    init_default_kbs,
    list_kbs,
    read_kb,
    write_kb,
)
from llm import LLMConfig, config_from_env, llm_completion  # noqa: E402


NIXOS_CONFIG = Path("/etc/nixos")
NIXOS_MODULES = NIXOS_CONFIG / "modules"


def _system_prompt() -> str:
    kb = read_kb(MANAGER_KB)
    modules_info = "\n".join(
        f"- `{k}` ({v})" for k, v in MODULE_DESCRIPTIONS.items()
    )
    return textwrap.dedent(f"""\
    You are the Fauxnix Admin Manager — the overseer for a set of NixOS module agents.
    Your job is to help the user manage, understand, and modify their NixOS configuration.

    ## Available modules
    {modules_info}

    ## Source of truth
    {kb}

    ## Workflow
    1. When the user asks a question, determine which modules are relevant.
    2. Load the relevant knowledge base(s) from the KB directory.
    3. Formulate a response using the KB context.
    4. If the user wants a change, suggest a specific diff and ask for confirmation.
    5. When confirming, say "APPROVED" on its own line, then describe the change.
    6. Never apply changes without explicit user approval.

    ## Rules
    - Always cite your knowledge base sources when answering.
    - If you don't know something, say so — never guess configuration options.
    - Suggest running `nixos-rebuild test` before `nixos-rebuild switch` for validation.
    - Keep responses concise but complete.
    """)


def chat(message: str, history: list[dict], cfg: LLMConfig | None = None) -> str:
    if cfg is None:
        cfg = config_from_env()
    init_default_kbs()

    # Build context from relevant KBs
    relevant_kbs = _find_relevant_kbs(message)
    kb_context = ""
    for kb_name in relevant_kbs:
        content = read_kb(kb_name)
        if content:
            kb_context += f"\n### {kb_name}\n{content}\n"

    system = _system_prompt()
    if kb_context:
        system += f"\n\n## Relevant knowledge base excerpts\n{kb_context}"

    messages = [{"role": "system", "content": system}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    return llm_completion(messages, cfg)


def _find_relevant_kbs(message: str) -> list[str]:
    msg_lower = message.lower()
    scored: list[tuple[int, str]] = []
    for module, kb_file in MODULE_KB_MAP.items():
        score = 0
        name = module.replace(".nix", "").replace("-", " ")
        if name in msg_lower:
            score += 3
        keywords = name.split()
        for kw in keywords:
            if kw in msg_lower:
                score += 1
        if score > 0:
            scored.append((score, kb_file))
    scored.sort(reverse=True)
    return [kb for _, kb in scored[:3]] if scored else list(MODULE_KB_MAP.values())[:2]


def apply_change(filepath: str, original: str, suggested: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {"ok": False, "error": f"file not found: {filepath}"}
    current = path.read_text(encoding="utf-8")
    if current == suggested:
        return {"ok": True, "applied": False, "reason": "no changes"}
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(str(path), str(backup))
    path.write_text(suggested, encoding="utf-8")
    diff = list(difflib.unified_diff(
        current.splitlines(keepends=True),
        suggested.splitlines(keepends=True),
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    ))
    return {
        "ok": True,
        "applied": True,
        "backup": str(backup),
        "diff": "".join(diff),
    }


def test_config() -> dict:
    try:
        result = subprocess.run(
            ["sudo", "nixos-rebuild", "test"],
            capture_output=True, text=True, timeout=300,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "build timed out after 5 minutes"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def rebuild_and_switch() -> dict:
    try:
        result = subprocess.run(
            ["sudo", "nixos-rebuild", "switch"],
            capture_output=True, text=True, timeout=600,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "build timed out after 10 minutes"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def update_kb(module: str, new_content: str) -> dict:
    kb_file = MODULE_KB_MAP.get(module)
    if not kb_file:
        return {"ok": False, "error": f"unknown module: {module}"}
    write_kb(kb_file, new_content)
    return {"ok": True, "kb": kb_file}


def get_kb(module: str | None) -> dict:
    if module:
        kb_file = MODULE_KB_MAP.get(module)
        if not kb_file:
            return {"ok": False, "error": f"unknown module: {module}"}
        return {"ok": True, "name": kb_file, "content": read_kb(kb_file)}
    return {"ok": True, "kbs": list_kbs()}
