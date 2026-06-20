from __future__ import annotations

import json
import time

from app.autotagging import apply_person_tag_to_files
from app.db import get_conn


PERSON_SENSITIVITIES = {"normal", "private", "restricted", "hidden"}
FACE_LINK_STATUSES = {"confirmed", "rejected", "tentative", "needs_review"}
EVENT_STATUSES = {"candidate", "confirmed", "rejected", "merged", "needs_review"}
DATE_PRECISIONS = {"exact", "day", "month", "year", "range", "unknown", "inferred"}


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _json_dict(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        return None


def _row(row) -> dict | None:
    return dict(row) if row else None


def _person_row(row) -> dict:
    item = dict(row)
    item["aliases"] = _json_list(item.pop("aliases_json", "[]"))
    return item


def _face_row(row) -> dict:
    item = dict(row)
    item["bbox"] = _json_dict(item.pop("bbox_json", None))
    return item


def _clamp_confidence(value: float | None) -> float:
    try:
        return max(0.0, min(float(value if value is not None else 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def clean_status(value: str | None, allowed: set[str], default: str) -> str:
    item = (value or default).strip().lower()
    return item if item in allowed else default


def clean_text(value: str | None, *, required: bool = False, label: str = "value") -> str:
    text = (value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    return text


def timeline_overview() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    tables = [
        "people",
        "face_observations",
        "person_face_links",
        "timeline_events",
        "timeline_event_evidence",
        "timeline_event_people",
    ]
    counts = {}
    for table in tables:
        cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
        counts[table] = int(cur.fetchone()["count"] or 0)
    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM timeline_events
        GROUP BY status
        ORDER BY status
        """
    )
    event_statuses = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"counts": counts, "event_statuses": event_statuses}


def create_person(req) -> dict:
    display_name = clean_text(req.display_name, required=True, label="display_name")
    aliases = [clean_text(alias) for alias in (req.aliases or []) if clean_text(alias)]
    sensitivity = clean_status(req.sensitivity, PERSON_SENSITIVITIES, "normal")
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO people (display_name, aliases_json, notes, sensitivity, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (display_name, json.dumps(aliases), clean_text(req.notes), sensitivity, now, now),
    )
    person_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM people WHERE id = ?", (person_id,))
    person = _person_row(cur.fetchone())
    conn.close()
    return person


def update_person(person_id: int, req) -> dict:
    updates = []
    params = []
    if req.display_name is not None:
        updates.append("display_name = ?")
        params.append(clean_text(req.display_name, required=True, label="display_name"))
    if req.aliases is not None:
        aliases = [clean_text(alias) for alias in req.aliases if clean_text(alias)]
        updates.append("aliases_json = ?")
        params.append(json.dumps(aliases))
    if req.notes is not None:
        updates.append("notes = ?")
        params.append(clean_text(req.notes))
    if req.sensitivity is not None:
        updates.append("sensitivity = ?")
        params.append(clean_status(req.sensitivity, PERSON_SENSITIVITIES, "normal"))
    if not updates:
        person = get_person(person_id)
        if not person:
            raise ValueError("Person not found")
        return person
    updates.append("updated_ts = ?")
    params.append(time.time())
    params.append(int(person_id))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE people SET {', '.join(updates)} WHERE id = ?", params)
    if cur.rowcount == 0:
        conn.close()
        raise ValueError("Person not found")
    conn.commit()
    cur.execute("SELECT * FROM people WHERE id = ?", (int(person_id),))
    person = _person_row(cur.fetchone())
    conn.close()
    return person


def get_person(person_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE id = ?", (int(person_id),))
    row = cur.fetchone()
    conn.close()
    return _person_row(row) if row else None


def list_people(q: str | None = None, limit: int = 80) -> dict:
    limit = max(1, min(int(limit or 80), 300))
    conn = get_conn()
    cur = conn.cursor()
    if q:
        pattern = f"%{q.strip()}%"
        cur.execute(
            """
            SELECT p.*,
                   COUNT(DISTINCT pfl.id) AS face_link_count,
                   COUNT(DISTINCT tep.event_id) AS event_count
            FROM people p
            LEFT JOIN person_face_links pfl ON pfl.person_id = p.id
            LEFT JOIN timeline_event_people tep ON tep.person_id = p.id
            WHERE p.display_name LIKE ? OR p.aliases_json LIKE ? OR p.notes LIKE ?
            GROUP BY p.id
            ORDER BY p.display_name COLLATE NOCASE
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        )
    else:
        cur.execute(
            """
            SELECT p.*,
                   COUNT(DISTINCT pfl.id) AS face_link_count,
                   COUNT(DISTINCT tep.event_id) AS event_count
            FROM people p
            LEFT JOIN person_face_links pfl ON pfl.person_id = p.id
            LEFT JOIN timeline_event_people tep ON tep.person_id = p.id
            GROUP BY p.id
            ORDER BY p.display_name COLLATE NOCASE
            LIMIT ?
            """,
            (limit,),
        )
    people = []
    for row in cur.fetchall():
        item = _person_row(row)
        item["face_link_count"] = int(item.get("face_link_count") or 0)
        item["event_count"] = int(item.get("event_count") or 0)
        people.append(item)
    conn.close()
    return {"people": people, "limit": limit}


def create_face_observation(req) -> dict:
    path = clean_text(req.path, required=True, label="path")
    media_type = clean_status(req.media_type, {"image", "video"}, "image")
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO face_observations (
            file_id, path, media_type, frame_seconds, bbox_json, crop_path,
            embedding_ref, detection_confidence, cluster_id, source, created_ts, updated_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            req.file_id,
            path,
            media_type,
            req.frame_seconds,
            json.dumps(req.bbox) if req.bbox else None,
            clean_text(req.crop_path) or None,
            clean_text(req.embedding_ref) or None,
            _clamp_confidence(req.detection_confidence) if req.detection_confidence is not None else None,
            clean_text(req.cluster_id) or None,
            clean_text(getattr(req, "source", None)) or "manual",
            now,
            now,
        ),
    )
    observation_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM face_observations WHERE id = ?", (observation_id,))
    observation = _face_row(cur.fetchone())
    conn.close()
    return observation


def list_face_observations(
    *,
    person_id: int | None = None,
    cluster_id: str | None = None,
    file_id: int | None = None,
    limit: int = 120,
) -> dict:
    limit = max(1, min(int(limit or 120), 500))
    clauses = []
    params = []
    join = ""
    if person_id:
        join = "JOIN person_face_links pfl ON pfl.face_observation_id = fo.id"
        clauses.append("pfl.person_id = ?")
        params.append(int(person_id))
    if cluster_id:
        clauses.append("fo.cluster_id = ?")
        params.append(cluster_id)
    if file_id:
        clauses.append("fo.file_id = ?")
        params.append(int(file_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT fo.*
        FROM face_observations fo
        {join}
        {where}
        ORDER BY fo.created_ts DESC, fo.id DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    observations = [_face_row(row) for row in cur.fetchall()]
    conn.close()
    return {"face_observations": observations, "limit": limit}


def link_person_face(req) -> dict:
    if not req.face_observation_id and not clean_text(req.cluster_id):
        raise ValueError("Provide a face_observation_id or cluster_id")
    status = clean_status(req.status, FACE_LINK_STATUSES, "confirmed")
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM people WHERE id = ?", (int(req.person_id),))
    if not cur.fetchone():
        conn.close()
        raise ValueError("Person not found")
    if req.face_observation_id:
        cur.execute("SELECT id FROM face_observations WHERE id = ?", (int(req.face_observation_id),))
        if not cur.fetchone():
            conn.close()
            raise ValueError("Face observation not found")
    cur.execute(
        """
        INSERT INTO person_face_links (
            person_id, face_observation_id, cluster_id, status, confidence, source, created_ts, updated_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(req.person_id),
            req.face_observation_id,
            clean_text(req.cluster_id) or None,
            status,
            _clamp_confidence(req.confidence),
            clean_text(req.source) or "user",
            now,
            now,
        ),
    )
    link_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM person_face_links WHERE id = ?", (link_id,))
    link = dict(cur.fetchone())
    tagged_files: list[int] = []
    if status == "confirmed":
        if req.face_observation_id:
            cur.execute("SELECT file_id FROM face_observations WHERE id = ?", (int(req.face_observation_id),))
            row = cur.fetchone()
            if row and row["file_id"]:
                tagged_files.append(int(row["file_id"]))
        if clean_text(req.cluster_id):
            cur.execute(
                """
                SELECT DISTINCT file_id
                FROM face_observations
                WHERE cluster_id = ? AND file_id IS NOT NULL
                """,
                (clean_text(req.cluster_id),),
            )
            tagged_files.extend(int(row["file_id"]) for row in cur.fetchall() if row["file_id"])
    conn.close()
    if tagged_files:
        link["person_file_tag"] = apply_person_tag_to_files(int(req.person_id), tagged_files)
        try:
            from app.chat_engine import sync_file_embedding_by_id

            link["embedding_sync"] = [sync_file_embedding_by_id(file_id) for file_id in sorted(set(tagged_files))]
        except Exception as error:
            link["embedding_sync"] = {"error": str(error)}
    return link


def create_timeline_event(req) -> dict:
    title = clean_text(req.title, required=True, label="title")
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO timeline_events (
            title, summary, start_ts, end_ts, date_precision, location_text,
            confidence, status, uncertainty_notes, created_ts, updated_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            clean_text(req.summary),
            req.start_ts,
            req.end_ts,
            clean_status(req.date_precision, DATE_PRECISIONS, "unknown"),
            clean_text(req.location_text),
            _clamp_confidence(req.confidence),
            clean_status(req.status, EVENT_STATUSES, "candidate"),
            clean_text(req.uncertainty_notes),
            now,
            now,
        ),
    )
    event_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return get_timeline_event(event_id) or {"id": event_id}


def update_timeline_event(event_id: int, req) -> dict:
    fields = []
    params = []
    if req.title is not None:
        fields.append("title = ?")
        params.append(clean_text(req.title, required=True, label="title"))
    if req.summary is not None:
        fields.append("summary = ?")
        params.append(clean_text(req.summary))
    if req.start_ts is not None:
        fields.append("start_ts = ?")
        params.append(req.start_ts)
    if req.end_ts is not None:
        fields.append("end_ts = ?")
        params.append(req.end_ts)
    if req.date_precision is not None:
        fields.append("date_precision = ?")
        params.append(clean_status(req.date_precision, DATE_PRECISIONS, "unknown"))
    if req.location_text is not None:
        fields.append("location_text = ?")
        params.append(clean_text(req.location_text))
    if req.confidence is not None:
        fields.append("confidence = ?")
        params.append(_clamp_confidence(req.confidence))
    if req.status is not None:
        fields.append("status = ?")
        params.append(clean_status(req.status, EVENT_STATUSES, "candidate"))
    if req.uncertainty_notes is not None:
        fields.append("uncertainty_notes = ?")
        params.append(clean_text(req.uncertainty_notes))
    if not fields:
        event = get_timeline_event(event_id)
        if not event:
            raise ValueError("Timeline event not found")
        return event
    fields.append("updated_ts = ?")
    params.append(time.time())
    params.append(int(event_id))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE timeline_events SET {', '.join(fields)} WHERE id = ?", params)
    if cur.rowcount == 0:
        conn.close()
        raise ValueError("Timeline event not found")
    conn.commit()
    conn.close()
    return get_timeline_event(event_id) or {"id": event_id}


def _event_people(cur, event_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT tep.event_id, tep.person_id, tep.role, tep.confidence, p.display_name
        FROM timeline_event_people tep
        JOIN people p ON p.id = tep.person_id
        WHERE tep.event_id = ?
        ORDER BY p.display_name COLLATE NOCASE, tep.role
        """,
        (int(event_id),),
    )
    return [dict(row) for row in cur.fetchall()]


def _event_evidence(cur, event_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT *
        FROM timeline_event_evidence
        WHERE event_id = ?
        ORDER BY confidence DESC, id ASC
        """,
        (int(event_id),),
    )
    return [dict(row) for row in cur.fetchall()]


def get_timeline_event(event_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM timeline_events WHERE id = ?", (int(event_id),))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    event = dict(row)
    event["people"] = _event_people(cur, int(event_id))
    event["evidence"] = _event_evidence(cur, int(event_id))
    conn.close()
    return event


def list_timeline_events(
    *,
    q: str | None = None,
    person_id: int | None = None,
    status: str | None = None,
    limit: int = 80,
) -> dict:
    limit = max(1, min(int(limit or 80), 300))
    joins = []
    clauses = []
    params = []
    if person_id:
        joins.append("JOIN timeline_event_people tep_filter ON tep_filter.event_id = te.id")
        clauses.append("tep_filter.person_id = ?")
        params.append(int(person_id))
    if status:
        clauses.append("te.status = ?")
        params.append(clean_status(status, EVENT_STATUSES, "candidate"))
    if q:
        pattern = f"%{q.strip()}%"
        clauses.append(
            "(te.title LIKE ? OR te.summary LIKE ? OR te.location_text LIKE ? OR te.uncertainty_notes LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT te.*,
               COUNT(DISTINCT tee.id) AS evidence_count,
               COUNT(DISTINCT tep.person_id) AS people_count
        FROM timeline_events te
        {' '.join(joins)}
        LEFT JOIN timeline_event_evidence tee ON tee.event_id = te.id
        LEFT JOIN timeline_event_people tep ON tep.event_id = te.id
        {where}
        GROUP BY te.id
        ORDER BY COALESCE(te.start_ts, te.created_ts) DESC, te.id DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    events = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"events": events, "limit": limit}


def add_event_evidence(event_id: int, req) -> dict:
    evidence_type = clean_text(req.evidence_type, required=True, label="evidence_type")
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM timeline_events WHERE id = ?", (int(event_id),))
    if not cur.fetchone():
        conn.close()
        raise ValueError("Timeline event not found")
    cur.execute(
        """
        INSERT INTO timeline_event_evidence (
            event_id, evidence_type, evidence_id, path, quote, description, confidence, created_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(event_id),
            evidence_type,
            req.evidence_id,
            clean_text(req.path),
            clean_text(req.quote),
            clean_text(req.description),
            _clamp_confidence(req.confidence),
            now,
        ),
    )
    evidence_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM timeline_event_evidence WHERE id = ?", (evidence_id,))
    evidence = dict(cur.fetchone())
    conn.close()
    return evidence


def add_event_person(event_id: int, req) -> dict:
    role = clean_text(req.role) or "unknown"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM timeline_events WHERE id = ?", (int(event_id),))
    if not cur.fetchone():
        conn.close()
        raise ValueError("Timeline event not found")
    cur.execute("SELECT id FROM people WHERE id = ?", (int(req.person_id),))
    if not cur.fetchone():
        conn.close()
        raise ValueError("Person not found")
    cur.execute(
        """
        INSERT OR REPLACE INTO timeline_event_people (event_id, person_id, role, confidence)
        VALUES (?, ?, ?, ?)
        """,
        (int(event_id), int(req.person_id), role, _clamp_confidence(req.confidence)),
    )
    conn.commit()
    cur.execute(
        """
        SELECT tep.event_id, tep.person_id, tep.role, tep.confidence, p.display_name
        FROM timeline_event_people tep
        JOIN people p ON p.id = tep.person_id
        WHERE tep.event_id = ? AND tep.person_id = ? AND tep.role = ?
        """,
        (int(event_id), int(req.person_id), role),
    )
    item = dict(cur.fetchone())
    conn.close()
    return item
