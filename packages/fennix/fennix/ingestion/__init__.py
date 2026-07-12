from __future__ import annotations

import time
import uuid

from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fennix.config import config


def ingest_content(file_path: str, file_hash: str, content: str, source: str = "manual") -> int:
    now = time.time()

    chunks = _chunk_text(content)
    if not chunks:
        return -1

    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    mime = _guess_mime(file_path)
    title = Path(file_path).name if file_path else "clipboard"

    cur.execute(
        """INSERT OR REPLACE INTO fennix_ingested_files
           (file_path, file_hash, mime_type, file_size, title, source, ingested_ts, updated_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_path, file_hash, mime, len(content.encode("utf-8")), title, source, now, now),
    )
    ingested_id = cur.lastrowid

    if ingested_id is None:
        cur.execute(
            "SELECT id FROM fennix_ingested_files WHERE file_path = ?",
            (file_path,),
        )
        row = cur.fetchone()
        ingested_id = row["id"] if row else None

    if ingested_id is None:
        conn.close()
        return -1

    cur.execute(
        "DELETE FROM fennix_file_chunks WHERE ingested_file_id = ?",
        (ingested_id,),
    )

    for i, chunk in enumerate(chunks):
        embedding_id = f"fennix-chunk-{uuid.uuid4().hex[:16]}"
        token_count = len(chunk.split())
        cur.execute(
            """INSERT INTO fennix_file_chunks
               (ingested_file_id, chunk_index, content, token_count, embedding_id, created_ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ingested_id, i, chunk, token_count, embedding_id, now),
        )

    conn.commit()
    conn.close()

    _embed_chunks(ingested_id, chunks)
    return ingested_id


def reingest_content(ingested_file_id: int, file_path: str, file_hash: str, content: str):
    now = time.time()
    chunks = _chunk_text(content)
    if not chunks:
        return

    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    mime = _guess_mime(file_path)
    cur.execute(
        """UPDATE fennix_ingested_files
           SET file_hash = ?, mime_type = ?, file_size = ?, updated_ts = ?
           WHERE id = ?""",
        (file_hash, mime, len(content.encode("utf-8")), now, ingested_file_id),
    )

    cur.execute(
        "DELETE FROM fennix_file_chunks WHERE ingested_file_id = ?",
        (ingested_file_id,),
    )

    for i, chunk in enumerate(chunks):
        embedding_id = f"fennix-chunk-{uuid.uuid4().hex[:16]}"
        token_count = len(chunk.split())
        cur.execute(
            """INSERT INTO fennix_file_chunks
               (ingested_file_id, chunk_index, content, token_count, embedding_id, created_ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ingested_file_id, i, chunk, token_count, embedding_id, now),
        )

    conn.commit()
    conn.close()

    _embed_chunks(ingested_file_id, chunks)


def _chunk_text(text: str) -> list[str]:
    chunk_size = config.chunk_size
    overlap = config.chunk_overlap
    if len(text) <= chunk_size:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current.strip())
            if len(para) > chunk_size:
                words = para.split()
                sub = ""
                for word in words:
                    if len(sub) + len(word) + 1 <= chunk_size:
                        sub = f"{sub} {word}" if sub else word
                    else:
                        chunks.append(sub.strip())
                        sub = word
                if sub:
                    current = sub
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    if overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = []
        for i, chunk in enumerate(chunks[:-1]):
            next_chunk = chunks[i + 1]
            overlap_text = next_chunk[:overlap]
            if overlap_text:
                overlapped.append(f"{chunk}\n\n{overlap_text}")
        overlapped.append(chunks[-1])
        return overlapped

    return chunks


def _embed_chunks(ingested_file_id: int, chunks: list[str]):
    try:
        from fauxnix_tools.llm.embeddings import embed_text
        import chromadb

        client = chromadb.PersistentClient(path=str(config.fauxnix.data_dir / "chroma"))
        collection = client.get_or_create_collection("fennix_files")

        for i, chunk in enumerate(chunks):
            embedding_id = f"fennix-chunk-{ingested_file_id}-{i}"
            try:
                embedding = embed_text(chunk[:6000])
                collection.upsert(
                    ids=[embedding_id],
                    embeddings=[embedding],
                    documents=[chunk[:6000]],
                    metadatas=[{
                        "ingested_file_id": ingested_file_id,
                        "chunk_index": i,
                        "type": "file_chunk",
                    }],
                )
            except Exception:
                pass
    except ImportError:
        pass


def _guess_mime(path: str) -> str:
    from fauxnix_tools.utils import guess_mime
    try:
        return guess_mime(Path(path))
    except Exception:
        return "text/plain"
