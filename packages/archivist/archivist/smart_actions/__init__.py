from __future__ import annotations

import json
import time
from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.llm.embeddings import chat_messages
from fauxnix_tools.files.extraction import extract_any
from fauxnix_tools.utils import sha256_file


def auto_classify_file(file_path: str, file_id: int | None = None) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    text = extract_any(p)
    info = {
        "name": p.name, "ext": p.suffix, "size": p.stat().st_size,
        "text_sample": text[:3000] if text else "",
    }

    try:
        prompt = f"""Analyze this file and return JSON with:
category: one of (invoice, receipt, contract, resume, photo, screenshot, document, code, spreadsheet, presentation, archive, media, other)
title: short descriptive title (max 60 chars)
tags: array of 3-6 relevant tags
summary: one sentence summary
confidentiality: one of (public, internal, confidential, personal)

File: {info['name']}
Size: {info['size']} bytes
Content sample: {info['text_sample'][:2000]}

Return ONLY valid JSON. No explanation."""
        response = chat_messages([{"role": "user", "content": prompt}], task="summary")
        result = response.get("message", {}).get("content", "{}")
        try:
            parsed = json.loads(_extract_json(result))
        except Exception:
            parsed = {"category": "document", "title": p.stem[:60], "tags": [], "summary": p.name, "confidentiality": "internal"}
    except Exception:
        parsed = {"category": "document", "title": p.stem[:60], "tags": [], "summary": p.name, "confidentiality": "internal"}

    if file_id:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute("UPDATE files SET summary = ? WHERE id = ?", (parsed.get("title", "")[:200], file_id))
        cur.execute(
            "INSERT INTO file_actions (file_id, action_type, result_json, decided_by, created_ts) VALUES (?, ?, ?, ?, ?)",
            (file_id, "classify", json.dumps(parsed), "llm", time.time()),
        )
        conn.commit()
        conn.close()

    return {"ok": True, "file": str(p), "classification": parsed}


def detect_duplicates(file_path: str, limit: int = 10) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    current_hash = sha256_file(p)
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, path, name, size_bytes, indexed_ts FROM files WHERE sha256 = ? AND path != ? ORDER BY indexed_ts DESC LIMIT ?",
        (current_hash, str(p), limit),
    )
    exact_dupes = [dict(r) for r in cur.fetchall()]

    similar = []
    if not exact_dupes:
        name_stem = p.stem.lower()
        size = p.stat().st_size
        cur.execute(
            """SELECT id, path, name, size_bytes, indexed_ts FROM files
               WHERE (LOWER(name) LIKE ? OR (ABS(size_bytes - ?) < 100 AND size_bytes > 0))
               AND path != ? ORDER BY indexed_ts DESC LIMIT ?""",
            (f"%{name_stem}%", size, str(p), limit),
        )
        similar = [dict(r) for r in cur.fetchall()]

    conn.close()

    return {
        "ok": True,
        "file": str(p),
        "hash": current_hash,
        "exact_duplicates": exact_dupes,
        "similar": similar,
        "has_exact_dupes": len(exact_dupes) > 0,
    }


def suggest_rename(file_path: str) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    text = extract_any(p)
    context = {
        "name": p.name, "ext": p.suffix, "stem": p.stem,
        "size": p.stat().st_size,
        "text_sample": text[:2000] if text else "",
    }

    try:
        prompt = f"""Suggest a better filename for this file. Return JSON with:
suggested_name: clear descriptive filename (preserve extension)
reason: short explanation why this name is better

Current: {context['name']}
Content: {context['text_sample'][:1500]}

Return ONLY valid JSON."""
        response = chat_messages([{"role": "user", "content": prompt}], task="summary")
        result = response.get("message", {}).get("content", "{}")
        try:
            parsed = json.loads(_extract_json(result))
        except Exception:
            parsed = {"suggested_name": p.name, "reason": "Could not generate suggestion"}
    except Exception:
        parsed = {"suggested_name": p.name, "reason": "LLM unavailable"}

    return {"ok": True, "file": str(p), "current_name": p.name, **parsed}


def smart_summarize_directory(dir_path: str) -> dict:
    root = Path(dir_path)
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory"}

    files = []
    total_size = 0
    categories = {}
    for entry in sorted(root.rglob("*")):
        if entry.is_file() and not entry.name.startswith("."):
            files.append({"name": entry.name, "ext": entry.suffix.lower(), "size": entry.stat().st_size})
            total_size += entry.stat().st_size
            cat = entry.suffix.lower() or "unknown"
            categories[cat] = categories.get(cat, 0) + 1

    file_list = "\n".join(f"- {f['name']} ({f['size']}B)" for f in files[:50])
    prompt = f"""Summarize this directory. Return JSON with:
summary: one sentence describing what this directory contains
purpose: likely purpose (e.g. 'project source', 'photo collection', 'downloads', 'backup')
suggested_name: a good folder name if it needs renaming
organization_hint: suggestion for how to organize it better

Directory contains {len(files)} files, {total_size} bytes.
Top extensions: {dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5])}
Files:\n{file_list}

Return ONLY valid JSON."""

    try:
        response = chat_messages([{"role": "user", "content": prompt}], task="summary")
        result = response.get("message", {}).get("content", "{}")
        parsed = json.loads(_extract_json(result))
    except Exception:
        parsed = {"summary": f"Directory with {len(files)} files", "purpose": "unknown", "suggested_name": root.name, "organization_hint": "No suggestion"}

    return {"ok": True, "directory": str(root), "file_count": len(files), "total_bytes": total_size, "categories": categories, "analysis": parsed}


def _extract_json(text: str) -> str:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return text
