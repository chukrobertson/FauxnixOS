from __future__ import annotations

from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.config import config as _fauxnix_config
from fennix.config import config as _fennix_config


def recall(query: str, limit: int | None = None) -> list[dict]:
    limit = limit or _fennix_config.recall_top_k
    results: list[dict] = []

    file_results = _search_files_vector(query, limit)
    for r in file_results:
        r["source"] = "file"
    results.extend(file_results)

    memory_results = _search_memories_vector(query, limit)
    for r in memory_results:
        r["source"] = "memory"
    results.extend(memory_results)

    conv_results = _search_conversations_text(query, limit)
    for r in conv_results:
        r["source"] = "conversation"
    results.extend(conv_results)

    if len(results) < limit:
        seen = {(r.get("content", "") or "") for r in results}
        text_results = _search_files_text(query, limit)
        for r in text_results:
            if (r.get("content") or "") not in seen:
                r["source"] = "file"
                results.append(r)
                seen.add(r.get("content") or "")

        text_mem = _search_memories_text(query, limit)
        for r in text_mem:
            if (r.get("content") or "") not in seen:
                r["source"] = "memory"
                results.append(r)
                seen.add(r.get("content") or "")

    scored = [r for r in results if r.get("score", 0) >= _fennix_config.recall_threshold]
    if not scored:
        return results[:limit]

    scored.sort(key=lambda r: r.get("score", 0), reverse=True)
    deduplicated: list[dict] = []
    seen_content: set[str] = set()
    for r in scored:
        content = (r.get("content") or "")[:100]
        if content in seen_content:
            continue
        seen_content.add(content)
        deduplicated.append(r)

    return deduplicated[:limit]


def search_files(query: str, limit: int | None = None) -> list[dict]:
    limit = limit or _fennix_config.recall_top_k
    results = _search_files_vector(query, limit)
    if not results:
        return _search_files_text(query, limit)
    return results


def search_conversations(query: str, limit: int | None = None) -> list[dict]:
    limit = limit or _fennix_config.recall_top_k
    results = _search_conversations_text(query, limit)
    return results[:limit]


def search_memories(query: str, limit: int | None = None) -> list[dict]:
    limit = limit or _fennix_config.recall_top_k
    results = _search_memories_vector(query, limit)
    if not results:
        return _search_memories_text(query, limit)
    return results


def _search_files_vector(query: str, limit: int) -> list[dict]:
    try:
        import chromadb
        from fauxnix_tools.llm.embeddings import embed_text

        client = chromadb.PersistentClient(path=str(_fauxnix_config.data_dir / "chroma"))
        collection = client.get_or_create_collection("fennix_files")
        embedding = embed_text(query[:6000])
        results = collection.query(query_embeddings=[embedding], n_results=limit * 2)

        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        if not ids:
            return []

        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        chunk_rows = _lookup_file_chunks_by_embedding_ids(cur, ids)
        conn.close()

        file_ids = {r["ingested_file_id"] for r in chunk_rows if r["ingested_file_id"]}
        file_map = _lookup_ingested_files(file_ids)

        parsed: list[dict] = []
        id_order = {eid: idx for idx, eid in enumerate(ids)}
        for row in chunk_rows:
            file_info = file_map.get(row["ingested_file_id"], {})
            parsed.append({
                "content": (row.get("content") or "")[:2000],
                "score": 1.0 - min(distances[id_order.get(row.get("embedding_id", ""), 0)], 1.0),
                "file_path": file_info.get("file_path"),
                "file_title": file_info.get("title"),
                "ingested_file_id": row.get("ingested_file_id"),
                "chunk_index": row.get("chunk_index"),
            })

        parsed.sort(key=lambda r: id_order.get(r.get("embedding_id", ""), 999))
        return parsed
    except ImportError:
        return []
    except Exception:
        return []


def _search_memories_vector(query: str, limit: int) -> list[dict]:
    try:
        import chromadb
        from fauxnix_tools.llm.embeddings import embed_text

        client = chromadb.PersistentClient(path=str(_fauxnix_config.data_dir / "chroma"))
        collection = client.get_or_create_collection("membrie_memories")
        embedding = embed_text(query[:6000])
        results = collection.query(query_embeddings=[embedding], n_results=limit * 2)

        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        if not ids:
            return []

        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"SELECT * FROM memory_items WHERE id IN ({placeholders}) AND status = 'KEEP'",
            ids,
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        id_order = {mid: idx for idx, mid in enumerate(ids)}
        results_list: list[dict] = []
        for row in rows:
            results_list.append({
                "content": (row.get("content") or "")[:2000],
                "score": 1.0 - min(distances[id_order.get(row.get("id", ""), 0)], 1.0),
                "memory_id": row.get("id"),
                "memory_kind": row.get("kind"),
                "confidence": row.get("confidence"),
                "source_conversation_id": row.get("source_conversation_id"),
            })

        results_list.sort(key=lambda r: id_order.get(r.get("memory_id", ""), 999))
        return results_list
    except ImportError:
        return []
    except Exception:
        return []


