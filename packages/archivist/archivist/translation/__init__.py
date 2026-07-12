from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.media.transcription import transcribe_video
from fauxnix_tools.llm.embeddings import chat_messages
from archivist.config import config


def translate_document(file_path: str, target_lang: str,
                       source_lang: str = "auto", file_id: int | None = None) -> dict:
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    from fauxnix_tools.files.extraction import extract_any
    text = extract_any(p)
    if not text or text.startswith("["):
        return {"ok": False, "error": "No extractable text"}

    chunks = _chunk_text(text, 3000)
    translated_chunks = []
    for i, chunk in enumerate(chunks):
        try:
            prompt = f"Translate the following text to {target_lang}. Return ONLY the translation, no explanations.\n\n{chunk}"
            response = chat_messages([{"role": "user", "content": prompt}], task="summary")
            translated = response.get("message", {}).get("content", "")[:4000]
            translated_chunks.append(translated)
        except Exception:
            translated_chunks.append(f"[Translation error: chunk {i+1}]")

    translated_text = "\n\n".join(translated_chunks)

    if file_id:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO translation_cache (file_id, source_lang, target_lang, translated_text, segments_json, created_ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, source_lang, target_lang, translated_text[:50000],
             json.dumps({"chunks": len(chunks), "source_chars": len(text)}), time.time()),
        )
        cur.execute(
            "INSERT INTO file_actions (file_id, action_type, result_json, decided_by, created_ts) VALUES (?, ?, ?, ?, ?)",
            (file_id, "translate", json.dumps({"target_lang": target_lang, "chars": len(translated_text)}), "llm", time.time()),
        )
        conn.commit()
        conn.close()

    return {"ok": True, "file": str(p), "source_chars": len(text), "translated_chars": len(translated_text), "target_lang": target_lang, "translated_text": translated_text[:10000]}


def translate_video_subtitles(video_path: str, target_lang: str,
                               file_id: int | None = None) -> dict:
    p = Path(video_path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    try:
        transcript = transcribe_video(str(p), file_id=file_id, prefer_subtitles=True)
        text = transcript.get("text") or ""
        engine = transcript.get("engine", "unknown")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not text:
        return {"ok": False, "error": "No speech or subtitles found"}

    chunks = _chunk_text(text, 2000)
    translated_chunks = []
    for chunk in chunks:
        try:
            prompt = f"Translate the following transcript to {target_lang}. Return ONLY the translation.\n\n{chunk}"
            response = chat_messages([{"role": "user", "content": prompt}], task="summary")
            translated_chunks.append(response.get("message", {}).get("content", "")[:3000])
        except Exception:
            translated_chunks.append(f"[Error]")

    translated = "\n\n".join(translated_chunks)

    return {"ok": True, "video": str(p), "engine": engine, "source_chars": len(text), "translated_chars": len(translated), "target_lang": target_lang, "translated_text": translated[:10000]}


def translation_status() -> dict:
    return {
        "available": True,
        "supported_languages": config.translation_languages,
        "engine": "ollama_llm",
        "hint": "Uses the LLM for translation. Install larger models for better quality.",
    }


def get_cached_translation(file_id: int, target_lang: str) -> dict | None:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM translation_cache WHERE file_id = ? AND target_lang = ?",
        (file_id, target_lang),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        d = dict(row)
        if d.get("segments_json"):
            d["segments"] = json.loads(d["segments_json"])
        return {"ok": True, "translation": d}
    return None


def _chunk_text(text: str, max_chars: int) -> list[str]:
    chunks = []
    current = ""
    for paragraph in text.split("\n"):
        if len(current) + len(paragraph) > max_chars and current:
            chunks.append(current.strip())
            current = ""
        current += paragraph + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks
