from __future__ import annotations

import time
import uuid

from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.llm.embeddings import chat_messages, embed_text
from fennix.config import config
from fennix.assistant.persona import get_persona
from fennix.assistant.context import build_context_block
from fennix.recall.__init__ import recall


def answer(user_text: str, conversation_id: str | None = None) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    if conversation_id:
        cur.execute("SELECT id FROM fennix_conversations WHERE id = ?", (conversation_id,))
        if not cur.fetchone():
            conversation_id = None

    if not conversation_id:
        conversation_id = _start_conversation(cur, user_text)

    now = time.time()
    cur.execute(
        "INSERT INTO fennix_messages (conversation_id, role, content, created_ts) VALUES (?, 'user', ?, ?)",
        (conversation_id, user_text[:4000], now),
    )
    user_msg_id = cur.lastrowid
    cur.execute("UPDATE fennix_conversations SET ended_ts = NULL WHERE id = ?", (conversation_id,))
    conn.commit()

    cur.execute(
        "SELECT role, content FROM fennix_messages WHERE conversation_id = ? ORDER BY created_ts ASC LIMIT 30",
        (conversation_id,),
    )
    history = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
    conn.close()

    persona = get_persona()
    context_block = build_context_block(user_text)

    system_prompt = persona
    if context_block:
        system_prompt += f"\n\n### Current OS Context\n{context_block}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages += history[-20:]

    try:
        response = chat_messages(messages, task="chat")
        reply = response.get("message", {}).get("content", "") or str(response.get("content", ""))
    except Exception as e:
        reply = f"Error connecting to Ollama: {e}"

    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    now = time.time()
    cur.execute(
        "INSERT INTO fennix_messages (conversation_id, role, content, created_ts) VALUES (?, 'assistant', ?, ?)",
        (conversation_id, reply[:4000], now),
    )
    cur.execute(
        "UPDATE fennix_conversations SET ended_ts = ? WHERE id = ?",
        (now, conversation_id),
    )
    conn.commit()
    conn.close()

    _auto_capture_memory(user_text, reply, conversation_id, user_msg_id)
    _embed_conversation_message(conversation_id, user_text)

    return {
        "conversation_id": conversation_id,
        "user": user_text[:4000],
        "reply": reply[:4000],
        "timestamp": now,
    }


def answer_with_file(file_path: str, user_text: str, conversation_id: str | None = None) -> dict:
    path = Path(file_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Cannot read file: {e}"}

    from fennix.ingestion.__init__ import ingest_content
    from fauxnix_tools.utils import sha256_file

    file_hash = sha256_file(path)
    ingest_content(
        file_path=str(path),
        file_hash=file_hash,
        content=content,
        source="manual",
    )

    full_text = f"[User provided file: {path.name}]\n\nFile contents:\n{content[:4000]}\n\nQuestion: {user_text}"
    return answer(full_text, conversation_id)


def get_conversation(conversation_id: str) -> dict | None:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fennix_conversations WHERE id = ?", (conversation_id,))
    conv = cur.fetchone()
    if not conv:
        conn.close()
        return None
    cur.execute(
        "SELECT * FROM fennix_messages WHERE conversation_id = ? ORDER BY created_ts ASC",
        (conversation_id,),
    )
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()
    conv_d = dict(conv)
    conv_d["messages"] = messages
    return conv_d


def list_conversations(limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM fennix_conversations ORDER BY started_ts DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def recall_context_for_query(query: str) -> list[dict]:
    return recall(query)


def _start_conversation(cur, user_text: str) -> str:
    conv_id = f"fennix-{uuid.uuid4().hex[:12]}"
    now = time.time()
    title = (user_text or "")[:80].split("\n")[0].strip()
    cur.execute(
        "INSERT INTO fennix_conversations (id, title, started_ts, session_id) VALUES (?, ?, ?, NULL)",
        (conv_id, title or "Untitled", now),
    )
    return conv_id


def _auto_capture_memory(user_text: str, reply: str, conversation_id: str, message_id: int | None):
    observed = _detect_personal_statement(user_text)
    if observed:
        _create_and_embed_memory(observed, "observed", 0.65, conversation_id, message_id, user_text[:300])

    explicit = _detect_remember_command(user_text)
    if explicit:
        _create_and_embed_memory(explicit, "observed", 0.85, conversation_id, message_id, "Explicit remember command")


def _create_and_embed_memory(content: str, kind: str, confidence: float, conv_id: str, msg_id: int | None, evidence: str):
    from fauxnix_tools.db import get_conn
    try:
        memory_id = f"mem-{uuid.uuid4().hex[:12]}"
        now = time.time()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO memory_items (id, kind, status, content, evidence, confidence,
               source_conversation_id, source_message_id, created_ts, updated_ts)
               VALUES (?, ?, 'KEEP', ?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, kind, content[:2000], evidence, confidence, conv_id, msg_id, now, now),
        )
        conn.commit()
        conn.close()

        import chromadb
        from fauxnix_tools.config import config as fauxnix_config
        client = chromadb.PersistentClient(path=str(fauxnix_config.data_dir / "chroma"))
        collection = client.get_or_create_collection("membrie_memories")
        embedding = embed_text(content[:2000])
        collection.upsert(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content[:2000]],
        )
    except ImportError:
        pass
    except Exception:
        pass


def _embed_conversation_message(conversation_id: str, content: str):
    try:
        import chromadb
        embedding = embed_text(content[:6000])
        client = chromadb.PersistentClient(path=str(config.fauxnix.data_dir / "chroma"))
        collection = client.get_or_create_collection("fennix_conversations")
        msg_id = f"fennix-msg-{conversation_id}-{int(time.time())}"
        collection.upsert(
            ids=[msg_id],
            embeddings=[embedding],
            documents=[content[:6000]],
            metadatas=[{
                "conversation_id": conversation_id,
                "type": "conversation_message",
            }],
        )
    except ImportError:
        pass
    except Exception:
        pass


_PERSONAL_STARTERS = [
    "i am ", "my name is ", "i'm ", "my family ", "i live in ", "i work at ",
    "i feel ", "i think ", "i believe ", "my favorite ", "i prefer ",
    "i have a ", "my hobby ", "my pet ", "my dog ", "my cat ",
    "i study ", "i'm studying ", "i graduated ", "my major ",
]


def _detect_personal_statement(text: str) -> str | None:
    lower = text.strip().lower()
    for starter in _PERSONAL_STARTERS:
        if lower.startswith(starter):
            return text.strip()[:2000]
    return None


def _detect_remember_command(text: str) -> str | None:
    lower = text.strip().lower()
    prefixes = [
        "remember that ", "remember: ", "remember this: ",
        "don't forget: ", "note to self: ", "please remember ",
    ]
    for prefix in prefixes:
        if lower.startswith(prefix):
            remainder = text.strip()[len(prefix):]
            return remainder[:2000] if remainder else None
    return None
