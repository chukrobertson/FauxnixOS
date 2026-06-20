from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from app.config import ARCHIVE_DUP_REVIEW_DIR, ARCHIVE_REVIEW_DIR, DATA_DIR
from app.db import get_conn
from app.source_safety import is_chat_safe_source
from app.utils import clean_filename, ensure_parent, unique_path


SMART_SORT_EXPORT_DIR = DATA_DIR / "smart_sort_exports"
STOPWORDS = {
    "about",
    "after",
    "all",
    "and",
    "archive",
    "around",
    "based",
    "before",
    "build",
    "by",
    "context",
    "copy",
    "direct",
    "export",
    "files",
    "for",
    "from",
    "into",
    "link",
    "links",
    "make",
    "of",
    "on",
    "reconstruct",
    "save",
    "smart",
    "sort",
    "symlink",
    "that",
    "the",
    "these",
    "timeline",
    "to",
    "with",
}
MONTHS = {
    name.lower(): idx
    for idx, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
MONTHS.update({name[:3].lower(): value for name, value in list(MONTHS.items())})


def _safe_json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _review_path(path_text: str) -> bool:
    try:
        path = Path(path_text).resolve(strict=False)
        return path.is_relative_to(ARCHIVE_REVIEW_DIR.resolve(strict=False)) or path.is_relative_to(ARCHIVE_DUP_REVIEW_DIR.resolve(strict=False))
    except Exception:
        return False


def smart_sort_terms(query: str) -> list[str]:
    terms = []
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]{2,}", query or ""):
        clean = term.strip("_-'").lower()
        if clean and clean not in STOPWORDS and clean not in terms:
            terms.append(clean)
    return terms[:12]


def _ts(year: int, month: int = 1, day: int = 1) -> float | None:
    try:
        return datetime(year, month, day).timestamp()
    except (OSError, OverflowError, ValueError):
        return None


