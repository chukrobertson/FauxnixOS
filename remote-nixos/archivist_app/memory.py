import re
import time
import uuid

import chromadb
from chromadb.config import Settings

from app.config import CHROMA_DIR
from app.db import get_conn
from app.embeddings import embed_text
from app.persona import KEEP_SWEEP_STATUSES

_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
_memory_collection = _client.get_or_create_collection(name="archivist_memories")

MEMORY_MARKERS = (
    "i am ",
    "i'm ",
    "i was ",
    "i used to ",
    "i feel ",
    "i believe ",
    "i value ",
    "i want ",
    "i need ",
    "my kids",
    "my children",
    "my family",
    "my daughter",
    "my son",
    "my life",
    "my archive",
    "my project",
    "my trauma",
    "my memory",
    "for me,",
)


def now_ts() -> float:
    return time.time()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def safe_status(status: str) -> str:
    cleaned = (status or "KEEP").strip().upper()
    return cleaned if cleaned in KEEP_SWEEP_STATUSES else "KEEP"


def conversation_title(text: str) -> str:
    title = normalize_text(text)
    if not title:
        return "Untitled thread"
    return title[:64] + ("..." if len(title) > 64 else "")


def normalize_scope(scope: str | None) -> str:
    cleaned = normalize_text(scope or "archivist").lower()
    return cleaned if cleaned in {"archivist", "admin", "fauxdex", "cowriter"} else "archivist"


def ensure_conversation(conversation_id: str | None, title_seed: str | None = None, scope: str = "archivist") -> str:
    scope = normalize_scope(scope)
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    if conversation_id:
        cur.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = ? AND COALESCE(scope, 'archivist') = ?
            """,
            (conversation_id, scope),
        )
        if cur.fetchone():
            cur.execute("UPDATE conversations SET updated_ts = ? WHERE id = ?", (ts, conversation_id))
            conn.commit()
            conn.close()
            return conversation_id

    new_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO conversations (id, title, scope, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?)",
        (new_id, conversation_title(title_seed or ""), scope, ts, ts),
    )
    conn.commit()
    conn.close()
    return new_id


def list_conversations(limit: int = 40, scope: str = "archivist") -> list[dict]:
    scope = normalize_scope(scope)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.title, COALESCE(c.scope, 'archivist') AS scope, c.created_ts, c.updated_ts, COUNT(m.id) AS message_count
        FROM conversations c
        LEFT JOIN chat_messages m ON m.conversation_id = c.id
        WHERE COALESCE(c.scope, 'archivist') = ?
        GROUP BY c.id
        ORDER BY c.updated_ts DESC
        LIMIT ?
        """,
        (scope, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_message(conversation_id: str, role: str, content: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, created_ts) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, ts),
    )
    message_id = int(cur.lastrowid)
    cur.execute("UPDATE conversations SET updated_ts = ? WHERE id = ?", (ts, conversation_id))
    conn.commit()
    conn.close()
    return message_id


def list_messages(conversation_id: str, limit: int = 80) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, conversation_id, role, content, created_ts
        FROM chat_messages
        WHERE conversation_id = ?
        ORDER BY created_ts DESC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return list(reversed(rows))


def create_memory(
    content: str,
    *,
    kind: str = "observed",
    status: str = "DORMANT_SEED",
    evidence: str | None = None,
    confidence: float = 0.55,
    source_conversation_id: str | None = None,
    source_message_id: int | None = None,
    notes: str | None = None,
) -> dict | None:
    cleaned = normalize_text(content)
    if len(cleaned) < 8:
        return None

    memory_id = str(uuid.uuid4())
    ts = now_ts()
    row = {
        "id": memory_id,
        "kind": normalize_text(kind)[:64] or "observed",
        "status": safe_status(status),
        "content": cleaned,
        "evidence": normalize_text(evidence or cleaned)[:3000],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "source_conversation_id": source_conversation_id,
        "source_message_id": source_message_id,
        "created_ts": ts,
        "updated_ts": ts,
        "notes": notes,
    }

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_items (
            id, kind, status, content, evidence, confidence, source_conversation_id,
            source_message_id, created_ts, updated_ts, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["kind"],
            row["status"],
            row["content"],
            row["evidence"],
            row["confidence"],
            row["source_conversation_id"],
            row["source_message_id"],
            row["created_ts"],
            row["updated_ts"],
            row["notes"],
        ),
    )
    conn.commit()
    conn.close()

    try:
        _memory_collection.upsert(
            ids=[memory_id],
            documents=[row["content"]],
            embeddings=[embed_text(row["content"])],
            metadatas=[
                {
                    "kind": row["kind"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "created_ts": row["created_ts"],
                    "source_conversation_id": row["source_conversation_id"] or "",
                }
            ],
        )
    except Exception as e:
        row["embedding_error"] = str(e)

    return row


def explicit_memory_from_text(text: str) -> str | None:
    cleaned = normalize_text(text)
    patterns = (
        r"\bplease remember(?: that)?\s+(.+)$",
        r"\bremember(?: this| that)?:?\s+(.+)$",
        r"\bmake a note(?: that| of)?\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1))
    return None


def looks_personal(text: str) -> bool:
    lower = f" {normalize_text(text).lower()} "
    if len(lower) < 28 or len(lower) > 1200:
        return False
    if lower.strip().endswith("?"):
        return False
    return any(marker in lower for marker in MEMORY_MARKERS)


def maybe_capture_memory(conversation_id: str, message_id: int, user_text: str) -> list[dict]:
    created = []
    explicit = explicit_memory_from_text(user_text)
    if explicit:
        memory = create_memory(
            explicit,
            kind="explicit",
            status="KEEP",
            evidence=user_text,
            confidence=0.95,
            source_conversation_id=conversation_id,
            source_message_id=message_id,
        )
        if memory:
            created.append(memory)
        return created

    if looks_personal(user_text):
        memory = create_memory(
            user_text,
            kind="observed",
            status="DORMANT_SEED",
            evidence=user_text,
            confidence=0.52,
            source_conversation_id=conversation_id,
            source_message_id=message_id,
        )
        if memory:
            created.append(memory)
    return created


def keyword_memory_search(query: str, limit: int = 8) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """
        SELECT id, kind, status, content, evidence, confidence, created_ts, updated_ts
        FROM memory_items
        WHERE content LIKE ? OR evidence LIKE ? OR notes LIKE ?
        ORDER BY updated_ts DESC
        LIMIT ?
        """,
        (q, q, q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def search_memories(query: str, limit: int = 8) -> list[dict]:
    try:
        res = _memory_collection.query(
            query_embeddings=[embed_text(query)],
            n_results=limit,
            include=["metadatas", "documents", "distances"],
        )
        out = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i in range(len(ids)):
            md = metas[i] or {}
            out.append(
                {
                    "id": ids[i],
                    "content": docs[i],
                    "kind": md.get("kind", ""),
                    "status": md.get("status", ""),
                    "confidence": md.get("confidence", 0),
                    "distance": dists[i],
                }
            )
        return out or keyword_memory_search(query, limit)
    except Exception:
        return keyword_memory_search(query, limit)


def list_memories(limit: int = 30) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, kind, status, content, evidence, confidence, created_ts, updated_ts, notes
        FROM memory_items
        ORDER BY updated_ts DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def memory_status() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM memory_items")
    total = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM memory_items
        GROUP BY status
        ORDER BY status
        """
    )
    by_status = {row["status"]: row["count"] for row in cur.fetchall()}
    conn.close()
    return {"total": total, "by_status": by_status}
