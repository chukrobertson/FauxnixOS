from __future__ import annotations

import json
import time
import uuid

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.llm.embeddings import embed_text


def create_memory(content: str, kind: str = "observed", confidence: float = 0.7,
                  source_conversation_id: str | None = None,
                  source_message_id: int | None = None,
                  evidence: str | None = None) -> dict:
    memory_id = f"mem-{uuid.uuid4().hex[:12]}"
    now = time.time()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO memory_items (id, kind, status, content, evidence, confidence,
           source_conversation_id, source_message_id, created_ts, updated_ts)
           VALUES (?, ?, 'KEEP', ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, kind, content[:2000], evidence, confidence,
         source_conversation_id, source_message_id, now, now),
    )
    conn.commit()
    conn.close()
    return {"id": memory_id, "kind": kind, "content": content[:2000], "confidence": confidence}


def search_memories(query: str, limit: int = 10) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """SELECT * FROM memory_items WHERE status = 'KEEP'
           AND (content LIKE ? OR evidence LIKE ?)
           ORDER BY updated_ts DESC LIMIT ?""",
        (q, q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def search_memories_vector(query: str, limit: int = 10) -> list[dict]:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(config.data_dir / "chroma"))
        collection = client.get_or_create_collection("membrie_memories")
        embedding = embed_text(query)
        results = collection.query(query_embeddings=[embedding], n_results=limit)
        ids = results.get("ids", [[]])[0]
        if not ids:
            return search_memories(query, limit)
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        cur.execute(f"SELECT * FROM memory_items WHERE id IN ({placeholders})", ids)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        id_order = {mid: idx for idx, mid in enumerate(ids)}
        ordered = sorted(rows, key=lambda r: id_order.get(r["id"], 999))
        return ordered
    except Exception:
        return search_memories(query, limit)

# need to fix config import
from fauxnix_tools.config import config


def list_memories(limit: int = 50, kind: str | None = None, status: str = "KEEP") -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    if kind:
        cur.execute("SELECT * FROM memory_items WHERE status = ? AND kind = ? ORDER BY updated_ts DESC LIMIT ?",
                     (status, kind, limit))
    else:
        cur.execute("SELECT * FROM memory_items WHERE status = ? ORDER BY updated_ts DESC LIMIT ?",
                     (status, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_memory_status(memory_id: str, status: str) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("UPDATE memory_items SET status = ?, updated_ts = ? WHERE id = ?",
                 (status, time.time(), memory_id))
    conn.commit()
    conn.close()
    return {"id": memory_id, "status": status}


def upsert_memory_vector(memory_id: str, content: str):
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(config.data_dir / "chroma"))
        collection = client.get_or_create_collection("membrie_memories")
        embedding = embed_text(content)
        collection.upsert(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content[:2000]],
        )
    except Exception:
        pass