def evidence_date(text: str) -> tuple[float | None, str, str]:
    haystack = text or ""
    patterns = [
        (r"\b(20\d{2}|19\d{2})[-_. ](0?[1-9]|1[0-2])[-_. ](0?[1-9]|[12]\d|3[01])\b", "ymd"),
        (r"\b(0?[1-9]|1[0-2])[-_. ](0?[1-9]|[12]\d|3[01])[-_. ](20\d{2}|19\d{2})\b", "mdy"),
        (r"\b(20\d{2}|19\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b", "compact"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, haystack)
        if not match:
            continue
        if kind in {"ymd", "compact"}:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        else:
            month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        ts = _ts(year, month, day)
        if ts is not None:
            return ts, "day", match.group(0)
    month_match = re.search(
        r"\b("
        + "|".join(re.escape(name) for name in sorted(MONTHS, key=len, reverse=True))
        + r")\s+([0-3]?\d)(?:st|nd|rd|th)?[,]?\s+(20\d{2}|19\d{2})\b",
        haystack,
        re.I,
    )
    if month_match:
        month = MONTHS.get(month_match.group(1).lower())
        day = int(month_match.group(2))
        year = int(month_match.group(3))
        ts = _ts(year, month or 1, day)
        if ts is not None:
            return ts, "day", month_match.group(0)
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", haystack)
    if year_match:
        ts = _ts(int(year_match.group(1)))
        if ts is not None:
            return ts, "year", year_match.group(1)
    return None, "unknown", ""


def _date_label(ts: float | None, precision: str, fallback: str = "Undated") -> str:
    if not ts:
        return fallback
    try:
        dt = datetime.fromtimestamp(float(ts))
    except (OSError, OverflowError, ValueError):
        return fallback
    if precision == "year":
        return str(dt.year)
    if precision == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def _score_row(row: dict, terms: list[str], semantic_paths: set[str]) -> tuple[float, list[str]]:
    text_fields = {
        "name": row.get("name") or "",
        "path": row.get("path") or "",
        "summary": row.get("summary") or "",
        "tags": " ".join(row.get("tags") or []),
        "people": " ".join(row.get("people") or []),
        "text": row.get("extracted_text") or "",
    }
    score = 0.0
    reasons = []
    lowered = {key: value.lower() for key, value in text_fields.items()}
    for term in terms:
        matched_fields = [key for key, value in lowered.items() if term in value]
        if not matched_fields:
            continue
        weight = 4.0 if "name" in matched_fields else 2.5 if "path" in matched_fields else 1.5
        if "tags" in matched_fields or "people" in matched_fields:
            weight += 2.0
        score += weight
        reasons.append(term)
    if row.get("path") in semantic_paths:
        score += 5.0
        reasons.append("semantic")
    if row.get("summary"):
        score += 0.4
    if row.get("tags"):
        score += 0.6
    if row.get("people"):
        score += 0.8
    if row.get("evidence_ts"):
        score += 0.5
    return score, sorted(set(reasons))


def _semantic_paths(query: str, limit: int) -> set[str]:
    # Kept opt-in because it can load embedding models while other archive work is active.
    try:
        from app.chat_engine import semantic_search

        hits = semantic_search(query, max(4, min(limit, 30)))
    except Exception:
        return set()
    paths = set()
    for item in hits:
        metadata = item.get("metadata") or {}
        path = str(metadata.get("path") or item.get("id") or "")
        if path:
            paths.add(path)
    return paths


def smart_sort_candidates(query: str, *, limit: int = 80, use_semantic: bool = False) -> list[dict]:
    terms = smart_sort_terms(query)
    limit = max(1, min(int(limit or 80), 150))
    if not terms:
        return []
    like_clauses = []
    params: list[str] = []
    for term in terms:
        like = f"%{term}%"
        like_clauses.append(
            """
            LOWER(f.name) LIKE ?
            OR LOWER(f.path) LIKE ?
            OR LOWER(COALESCE(f.summary, '')) LIKE ?
            OR LOWER(COALESCE(f.extracted_text, '')) LIKE ?
            OR LOWER(COALESCE(t.name, '')) LIKE ?
            OR LOWER(COALESCE(p.display_name, '')) LIKE ?
            """
        )
        params.extend([like, like, like, like, like, like])
    semantic_paths = _semantic_paths(query, limit) if use_semantic else set()
    semantic_clause = ""
    if semantic_paths:
        placeholders = ",".join("?" for _ in semantic_paths)
        semantic_clause = f" OR f.path IN ({placeholders})"
        params.extend(sorted(semantic_paths))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
          f.id, f.path, f.rel_path, f.name, f.ext, f.category, f.size_bytes,
          f.created_ts, f.modified_ts, f.indexed_ts, f.summary,
          SUBSTR(COALESCE(f.extracted_text, ''), 1, 12000) AS extracted_text,
          f.preview_path, f.thumb_path,
          GROUP_CONCAT(DISTINCT t.name) AS tags_csv,
          GROUP_CONCAT(DISTINCT p.display_name) AS people_csv
        FROM files f
        LEFT JOIN file_tags ft ON ft.file_id = f.id
        LEFT JOIN tags t ON t.id = ft.tag_id
        LEFT JOIN face_observations fo ON fo.file_id = f.id
        LEFT JOIN person_face_links pfl
          ON (pfl.face_observation_id = fo.id OR (pfl.cluster_id IS NOT NULL AND pfl.cluster_id = fo.cluster_id))
          AND pfl.status = 'confirmed'
        LEFT JOIN people p ON p.id = pfl.person_id
        WHERE COALESCE(f.deleted_candidate, 0) = 0
          AND (({" OR ".join(f"({clause})" for clause in like_clauses)}){semantic_clause})
        GROUP BY f.id
        ORDER BY COALESCE(f.modified_ts, f.created_ts, f.indexed_ts, 0) ASC, f.id ASC
        LIMIT ?
        """,
        [*params, max(limit * 4, 200)],
    )
    rows = []
    for raw in cur.fetchall():
        row = dict(raw)
        path = row.get("path") or ""
        if not path or _review_path(path) or not is_chat_safe_source(path):
            continue
        row["tags"] = [item.strip() for item in (row.pop("tags_csv") or "").split(",") if item.strip()]
        row["people"] = [item.strip() for item in (row.pop("people_csv") or "").split(",") if item.strip()]
        ts, precision, date_match = evidence_date(" ".join([row.get("name") or "", row.get("path") or "", row.get("summary") or "", row.get("extracted_text") or ""]))
        row["evidence_ts"] = ts or row.get("modified_ts") or row.get("created_ts") or row.get("indexed_ts")
        row["date_precision"] = precision if ts else "metadata" if row.get("evidence_ts") else "unknown"
        row["date_evidence"] = date_match or ("file metadata" if row.get("evidence_ts") else "")
        row["score"], row["match_terms"] = _score_row(row, terms, semantic_paths)
        if row["score"] > 0:
            rows.append(row)
    conn.close()
    rows.sort(key=lambda item: (-float(item.get("score") or 0), float(item.get("evidence_ts") or 0), item.get("path") or ""))
    selected = rows[:limit]
    selected.sort(key=lambda item: (float(item.get("evidence_ts") or 0), item.get("path") or ""))
    return selected


def _bucket_key(item: dict) -> str:
    ts = item.get("evidence_ts")
    precision = item.get("date_precision") or "unknown"
    if not ts:
        return "undated"
    try:
        dt = datetime.fromtimestamp(float(ts))
    except (OSError, OverflowError, ValueError):
        return "undated"
    if precision == "year":
        return f"{dt.year}"
    return dt.strftime("%Y-%m-%d")


def _date_range_label(events: list[dict]) -> str:
    dated = [event.get("date_label") for event in events if event.get("key") != "undated" and event.get("date_label")]
    if not dated:
        return "undated evidence"
    if len(dated) == 1 or dated[0] == dated[-1]:
        return str(dated[0])
    return f"{dated[0]} through {dated[-1]}"


def timeline_summary(plan: dict) -> str:
    events = plan.get("events") or []
    if not events:
        return f"No connected indexed files were found for `{plan.get('query') or 'this request'}`."
    categories = sorted({category for event in events for category in event.get("categories") or []})
    people = sorted({person for event in events for person in event.get("people") or []})
    terms = sorted({term for event in events for term in event.get("connection_terms") or []})
    confidence_values = [float(event.get("confidence") or 0) for event in events]
    avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    evidence_noun = "file" if int(plan.get("file_count") or 0) == 1 else "files"
    event_noun = "event" if int(plan.get("event_count") or 0) == 1 else "events"
    parts = [
        f"The requested timeline for `{plan.get('query')}` currently reconstructs {_date_range_label(events)} from {int(plan.get('file_count') or 0):,} connected {evidence_noun} grouped into {int(plan.get('event_count') or 0):,} candidate {event_noun}.",
    ]
    if terms:
        parts.append(f"The strongest connection clues are {', '.join(terms[:8])}.")
    if categories:
        parts.append(f"The evidence mix is mostly {', '.join(categories[:6])}.")
    if people:
        parts.append(f"Confirmed people linked in the evidence include {', '.join(people[:6])}.")
    if any(event.get("key") == "undated" for event in events):
        parts.append("Some evidence is undated or has unusable metadata, so those items remain review scaffolding rather than settled chronology.")
    parts.append(f"Average event confidence is {avg_confidence:.2f}; treat this as a reviewable reconstruction, not final fact.")
    return " ".join(parts)


def build_context_timeline(query: str, *, limit: int = 80, use_semantic: bool = False, title: str | None = None) -> dict:
    files = smart_sort_candidates(query, limit=limit, use_semantic=use_semantic)
    events_by_key: dict[str, list[dict]] = {}
    for item in files:
        events_by_key.setdefault(_bucket_key(item), []).append(item)
    events = []
    for idx, (key, items) in enumerate(sorted(events_by_key.items(), key=lambda pair: (pair[0] == "undated", pair[0])), start=1):
        first = items[0]
        label = _date_label(first.get("evidence_ts"), first.get("date_precision") or "unknown", "Undated")
        terms = sorted({term for item in items for term in item.get("match_terms") or [] if term != "semantic"})
        categories = sorted({item.get("category") or "file" for item in items})
        people = sorted({person for item in items for person in item.get("people") or []})
        tags = sorted({tag for item in items for tag in item.get("tags") or []})
        events.append(
            {
                "index": idx,
                "key": key,
                "title": f"{label}: {', '.join(terms[:4]) or first.get('name') or 'Archive evidence'}",
                "date_label": label,
                "date_precision": first.get("date_precision") or "unknown",
                "file_count": len(items),
                "categories": categories,
                "people": people[:12],
                "tags": tags[:12],
                "connection_terms": terms[:12],
                "confidence": round(min(0.95, 0.35 + (len(items) * 0.08) + (len(terms) * 0.04) + (0.08 if people else 0)), 2),
                "files": [
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "id",
                            "path",
                            "rel_path",
                            "name",
                            "category",
                            "size_bytes",
                            "summary",
                            "preview_path",
                            "thumb_path",
                            "tags",
                            "people",
                            "evidence_ts",
                            "date_precision",
                            "date_evidence",
                            "match_terms",
                            "score",
                        }
                    }
                    for item in items
                ],
            }
        )
    total_bytes = sum(int(item.get("size_bytes") or 0) for item in files)
    plan = {
        "query": query,
        "title": title or f"Smart timeline - {query}".strip(),
        "terms": smart_sort_terms(query),
        "file_count": len(files),
        "event_count": len(events),
        "total_bytes": total_bytes,
        "use_semantic": bool(use_semantic),
        "events": events,
        "export_modes": ["symlink", "copy"],
    }
    plan["summary"] = timeline_summary(plan)
    return plan


def _event_markdown(event: dict) -> str:
    lines = [
        f"# {event.get('title')}",
        "",
        f"- Date: {event.get('date_label')} ({event.get('date_precision')})",
        f"- Confidence: {event.get('confidence')}",
        f"- Files: {event.get('file_count')}",
    ]
    if event.get("people"):
        lines.append(f"- People: {', '.join(event['people'])}")
    if event.get("connection_terms"):
        lines.append(f"- Connection terms: {', '.join(event['connection_terms'])}")
    lines.extend(["", "## Evidence"])
    for idx, item in enumerate(event.get("files") or [], start=1):
        lines.append(f"{idx}. `{item.get('path')}`")
        if item.get("summary"):
            lines.append(f"   - Summary: {item.get('summary')}")
        if item.get("date_evidence"):
            lines.append(f"   - Date evidence: {item.get('date_evidence')}")
        if item.get("tags"):
            lines.append(f"   - Tags: {', '.join(item.get('tags') or [])}")
    lines.append("")
    return "\n".join(lines)


def _timeline_markdown(plan: dict, export_mode: str) -> str:
    lines = [
        f"# {plan.get('title') or 'Smart Timeline'}",
        "",
        f"Query: `{plan.get('query')}`",
        f"Files: {plan.get('file_count')} | Events: {plan.get('event_count')} | Export mode: {export_mode}",
        "",
        "This is a candidate reconstruction. It groups evidence by indexed context, dates, tags, people, and folder/name clues. Treat it as a review scaffold, not settled fact.",
        "",
        "## Summary",
        "",
        plan.get("summary") or "No summary available.",
        "",
        "## Events",
    ]
    for event in plan.get("events") or []:
        lines.append(f"- {event.get('date_label')}: {event.get('title')} ({event.get('file_count')} file(s), confidence {event.get('confidence')})")
    lines.append("")
    return "\n".join(lines)


def _write_link_or_pointer(source: Path, dest: Path) -> tuple[str, str | None]:
    try:
        os.symlink(str(source), str(dest), target_is_directory=False)
        return "symlink", None
    except OSError as error:
        pointer = dest.with_suffix(dest.suffix + ".path.txt")
        pointer.write_text(str(source), encoding="utf-8")
        return "pointer", str(error)


def execute_context_export(plan: dict, *, export_mode: str = "symlink") -> dict:
    mode = "copy" if str(export_mode or "").lower() == "copy" else "symlink"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    slug = clean_filename(plan.get("title") or plan.get("query") or "smart-timeline")[:80]
    export_dir = unique_path(SMART_SORT_EXPORT_DIR / f"{stamp}-{slug}")
    events_dir = export_dir / "events"
    evidence_dir = export_dir / "evidence"
    events_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "timeline.md").write_text(_timeline_markdown(plan, mode), encoding="utf-8")
    (export_dir / "manifest.json").write_text(json.dumps(plan, indent=2, sort_keys=True, default=str), encoding="utf-8")
    exported = 0
    copied = 0
    linked = 0
    pointers = 0
    missing = 0
    failed: list[dict] = []
    for event in plan.get("events") or []:
        event_slug = clean_filename(f"{int(event.get('index') or 0):03d}-{event.get('date_label')}-{event.get('title')}")
        (events_dir / f"{event_slug}.md").write_text(_event_markdown(event), encoding="utf-8")
        event_evidence_dir = evidence_dir / event_slug
        event_evidence_dir.mkdir(parents=True, exist_ok=True)
        for idx, item in enumerate(event.get("files") or [], start=1):
            source = Path(str(item.get("path") or "")).resolve(strict=False)
            if not source.exists() or not source.is_file():
                missing += 1
                failed.append({"path": str(source), "error": "missing"})
                continue
            dest = unique_path(event_evidence_dir / f"{idx:03d}-{clean_filename(source.name)}")
            try:
                ensure_parent(dest)
                if mode == "copy":
                    shutil.copy2(source, dest)
                    copied += 1
                else:
                    result_mode, error = _write_link_or_pointer(source, dest)
                    if result_mode == "symlink":
                        linked += 1
                    else:
                        pointers += 1
                        failed.append({"path": str(source), "error": f"symlink failed; wrote pointer: {error}"})
                exported += 1
            except OSError as error:
                failed.append({"path": str(source), "error": str(error)})
    return {
        "export_dir": str(export_dir),
        "mode": mode,
        "events": len(plan.get("events") or []),
        "exported": exported,
        "copied": copied,
        "symlinked": linked,
        "pointers": pointers,
        "missing": missing,
        "failed": len(failed),
        "failures": failed[:20],
        "timeline_path": str(export_dir / "timeline.md"),
        "manifest_path": str(export_dir / "manifest.json"),
    }
