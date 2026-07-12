from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from nexus.db import recent_events, insert_event


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


def ngram_vector(text: str, n: int = 3) -> dict[str, float]:
    if not text:
        return {}
    chars = text.lower()
    ngrams = [chars[i:i+n] for i in range(len(chars) - n + 1)]
    counter = Counter(ngrams)
    total = sum(counter.values())
    return {k: v / total for k, v in counter.items()} if total else {}


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0

    all_keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in all_keys)
    mag_a = sum(v ** 2 for v in vec_a.values()) ** 0.5
    mag_b = sum(v ** 2 for v in vec_b.values()) ** 0.5

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def embed_events(thread_name: str, limit: int = 50) -> tuple[str, dict[str, float]]:
    summary = textify_events(thread_name, limit)
    vector = ngram_vector(summary)
    return summary, vector


def cluster_threads(thread_names: list[str], threshold: float = 0.6) -> list[dict]:
    if len(thread_names) < 2:
        return []

    vectors: dict[str, tuple[str, dict[str, float]]] = {}
    for name in thread_names:
        summary, vector = embed_events(name)
        if summary:
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

    older_vec = ngram_vector(older_text)
    recent_vec = ngram_vector(recent_text)
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
