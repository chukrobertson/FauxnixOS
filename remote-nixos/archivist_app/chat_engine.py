from pathlib import Path

import chromadb
from chromadb.config import Settings
from app.config import ARCHIVE_DUP_REVIEW_DIR, ARCHIVE_REVIEW_DIR, CHROMA_DIR
from app.embeddings import embed_text, chat_messages
from app.db import get_conn
from app.source_safety import is_chat_safe_source
from app.memory import (
    add_message,
    ensure_conversation,
    list_messages,
    maybe_capture_memory,
    search_memories,
)
from app.persona import ARCHIVIST_SYSTEM_PROMPT
from app.file_operator import maybe_handle_file_operator
from app.dashboard import dashboard_context, format_dashboard_context
from app.notes import format_workspace_context

_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
_collection = _client.get_or_create_collection(name="archive_files")


def _path_inside(path_text: str, root: Path) -> bool:
    try:
        Path(path_text).resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def _is_review_path(path_text: str) -> bool:
    return _path_inside(path_text, ARCHIVE_REVIEW_DIR) or _path_inside(path_text, ARCHIVE_DUP_REVIEW_DIR)


def active_chat_file_row(path_text: str) -> dict | None:
    if not path_text or _is_review_path(path_text) or not is_chat_safe_source(path_text):
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, path, name, category, summary, extracted_text, deleted_candidate
        FROM files
        WHERE path = ? AND COALESCE(deleted_candidate, 0) = 0
        """,
        (path_text,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def reset_archive_embeddings() -> dict:
    global _collection
    deleted = False
    try:
        _client.delete_collection(name="archive_files")
        deleted = True
    except Exception:
        deleted = False
    _collection = _client.get_or_create_collection(name="archive_files")
    return {"collection": "archive_files", "deleted": deleted}


def add_embedding(doc_id: str, text: str, metadata: dict):
    if not text.strip():
        return False
    clipped = text[:6000]
    try:
        _collection.upsert(
            ids=[doc_id],
            documents=[clipped],
            embeddings=[embed_text(clipped)],
            metadatas=[metadata],
        )
        return True
    except Exception as e:
        print(f"[embedding] failed {doc_id}: {e}")
        return False


def delete_embeddings(doc_ids: list[str]) -> dict:
    ids = sorted({str(item) for item in doc_ids if str(item or "").strip()})
    if not ids:
        return {"attempted": 0, "deleted": 0, "failed": 0}
    try:
        _collection.delete(ids=ids)
        return {"attempted": len(ids), "deleted": len(ids), "failed": 0}
    except Exception as e:
        print(f"[embedding] delete failed: {e}")
        return {"attempted": len(ids), "deleted": 0, "failed": len(ids), "error": str(e)}


def archive_embedding_ids() -> set[str]:
    try:
        count = _collection.count()
        if count == 0:
            return set()
        all_ids = set()
        offset = 0
        batch = 10000
        while offset < count:
            result = _collection.get(offset=offset, limit=batch)
            all_ids.update(result.get("ids", []))
            offset += batch
        return all_ids
    except Exception:
        return set()


def delete_embedding(doc_id: str) -> dict:
    return delete_embeddings([doc_id])


def sync_file_embedding(row: dict | None) -> dict:
    if not row:
        return {"synced": False, "reason": "missing_row"}
    path = str(row.get("path") or "")
    if not path:
        return {"synced": False, "reason": "missing_path"}
    if int(row.get("deleted_candidate") or 0) or _is_review_path(path) or not is_chat_safe_source(path):
        removed = delete_embedding(path)
        return {"synced": True, "mode": "deleted", "path": path, "embedding": removed}
    category = row.get("category") or "other"
    summary = row.get("summary") or ""
    extracted = row.get("extracted_text") or ""
    tags = file_tags_for_embedding(row)
    tag_text = f"Tags: {', '.join(tags)}" if tags else ""
    text = "\n".join([row.get("name") or Path(path).name, summary, tag_text, extracted[:6000]]).strip()
    corpus = "knowledgebase" if category == "knowledgebase" else "archive"
    embedded = add_embedding(
        doc_id=path,
        text=text,
        metadata={
            "path": path,
            "name": row.get("name") or Path(path).name,
            "category": category,
            "corpus": corpus,
            "summary": summary,
            "tags": ", ".join(tags),
        },
    )
    return {"synced": embedded, "mode": "upserted" if embedded else "failed", "path": path}


def file_tags_for_embedding(row: dict) -> list[str]:
    file_id = row.get("id")
    path = row.get("path")
    conn = get_conn()
    cur = conn.cursor()
    if file_id:
        cur.execute(
            """
            SELECT t.name
            FROM file_tags ft
            JOIN tags t ON t.id = ft.tag_id
            WHERE ft.file_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (int(file_id),),
        )
    else:
        cur.execute(
            """
            SELECT t.name
            FROM files f
            JOIN file_tags ft ON ft.file_id = f.id
            JOIN tags t ON t.id = ft.tag_id
            WHERE f.path = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (str(path),),
        )
    tags = [row["name"] for row in cur.fetchall()]
    conn.close()
    return tags


def sync_file_embedding_by_id(file_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE id = ?", (int(file_id),))
    row = cur.fetchone()
    conn.close()
    return sync_file_embedding(dict(row)) if row else {"synced": False, "reason": "missing_row", "file_id": int(file_id)}


def semantic_search(query: str, n_results: int = 8):
    try:
        res = _collection.query(
            query_embeddings=[embed_text(query)],
            n_results=max(n_results * 5, 25),
            include=["metadatas", "documents", "distances"],
        )
    except Exception:
        return []
    out = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for i in range(len(ids)):
        md = metas[i] or {}
        path = str(md.get("path") or ids[i] or "")
        if not active_chat_file_row(path):
            continue
        out.append({"id": ids[i], "document": docs[i], "metadata": metas[i], "distance": dists[i]})
        if len(out) >= n_results:
            break
    return out


def keyword_search(query: str, limit: int = 12):
    conn = get_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    candidate_limit = max(limit * 10, 50)
    cur.execute(
        """
        SELECT id, path, name, ext, category, summary, preview_path, thumb_path
        FROM files
        WHERE COALESCE(deleted_candidate, 0) = 0
          AND path NOT LIKE ?
          AND path NOT LIKE ?
          AND (name LIKE ? OR extracted_text LIKE ? OR summary LIKE ?)
        LIMIT ?
        """,
        (f"{str(ARCHIVE_REVIEW_DIR)}%", f"{str(ARCHIVE_DUP_REVIEW_DIR)}%", q, q, q, candidate_limit),
    )
    rows = []
    for r in cur.fetchall():
        item = dict(r)
        if is_chat_safe_source(item.get("path") or ""):
            rows.append(item)
        if len(rows) >= limit:
            break
    conn.close()
    return rows


def format_archive_context(keyword_hits: list[dict], semantic_hits: list[dict]) -> str:
    context_blocks = []
    for item in keyword_hits:
        label = "KNOWLEDGEBASE" if item.get("category") == "knowledgebase" else "ARCHIVE"
        context_blocks.append(
            f"[{label} KEYWORD]\nPath: {item['path']}\nSummary: {item.get('summary') or ''}\n"
        )
    for item in semantic_hits:
        md = item["metadata"] or {}
        label = "KNOWLEDGEBASE" if md.get("corpus") == "knowledgebase" or md.get("category") == "knowledgebase" else "ARCHIVE"
        context_blocks.append(
            f"[{label} SEMANTIC]\nPath: {md.get('path')}\nSummary: {md.get('summary', '')}\n"
            f"Extract:\n{(item.get('document') or '')[:1500]}\n"
        )
    return "\n\n".join(context_blocks)[:18000]


def format_memory_context(memory_hits: list[dict]) -> str:
    blocks = []
    for item in memory_hits:
        blocks.append(
            f"[{item.get('status') or 'MEMORY'} | {item.get('kind') or 'observed'} | "
            f"confidence {item.get('confidence', 0)}]\n{item.get('content') or ''}"
        )
    return "\n\n".join(blocks)[:8000]


def recent_history_messages(conversation_id: str, current_message_id: int) -> list[dict[str, str]]:
    history = []
    for item in list_messages(conversation_id, limit=10):
        if item["id"] == current_message_id:
            continue
        if item["role"] not in {"user", "assistant"}:
            continue
        history.append({"role": item["role"], "content": item["content"][:4000]})
    return history[-8:]


def answer_query(query: str, conversation_id: str | None = None, runtime_tools=None):
    conversation_id = ensure_conversation(conversation_id, query)
    user_message_id = add_message(conversation_id, "user", query)
    created_memories = maybe_capture_memory(conversation_id, user_message_id, query)

    operator = maybe_handle_file_operator(query, conversation_id)
    if operator.get("handled"):
        answer = operator.get("answer") or ""
        assistant_message_id = add_message(conversation_id, "assistant", answer)
        return {
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "answer": answer,
            "keyword_hits": operator.get("keyword_hits", []),
            "semantic_hits": [],
            "memory_hits": [],
            "created_memories": created_memories,
            "operator_action": operator.get("operator_action"),
        }

    if runtime_tools:
        operator = runtime_tools(query, conversation_id)
        if operator.get("handled"):
            answer = operator.get("answer") or ""
            assistant_message_id = add_message(conversation_id, "assistant", answer)
            return {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "answer": answer,
                "keyword_hits": operator.get("keyword_hits", []),
                "semantic_hits": [],
                "memory_hits": [],
                "created_memories": created_memories,
                "operator_action": operator.get("operator_action"),
            }

    kw = keyword_search(query, 8)
    sem = semantic_search(query, 8)
    memory_hits = search_memories(query, 8)
    archive_context = format_archive_context(kw, sem)
    memory_context = format_memory_context(memory_hits)
    dashboard = dashboard_context()
    dashboard_text = format_dashboard_context(dashboard)
    workspace_text = format_workspace_context()
    prompt = f"""
Current user query:
{query}

Relevant persistent memory:
{memory_context or "[No directly relevant memory retrieved.]"}

Current dashboard context:
{dashboard_text or "[No dashboard context available.]"}

Current clipboard and notes context:
{workspace_text or "[No active clipboard or notes context.]"}

Archive and knowledgebase evidence:
{archive_context or "[No directly relevant file evidence retrieved.]"}

Answer as the Archivist. Use memory and file evidence when it helps, but clearly
distinguish evidence from inference. Cite file paths when file evidence is used.
Treat KNOWLEDGEBASE evidence as reference material and ARCHIVE evidence as personal archive material.
Weather, calendar, clipboard, notes, and archive activity are chat-aware context.
Do not invent synced data when a provider is not connected.
If the user is asking for reflection rather than retrieval, stay grounded in the
available memory and preserve uncertainty.
"""
    messages = [{"role": "system", "content": ARCHIVIST_SYSTEM_PROMPT}]
    messages.extend(recent_history_messages(conversation_id, user_message_id))
    messages.append({"role": "user", "content": prompt})

    thinking = ""
    try:
        thinking_prompt = [
            {"role": "system", "content": "You are the Archivist's internal reasoning. Think through the user's query step by step. Be thorough, honest about uncertainty, and show your work. Don't give the final answer - just the reasoning process."},
            *messages,
        ]
        thinking = chat_messages(thinking_prompt, task="reasoning")
    except Exception:
        thinking = ""

    if thinking:
        messages.insert(1, {"role": "system", "content": f"Internal reasoning (not shown to user):\n{thinking[:3000]}"})

    try:
        answer = chat_messages(messages, task="archivist_chat")
    except Exception as e:
        answer = (
            "I stored this turn and searched the local archive, but I could not "
            f"reach the local Ollama chat model. The retrieval layer is still "
            f"available. Error: {e}"
        )

    assistant_message_id = add_message(conversation_id, "assistant", answer)
    return {
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "answer": answer,
        "thinking": thinking,
        "keyword_hits": kw,
        "semantic_hits": sem,
        "memory_hits": memory_hits,
        "created_memories": created_memories,
    }
