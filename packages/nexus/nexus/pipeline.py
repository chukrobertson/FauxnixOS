from __future__ import annotations

import json
import struct
from collections import Counter

from nexus.db import recent_events, get_conn


OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"


def textify_events(thread_name: str, limit: int = 50) -> str:
    events = recent_events(thread_name, limit)
    if not events:
        return ""

    sources = Counter()
    paths: set[str] = set()
    apps: set[str] = set()
    cmds: set[str] = set()
    repos: set[str] = set()
    branches: set[str] = set()

    for e in events:
        src = e["source"]
        sources[src] += 1
        try:
            data = json.loads(e["event_data"])
        except json.JSONDecodeError:
            continue

        if src == "file":
            path = data.get("path", "")
            if path:
                paths.add(path)
        elif src == "window":
            app = data.get("app", "")
            if app:
                apps.add(app)
        elif src == "terminal":
            cmd = data.get("cmd", "")
            if cmd:
                cmds.add(cmd)
        elif src == "git":
            repo = data.get("repo", "")
            branch = data.get("branch", "")
            if repo:
                repos.add(repo)
            if branch:
                branches.add(branch)

    parts = []

    if sources:
        top_sources = [s for s, _ in sources.most_common(3)]
        parts.append(f"Activity: {', '.join(top_sources)}")

    if apps:
        parts.append(f"Apps: {', '.join(sorted(apps)[:5])}")

    if paths:
        key_paths = [p.split("/")[-1] for p in list(paths)[:5]]
        parts.append(f"Files: {', '.join(key_paths)}")

    if cmds:
        parts.append(f"Commands: {', '.join(list(cmds)[:3])}")

    if repos:
        parts.append(f"Repos: {', '.join(list(repos)[:3])}")

    if branches:
        parts.append(f"Branches: {', '.join(list(branches)[:3])}")

    return ". ".join(parts) if parts else f"{len(events)} events"


def embed_text(text: str) -> list[float]:
    if not text:
        return []

    try:
        import urllib.request
        data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("embedding", [])
    except Exception:
        pass

    return _ngram_sparse_vector(text)


def _ngram_sparse_vector(text: str, n: int = 3, dims: int = 768) -> list[float]:
    if not text:
        return [0.0] * dims

    chars = text.lower()
    ngrams = [hash(chars[i:i+n]) % dims for i in range(len(chars) - n + 1)]
    if not ngrams:
        return [0.0] * dims

    counter = Counter(ngrams)
    total = sum(counter.values())
    vec = [0.0] * dims
    for idx, count in counter.items():
        vec[idx] = count / total * 3.0
    return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(v ** 2 for v in vec_a) ** 0.5
    mag_b = sum(v ** 2 for v in vec_b) ** 0.5

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(data: bytes) -> list[float]:
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def store_vector(thread_name: str, text_summary: str, vector: list[float]) -> None:
    if not vector:
        return
    conn = get_conn()
    blob = pack_vector(vector)
    conn.execute(
        "INSERT INTO thread_vectors (thread_name, vector, text_summary) VALUES (?, ?, ?)",
        (thread_name, blob, text_summary),
    )
    conn.commit()
    conn.close()


def load_latest_vector(thread_name: str) -> tuple[str, list[float]] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT text_summary, vector FROM thread_vectors WHERE thread_name = ? ORDER BY id DESC LIMIT 1",
        (thread_name,),
    ).fetchone()
    conn.close()
    if row and row["vector"]:
        return row["text_summary"], unpack_vector(row["vector"])
    return None


def embed_events(thread_name: str, limit: int = 50) -> tuple[str, list[float]]:
    summary = textify_events(thread_name, limit)
    vector = embed_text(summary)
    if vector:
        store_vector(thread_name, summary, vector)
    return summary, vector


def cluster_threads(thread_names: list[str], threshold: float = 0.6) -> list[dict]:
    if len(thread_names) < 2:
        return []

    vectors: dict[str, tuple[str, list[float]]] = {}
    for name in thread_names:
        summary, vector = embed_events(name)
        if summary and vector:
            vectors[name] = (summary, vector)

    overlaps: list[dict] = []
    names = list(vectors.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            sim = cosine_similarity(vectors[a][1], vectors[b][1])
            if sim >= threshold:
                overlaps.append({
                    "thread_a": a,
                    "thread_b": b,
                    "similarity": round(sim, 3),
                    "summary_a": vectors[a][0][:100],
                    "summary_b": vectors[b][0][:100],
                })

    return sorted(overlaps, key=lambda x: x["similarity"], reverse=True)


def detect_drift(thread_name: str, window_a: int = 50, window_b: int = 20) -> dict | None:
    all_events = recent_events(thread_name, 200)
    if len(all_events) < window_b:
        return None

    older = all_events[:window_a] if len(all_events) >= window_a else all_events
    recent = all_events[-window_b:]

    older_text = _textify_event_list(older)
    recent_text = _textify_event_list(recent)

    if not older_text or not recent_text:
        return None

    older_vec = embed_text(older_text)
    recent_vec = embed_text(recent_text)
    similarity = cosine_similarity(older_vec, recent_vec)

    if similarity >= 0.7:
        return None

    return {
        "thread_name": thread_name,
        "similarity": round(similarity, 3),
        "older_topic": older_text[:100],
        "recent_topic": recent_text[:100],
    }


def _textify_event_list(events: list[dict]) -> str:
    sources = Counter()
    apps: set[str] = set()
    cmds: set[str] = set()

    for e in events:
        src = e["source"]
        sources[src] += 1
        try:
            data = json.loads(e["event_data"])
        except json.JSONDecodeError:
            continue
        if src == "window":
            app = data.get("app", "")
            if app:
                apps.add(app)
        elif src == "terminal":
            cmd = data.get("cmd", "")
            if cmd:
                cmds.add(cmd)

    parts = []
    if sources:
        parts.append(", ".join(s for s, _ in sources.most_common(3)))
    if apps:
        parts.append("apps: " + ", ".join(sorted(apps)[:3]))
    if cmds:
        parts.append("cmds: " + ", ".join(list(cmds)[:3]))

    return ". ".join(parts)