def _search_conversations_text(query: str, limit: int) -> list[dict]:
    try:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        param = f"%{query}%"
        cur.execute(
            """SELECT fm.id, fm.content, fm.conversation_id, fm.created_ts,
                      fc.title AS conv_title
               FROM fennix_messages fm
               LEFT JOIN fennix_conversations fc ON fc.id = fm.conversation_id
               WHERE fm.content LIKE ?
               ORDER BY fm.created_ts DESC
               LIMIT ?""",
            (param, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return [
            {
                "content": (r.get("content") or "")[:2000],
                "score": _simple_text_score(query, r.get("content") or ""),
                "conversation_id": r.get("conversation_id"),
                "conversation_title": r.get("conv_title"),
                "message_id": r.get("id"),
                "created_ts": r.get("created_ts"),
            }
            for r in rows
        ]
    except Exception:
        return []


def _search_files_text(query: str, limit: int) -> list[dict]:
    try:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        param = f"%{query}%"
        cur.execute(
            """SELECT ffc.content, fif.file_path, fif.title, ffc.ingested_file_id, ffc.chunk_index
               FROM fennix_file_chunks ffc
               JOIN fennix_ingested_files fif ON fif.id = ffc.ingested_file_id
               WHERE ffc.content LIKE ?
               ORDER BY fif.updated_ts DESC
               LIMIT ?""",
            (param, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return [
            {
                "content": (r.get("content") or "")[:2000],
                "score": _simple_text_score(query, r.get("content") or ""),
                "file_path": r.get("file_path"),
                "file_title": r.get("title"),
                "ingested_file_id": r.get("ingested_file_id"),
                "chunk_index": r.get("chunk_index"),
            }
            for r in rows
        ]
    except Exception:
        return []


def _search_memories_text(query: str, limit: int) -> list[dict]:
    try:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        param = f"%{query}%"
        cur.execute(
            """SELECT id, content, kind, confidence, source_conversation_id
               FROM memory_items
               WHERE status = 'KEEP' AND (content LIKE ?)
               ORDER BY updated_ts DESC
               LIMIT ?""",
            (param, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return [
            {
                "content": (r.get("content") or "")[:2000],
                "score": _simple_text_score(query, r.get("content") or ""),
                "memory_id": r.get("id"),
                "memory_kind": r.get("kind"),
                "confidence": r.get("confidence"),
                "source_conversation_id": r.get("source_conversation_id"),
            }
            for r in rows
        ]
    except Exception:
        return []


def _lookup_file_chunks_by_embedding_ids(cur, embedding_ids: list[str]) -> list[dict]:
    parsed: list[dict] = []
    for eid in embedding_ids:
        parts = eid.split("-")
        if len(parts) >= 4 and parts[0] == "fennix" and parts[1] == "chunk":
            try:
                ingested_id = int(parts[2])
                chunk_idx = int(parts[3])
                cur.execute(
                    """SELECT content, ingested_file_id, chunk_index, embedding_id
                       FROM fennix_file_chunks
                       WHERE ingested_file_id = ? AND chunk_index = ?""",
                    (ingested_id, chunk_idx),
                )
                row = cur.fetchone()
                if row:
                    parsed.append(dict(row))
            except (ValueError, IndexError):
                pass
    return parsed


def _lookup_ingested_files(file_ids: set[int]) -> dict[int, dict]:
    if not file_ids:
        return {}
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in file_ids)
    cur.execute(
        f"SELECT id, file_path, title FROM fennix_ingested_files WHERE id IN ({placeholders})",
        list(file_ids),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {r["id"]: r for r in rows}


def _simple_text_score(query: str, content: str) -> float:
    q_lower = query.lower()
    c_lower = content.lower()
    query_words = [w for w in q_lower.split() if len(w) > 1]
    if not query_words:
        return 0.0
    matches = sum(1 for w in query_words if w in c_lower)
    return min(matches / len(query_words), 1.0) * 0.5
