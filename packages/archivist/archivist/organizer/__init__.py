from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.utils import unique_path


def add_rule(name: str, conditions: dict, target_path: str,
             action: str = "move", priority: int = 0) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    now = time.time()
    cur.execute(
        """INSERT INTO organization_rules (name, priority, conditions_json, target_path, action, enabled, created_ts, updated_ts)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (name, priority, json.dumps(conditions), str(target_path), action, now, now),
    )
    rule_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "rule_id": rule_id, "name": name}


def list_rules() -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM organization_rules ORDER BY priority DESC, id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        if r.get("conditions_json"):
            r["conditions"] = json.loads(r["conditions_json"])
    return rows


def delete_rule(rule_id: int) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM organization_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": rule_id}


def toggle_rule(rule_id: int, enabled: bool) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("UPDATE organization_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id))
    conn.commit()
    conn.close()
    return {"ok": True, "rule_id": rule_id, "enabled": enabled}


def apply_rules_to_file(file_path: str, file_id: int | None = None) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    rules = list_rules()
    ext = p.suffix.lower()
    name = p.name.lower()
    stat = p.stat()

    for rule in rules:
        if not rule.get("enabled"):
            continue
        conditions = rule.get("conditions", {})
        if _matches_conditions(name, ext, stat.st_size, conditions):
            target = Path(rule["target_path"])
            target.mkdir(parents=True, exist_ok=True)
            dest = unique_path(target / p.name)
            if rule.get("action") == "move":
                shutil.move(str(p), str(dest))
            elif rule.get("action") == "copy":
                shutil.copy2(str(p), str(dest))

            if file_id:
                conn = _get_fauxnix_conn()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO file_actions (file_id, action_type, result_json, decided_by, created_ts) VALUES (?, ?, ?, ?, ?)",
                    (file_id, "organize", json.dumps({"rule": rule["name"], "dest": str(dest)}), "rules", time.time()),
                )
                conn.commit()
                conn.close()

            return {"ok": True, "file": str(p), "dest": str(dest), "rule": rule["name"], "action": rule.get("action")}

    return {"ok": True, "file": str(p), "action": "none", "reason": "No matching rule"}


def apply_rules_to_directory(dir_path: str) -> dict:
    root = Path(dir_path)
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory"}

    moved = 0
    skipped = 0
    errors = []

    for entry in sorted(root.rglob("*")):
        if entry.is_file() and not entry.name.startswith("."):
            try:
                result = apply_rules_to_file(str(entry))
                if result.get("action") != "none":
                    moved += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(str(entry))
                skipped += 1

    return {"ok": True, "directory": str(root), "moved": moved, "skipped": skipped, "errors": len(errors)}


def suggest_organization(file_path: str) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    from fauxnix_tools.utils.categories import file_category
    from fauxnix_tools.files.extraction import extract_any

    cat = file_category(p, "")
    ext = p.suffix.lower()

    suggestions = []

    if cat == "image" and ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        suggestions.append({
            "folder": "~/Pictures", "reason": "Image files belong in Pictures",
            "confidence": 0.9,
        })
    elif cat == "video":
        suggestions.append({
            "folder": "~/Videos", "reason": "Video files belong in Videos",
            "confidence": 0.9,
        })
    elif cat == "audio":
        suggestions.append({
            "folder": "~/Music", "reason": "Audio files belong in Music",
            "confidence": 0.9,
        })
    elif cat == "document":
        suggestions.append({
            "folder": "~/Documents", "reason": "Document files belong in Documents",
            "confidence": 0.85,
        })
    elif cat == "code":
        suggestions.append({
            "folder": "~/Projects", "reason": "Code files belong in Projects",
            "confidence": 0.8,
        })

    text = extract_any(p)
    if text:
        try:
            from fauxnix_tools.llm.embeddings import chat_messages
            prompt = f"""Based on the file content, suggest the best folder to organize this file into.
Return JSON with: folder (absolute or ~/ path), reason (short).

Filename: {p.name}
Content preview: {text[:1000]}

Return ONLY valid JSON."""
            response = chat_messages([{"role": "user", "content": prompt}], task="summary")
            result = response.get("message", {}).get("content", "{}")
            try:
                parsed = json.loads(result[result.find("{"):result.rfind("}") + 1])
                suggestions.append({
                    "folder": parsed.get("folder", "~/Documents"),
                    "reason": parsed.get("reason", "LLM suggested"),
                    "confidence": 0.7,
                    "source": "llm",
                })
            except Exception:
                pass
        except Exception:
            pass

    if not suggestions:
        suggestions.append({
            "folder": "~/Documents", "reason": "Default document location",
            "confidence": 0.3,
        })

    return {"ok": True, "file": str(p), "suggestions": suggestions}


def _matches_conditions(name: str, ext: str, size: int, conditions: dict) -> bool:
    if "extensions" in conditions:
        exts = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in conditions["extensions"]]
        if ext not in exts:
            return False

    if "name_patterns" in conditions:
        if not any(p.lower() in name.lower() for p in conditions["name_patterns"]):
            return False

    if "min_size" in conditions and size < conditions["min_size"]:
        return False
    if "max_size" in conditions and size > conditions["max_size"]:
        return False

    return True
