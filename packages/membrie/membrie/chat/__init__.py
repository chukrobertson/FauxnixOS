from __future__ import annotations

import time
import uuid
from typing import Optional

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.llm.embeddings import chat_messages
from fauxnix_tools.llm.router import model_for_task
from membrie.chat.persona import get_persona
from membrie.chat.memory import create_memory, search_memories, upsert_memory_vector
from membrie.awareness.process import get_active_process_context


def answer_query(user_text: str, conversation_id: Optional[str] = None) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    if conversation_id:
        cur.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,))
        if not cur.fetchone():
            conversation_id = None

    if not conversation_id:
        conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
        now = time.time()
        title = (user_text or "")[:80].split("\n")[0].strip()
        cur.execute(
            "INSERT INTO conversations (id, title, created_ts, updated_ts) VALUES (?, ?, ?, ?)",
            (conversation_id, title or "Untitled", now, now),
        )

    now = time.time()
    cur.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, created_ts) VALUES (?, 'user', ?, ?)",
        (conversation_id, user_text[:4000], now),
    )
    user_msg_id = cur.lastrowid
    cur.execute("UPDATE conversations SET updated_ts = ? WHERE id = ?", (now, conversation_id))
    conn.commit()

    cur.execute(
        "SELECT role, content FROM chat_messages WHERE conversation_id = ? ORDER BY created_ts ASC LIMIT 30",
        (conversation_id,),
    )
    history = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
    conn.close()

    memories = search_memories(user_text, limit=5)
    memory_context = ""
    if memories:
        memory_context = "\n".join(f"- {m['content'][:200]}" for m in memories)
        memory_context = f"\n\n[User memories]\n{memory_context}\n"

    process_context = get_active_process_context()

    persona = get_persona()
    system_prompt = persona
    if process_context:
        system_prompt += f"\n\nCurrent desktop context: {process_context}"
    if memory_context:
        system_prompt += memory_context

    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    try:
        response = chat_messages(messages, task="chat")
        reply = response.get("message", {}).get("content", "") or str(response.get("content", ""))
    except Exception as e:
        reply = f"Error connecting to Ollama: {e}"

    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    now = time.time()
    cur.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, created_ts) VALUES (?, 'assistant', ?, ?)",
        (conversation_id, reply[:4000], now),
    )
    cur.execute("UPDATE conversations SET updated_ts = ? WHERE id = ?", (now, conversation_id))
    conn.commit()
    conn.close()

    _auto_capture_memory(user_text, reply, conversation_id, user_msg_id)

    return {
        "conversation_id": conversation_id,
        "user": user_text[:4000],
        "reply": reply[:4000],
        "timestamp": now,
    }


def get_conversation(conversation_id: str) -> dict | None:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    conv = cur.fetchone()
    if not conv:
        conn.close()
        return None
    cur.execute(
        "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY created_ts ASC",
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
    cur.execute("SELECT * FROM conversations ORDER BY updated_ts DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _auto_capture_memory(user_text: str, reply: str, conversation_id: str, message_id: int):
    observed = _detect_personal_statement(user_text)
    if observed:
        mem = create_memory(
            content=observed, kind="observed", confidence=0.65,
            source_conversation_id=conversation_id,
            source_message_id=message_id,
            evidence=user_text[:300],
        )
        upsert_memory_vector(mem["id"], observed)

    explicit = _detect_remember_command(user_text)
    if explicit:
        mem = create_memory(
            content=explicit, kind="observed", confidence=0.85,
            source_conversation_id=conversation_id,
            source_message_id=message_id,
            evidence="Explicit remember command",
        )
        upsert_memory_vector(mem["id"], explicit)


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
