import json
import re
import time
from collections import Counter, defaultdict
from email.utils import getaddresses, parseaddr

from app.db import get_conn


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
CASE_RE = re.compile(
    r"\b(?:case|matter|docket|cause|filing|motion|order|petition)\s*(?:no\.?|#|number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-:/]{4,})\b",
    re.IGNORECASE,
)
NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b")


LEGAL_KEYWORDS = {
    "cps": 8.0,
    "children services": 8.0,
    "child protective": 8.0,
    "family court": 8.0,
    "guardian ad litem": 8.0,
    "gal": 7.0,
    "caseworker": 6.0,
    "jfs": 7.0,
    "juvenile court": 7.0,
    "custody": 6.0,
    "visitation": 5.5,
    "hearing": 5.0,
    "court order": 6.0,
    "motion": 4.5,
    "filing": 4.5,
    "attorney": 4.5,
    "counsel": 4.0,
    "subpoena": 5.0,
    "case plan": 5.5,
    "family services": 5.0,
    "child support": 5.0,
    "mediation": 4.0,
    "affidavit": 4.0,
    "summons": 4.0,
    "notice of hearing": 7.0,
    "correspondence": 2.0,
}

ARCHIVE_SIGNAL_KEYWORDS = {
    "court",
    "custody",
    "attorney",
    "lawyer",
    "hearing",
    "filing",
    "motion",
    "case",
    "cps",
    "jfs",
    "gal",
    "guardian ad litem",
    "visitation",
    "children services",
    "family services",
    "juvenile",
    "support",
    "medical",
    "school",
    "therapy",
    "timeline",
}

BULK_TERMS = {
    "unsubscribe",
    "newsletter",
    "promo",
    "promotion",
    "sale",
    "coupon",
    "deal",
    "marketing",
    "reward",
    "survey",
    "receipt",
    "tracking",
    "shipment",
    "delivery",
}

NOISE_SENDERS = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "newsletter",
    "marketing",
    "promo",
    "support",
    "notification",
}

COMMON_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "msn.com",
}

STOP_NAMES = {
    "Gmail Message",
    "Archive Awareness",
    "Google Calendar",
    "No Subject",
    "Body Not",
    "Attachment Metadata",
    "Last Import",
    "Cloud Sync",
}

DOMAIN_HINTS = {
    ".gov": 4.5,
    ".us": 1.5,
    "ohio.gov": 6.0,
    "jfs.ohio.gov": 10.0,
    "court": 5.0,
    "courts": 5.0,
    "clerk": 4.0,
    "law": 3.5,
    "legal": 3.5,
}

POSITIVE_LABEL_WEIGHTS = {
    "IMPORTANT": 4.0,
    "STARRED": 5.0,
    "SENT": 2.0,
    "CATEGORY_PERSONAL": 1.5,
    "INBOX": 0.5,
}

NEGATIVE_LABEL_WEIGHTS = {
    "CATEGORY_PROMOTIONS": -5.0,
    "CATEGORY_SOCIAL": -3.0,
    "CATEGORY_FORUMS": -2.0,
    "SPAM": -8.0,
    "TRASH": -8.0,
}

SIGNAL_LIMITS = {
    "email": 2000,
    "domain": 1000,
    "person": 1200,
    "case_number": 800,
    "keyword": 500,
}


def _now() -> float:
    return time.time()


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _safe_json_loads(value, default):
    if value in (None, ""):
        return default
    try:
        parsed = json.loads(value)
        return parsed if parsed is not None else default
    except Exception:
        return default


def _safe_json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _message_text(row) -> str:
    labels = " ".join(_safe_json_loads(row["labels_json"], []))
    parts = [
        row["subject"] or "",
        row["sender"] or "",
        row["recipients"] or "",
        row["cc"] or "",
        row["snippet"] or "",
        labels,
    ]
    return "\n".join(str(part) for part in parts if part)


def _split_email_parts(value: str) -> list[tuple[str, str]]:
    if not value:
        return []
    return [(name.strip(), email.strip().lower()) for name, email in getaddresses([value]) if email]


def _domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower().strip()


def _clean_name(value: str) -> str:
    name = re.sub(r"[\"'<>()[\]{}]", " ", str(value or ""))
    name = re.sub(r"\s+", " ", name).strip()
    if not name or name in STOP_NAMES:
        return ""
    if "@" in name:
        return ""
    if len(name) < 5 or len(name) > 80:
        return ""
    tokens = name.split()
    if len(tokens) < 2:
        return ""
    if any(token.lower() in BULK_TERMS or token.lower() in NOISE_SENDERS for token in tokens):
        return ""
    return name


def _emails(text: str) -> set[str]:
    return {match.group(0).lower() for match in EMAIL_RE.finditer(text or "")}


def _case_numbers(text: str) -> set[str]:
    values = set()
    for match in CASE_RE.finditer(text or ""):
        value = match.group(1).strip(" .,:;")
        if len(value) >= 5 and any(char.isdigit() for char in value):
            values.add(value)
    return values


def _names_from_text(text: str) -> set[str]:
    names = set()
    for match in NAME_RE.finditer(text or ""):
        name = _clean_name(match.group(0))
        if name:
            names.add(name)
    return names


def _keyword_hits(text: str) -> set[str]:
    lower = f" {_norm(text)} "
    hits = set()
    for keyword in ARCHIVE_SIGNAL_KEYWORDS:
        pattern = rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])"
        if re.search(pattern, lower):
            hits.add(keyword)
    return hits


def _append_reason(reasons: list[dict], reason: str, weight: float, source: str = "score") -> None:
    if not reason:
        return
    key = reason.lower()
    if any(item.get("reason", "").lower() == key for item in reasons):
        return
    reasons.append({"reason": reason, "weight": round(float(weight), 2), "source": source})


def _signal_key(signal_type: str, value: str, source: str) -> tuple[str, str, str]:
    return signal_type, _norm(value), source


def _add_signal(signals: dict, signal_type: str, value: str, weight: float, source: str, evidence: str = "") -> None:
    clean = str(value or "").strip()
    normalized = _norm(clean)
    if not clean or not normalized:
        return
    if signal_type == "domain" and normalized in COMMON_EMAIL_DOMAINS:
        return
    if len(normalized) < 2:
        return
    limit = SIGNAL_LIMITS.get(signal_type, 1000)
    existing_for_type = sum(1 for key in signals if key[0] == signal_type)
    if existing_for_type >= limit and _signal_key(signal_type, clean, source) not in signals:
        return
    key = _signal_key(signal_type, clean, source)
    current = signals.setdefault(
        key,
        {
            "signal_type": signal_type,
            "value": clean,
            "normalized_value": normalized,
            "source": source,
            "weight": 0.0,
            "evidence_count": 0,
            "examples": [],
        },
    )
    current["weight"] = max(float(current["weight"]), float(weight))
    current["evidence_count"] = int(current["evidence_count"]) + 1
    if evidence and len(current["examples"]) < 3:
        current["examples"].append(str(evidence)[:180])


def _extract_signals_from_text(signals: dict, text: str, source: str, base_weight: float, evidence: str = "") -> None:
    if not text:
        return
    for email in _emails(text):
        domain = _domain(email)
        _add_signal(signals, "email", email, base_weight + 2.0, source, evidence)
        if domain:
            _add_signal(signals, "domain", domain, base_weight + 1.0, source, evidence)
    for case_number in _case_numbers(text):
        _add_signal(signals, "case_number", case_number, base_weight + 5.0, source, evidence)
    for keyword in _keyword_hits(text):
        _add_signal(signals, "keyword", keyword, base_weight + 1.5, source, evidence)
    for name in _names_from_text(text):
        _add_signal(signals, "person", name, base_weight + 2.0, source, evidence)


def _extract_message_address_signals(signals: dict, row, source: str = "gmail") -> None:
    fields = [row["sender"] or "", row["recipients"] or "", row["cc"] or ""]
    for name, email in _split_email_parts(", ".join(fields)):
        domain = _domain(email)
        display = _clean_name(name or parseaddr(email)[0])
        _add_signal(signals, "email", email, 2.5, source, row["subject"] or "")
        if domain:
            _add_signal(signals, "domain", domain, 1.5, source, row["subject"] or "")
        if display:
            _add_signal(signals, "person", display, 2.0, source, row["subject"] or "")


def _seed_cold_start_signals(signals: dict) -> None:
    for keyword, weight in LEGAL_KEYWORDS.items():
        _add_signal(signals, "keyword", keyword, weight, "seed", "Cold-start legal/family-services relevance")
    for domain, weight in {
        "jfs.ohio.gov": 12.0,
        "ohio.gov": 7.0,
        "supremecourt.ohio.gov": 8.0,
    }.items():
        _add_signal(signals, "domain", domain, weight, "seed", "Cold-start public-agency relevance")


def _load_archive_signals(signals: dict, include_notes: bool = True, include_archive: bool = True) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    counts = defaultdict(int)
    if include_archive:
        cur.execute(
            """
            SELECT name, rel_path, path, summary, extracted_text
            FROM files
            WHERE COALESCE(deleted_candidate, 0) = 0
              AND id NOT IN (SELECT file_id FROM gmail_messages WHERE file_id IS NOT NULL)
            ORDER BY indexed_ts DESC, id DESC
            LIMIT 2500
            """
        )
        for row in cur.fetchall():
            text = "\n".join(
                str(part or "")
                for part in [
                    row["name"],
                    row["rel_path"],
                    row["summary"],
                    (row["extracted_text"] or "")[:3500],
                ]
            )
            _extract_signals_from_text(signals, text, "archive", 2.0, row["name"] or row["path"] or "")
            counts["archive_files"] += 1
    if include_notes:
        cur.execute(
            """
            SELECT title, content
            FROM notes
            WHERE COALESCE(status, 'active') = 'active'
            ORDER BY updated_ts DESC, id DESC
            LIMIT 1000
            """
        )
        for row in cur.fetchall():
            text = f"{row['title'] or ''}\n{row['content'] or ''}"
            _extract_signals_from_text(signals, text, "notes", 4.0, row["title"] or "note")
            counts["notes"] += 1
        cur.execute(
            """
            SELECT content, original_name
            FROM clipboard_items
            ORDER BY created_ts DESC, id DESC
            LIMIT 1000
            """
        )
        for row in cur.fetchall():
            text = f"{row['original_name'] or ''}\n{row['content'] or ''}"
            _extract_signals_from_text(signals, text, "clipboard", 3.5, row["original_name"] or "clipboard")
            counts["clipboard_items"] += 1
    try:
        cur.execute("SELECT display_name, aliases_json, notes FROM people ORDER BY updated_ts DESC, id DESC LIMIT 1000")
        for row in cur.fetchall():
            name = _clean_name(row["display_name"] or "")
            if name:
                _add_signal(signals, "person", name, 4.5, "people", "Known person")
            aliases = _safe_json_loads(row["aliases_json"], [])
            for alias in aliases if isinstance(aliases, list) else []:
                clean = _clean_name(str(alias))
                if clean:
                    _add_signal(signals, "person", clean, 4.0, "people", "Known person alias")
            _extract_signals_from_text(signals, row["notes"] or "", "people", 3.0, name or "person notes")
            counts["people"] += 1
    except Exception:
        pass
    conn.close()
    return dict(counts)


def _load_gmail_signal_context(signals: dict, include_gmail: bool = True) -> dict:
    if not include_gmail:
        return {}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM gmail_messages
        ORDER BY message_ts DESC, id DESC
        LIMIT 10000
        """
    )
    rows = cur.fetchall()
    conn.close()
    domains = Counter()
    important_domains = Counter()
    sent_domains = Counter()
    counts = defaultdict(int)
    for row in rows:
        _extract_message_address_signals(signals, row, "gmail")
        labels = set(_safe_json_loads(row["labels_json"], []))
        sender_email = parseaddr(row["sender"] or "")[1].lower()
        sender_domain = _domain(sender_email)
        if sender_domain:
            domains[sender_domain] += 1
            if "IMPORTANT" in labels or "STARRED" in labels:
                important_domains[sender_domain] += 1
            if "SENT" in labels:
                sent_domains[sender_domain] += 1
        counts["gmail_messages"] += 1
    for domain, count in important_domains.items():
        if count >= 2:
            _add_signal(signals, "domain", domain, min(7.0, 3.0 + count), "gmail_important", f"{count} important/starred message(s)")
    for domain, count in sent_domains.items():
        if count >= 2:
            _add_signal(signals, "domain", domain, min(5.0, 2.0 + count / 2), "gmail_sent", f"{count} sent message(s)")
    for domain, count in domains.items():
        if 2 <= count <= 40:
            _add_signal(signals, "domain", domain, min(3.0, 1.0 + count / 20), "gmail_seen", f"{count} local message(s)")
    return dict(counts)


def _persist_signals(signals: dict) -> None:
    now = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM relevance_signals")
    cur.execute("DELETE FROM relevance_entities")
    for item in signals.values():
        metadata = {"examples": item.get("examples") or []}
        cur.execute(
            """
            INSERT INTO relevance_signals (
                scope, signal_type, value, normalized_value, weight, source,
                evidence_count, metadata_json, updated_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope, signal_type, normalized_value, source) DO UPDATE SET
                value=excluded.value,
                weight=excluded.weight,
                evidence_count=excluded.evidence_count,
                metadata_json=excluded.metadata_json,
                updated_ts=excluded.updated_ts
            """,
            (
                "gmail",
                item["signal_type"],
                item["value"],
                item["normalized_value"],
                float(item["weight"]),
                item["source"],
                int(item["evidence_count"]),
                _safe_json_dumps(metadata),
                now,
            ),
        )
        if item["signal_type"] in {"email", "domain", "person", "case_number"}:
            cur.execute(
                """
                INSERT INTO relevance_entities (
                    entity_type, value, normalized_value, source, weight,
                    evidence_count, first_seen_ts, last_seen_ts, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, normalized_value, source) DO UPDATE SET
                    value=excluded.value,
                    weight=excluded.weight,
                    evidence_count=excluded.evidence_count,
                    last_seen_ts=excluded.last_seen_ts,
                    metadata_json=excluded.metadata_json
                """,
                (
                    item["signal_type"],
                    item["value"],
                    item["normalized_value"],
                    item["source"],
                    float(item["weight"]),
                    int(item["evidence_count"]),
                    now,
                    now,
                    _safe_json_dumps(metadata),
                ),
            )
    conn.commit()
    conn.close()


def build_relevance_profile(options: dict | None = None, *, persist: bool = True) -> dict:
    opts = options or {}
    mode = str(opts.get("mode") or "auto").strip().lower()
    include_archive = bool(opts.get("include_archive", mode != "cold_start"))
    include_notes = bool(opts.get("include_notes", True))
    include_gmail = bool(opts.get("include_gmail", True))
    signals: dict = {}
    _seed_cold_start_signals(signals)
    archive_counts = _load_archive_signals(signals, include_notes=include_notes, include_archive=include_archive)
    gmail_counts = _load_gmail_signal_context(signals, include_gmail=include_gmail)
    if persist:
        _persist_signals(signals)
    by_type = Counter(item["signal_type"] for item in signals.values())
    by_source = Counter(item["source"] for item in signals.values())
    return {
        "mode": mode,
        "signal_count": len(signals),
        "by_type": dict(by_type),
        "by_source": dict(by_source),
        "source_counts": {**archive_counts, **gmail_counts},
    }


def _domain_score(sender_domain: str, reasons: list[dict]) -> float:
    if not sender_domain:
        return 0.0
    score = 0.0
    for hint, weight in DOMAIN_HINTS.items():
        if hint.startswith("."):
            if sender_domain.endswith(hint):
                score += weight
                _append_reason(reasons, f"sender domain ends with {hint}", weight, "domain_hint")
        elif hint in sender_domain:
            score += weight
            _append_reason(reasons, f"sender domain matches {hint}", weight, "domain_hint")
    return score


def _label_score(labels: set[str], reasons: list[dict]) -> float:
    score = 0.0
    for label, weight in POSITIVE_LABEL_WEIGHTS.items():
        if label in labels:
            score += weight
            _append_reason(reasons, f"Gmail label {label}", weight, "gmail_label")
    for label, weight in NEGATIVE_LABEL_WEIGHTS.items():
        if label in labels:
            score += weight
            _append_reason(reasons, f"Gmail label {label}", weight, "gmail_label")
    return score


def _bulk_penalty(text: str, sender_email: str, reasons: list[dict]) -> float:
    lower = _norm(f"{text} {sender_email}")
    score = 0.0
    local = sender_email.split("@", 1)[0] if sender_email else ""
    for term in NOISE_SENDERS:
        if term in local:
            score -= 4.0
            _append_reason(reasons, f"bulk sender pattern `{term}`", -4.0, "noise")
            break
    hit_count = sum(1 for term in BULK_TERMS if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lower))
    if hit_count:
        penalty = min(7.0, 2.0 + hit_count)
        score -= penalty
        _append_reason(reasons, f"{hit_count} bulk-mail term(s)", -penalty, "noise")
    return score


def _keyword_score(text: str, reasons: list[dict]) -> tuple[float, list[dict]]:
    score = 0.0
    matches = []
    lower = _norm(text)
    for keyword, weight in LEGAL_KEYWORDS.items():
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        if re.search(pattern, lower):
            score += weight
            matches.append({"type": "keyword", "value": keyword, "source": "seed", "weight": weight})
            _append_reason(reasons, f"mentions `{keyword}`", weight, "keyword")
    return score, matches


def _signal_matches(row, text: str, signals: list[dict], reasons: list[dict]) -> tuple[float, list[dict]]:
    lower = _norm(text)
    sender_email = parseaddr(row["sender"] or "")[1].lower()
    sender_domain = _domain(sender_email)
    message_emails = _emails(text)
    message_domains = {_domain(email) for email in message_emails if _domain(email)}
    if sender_domain:
        message_domains.add(sender_domain)
    score = 0.0
    matches = []
    per_type = defaultdict(int)
    for signal in signals:
        signal_type = signal["signal_type"]
        normalized = signal["normalized_value"]
        if not normalized:
            continue
        matched = False
        if signal_type == "email":
            matched = normalized in message_emails
        elif signal_type == "domain":
            matched = normalized in message_domains or sender_domain.endswith(f".{normalized}")
        elif signal_type in {"person", "case_number", "keyword"}:
            matched = re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", lower) is not None
        if not matched:
            continue
        if per_type[signal_type] >= 8:
            continue
        weight = float(signal["weight"] or 0.0)
        if signal["source"] == "gmail_seen":
            weight = min(weight, 1.5)
        if signal["source"] == "gmail":
            weight = min(weight, 1.0)
        if signal_type == "keyword":
            weight = min(weight, 5.0)
        if weight <= 0:
            continue
        score += weight
        per_type[signal_type] += 1
        matches.append(
            {
                "type": signal_type,
                "value": signal["value"],
                "source": signal["source"],
                "weight": round(weight, 2),
            }
        )
        _append_reason(reasons, f"matched {signal['source']} {signal_type} `{signal['value']}`", weight, "signal")
    return score, matches


def _score_band(score: float) -> str:
    if score >= 16:
        return "strong"
    if score >= 8:
        return "maybe"
    if score >= 3:
        return "low"
    return "noise"


def _score_row(row, signals: list[dict]) -> dict:
    reasons: list[dict] = []
    matched_entities: list[dict] = []
    text = _message_text(row)
    labels = set(_safe_json_loads(row["labels_json"], []))
    sender_email = parseaddr(row["sender"] or "")[1].lower()
    sender_domain = _domain(sender_email)
    score = 0.0
    score += _label_score(labels, reasons)
    score += _domain_score(sender_domain, reasons)
    hard_relevance = bool(
        sender_domain.endswith(".gov")
        or any(hint in sender_domain for hint in ("jfs", "court", "clerk", "law", "legal"))
    )
    keyword_score, keyword_matches = _keyword_score(text, reasons)
    score += keyword_score
    matched_entities.extend(keyword_matches)
    if any(float(match.get("weight") or 0) >= 5.0 for match in keyword_matches):
        hard_relevance = True
    signal_score, signal_matches = _signal_matches(row, text, signals, reasons)
    score += signal_score
    matched_entities.extend(signal_matches)
    attachment_count = int(row["attachment_count"] or 0)
    if attachment_count:
        weight = min(6.0, 1.5 + attachment_count * 1.25)
        score += weight
        _append_reason(reasons, f"has {attachment_count} attachment(s)", weight, "attachments")
    if row["body_status"] == "downloaded":
        score += 1.0
        _append_reason(reasons, "full body already downloaded", 1.0, "body")
    bulk_score = _bulk_penalty(text, sender_email, reasons)
    score += bulk_score
    if ("CATEGORY_PROMOTIONS" in labels or bulk_score <= -4.0) and not hard_relevance:
        capped = 2.5 if "CATEGORY_PROMOTIONS" in labels else 4.0
        if score > capped:
            score = capped
            _append_reason(reasons, "bulk/promotional cap without hard case signal", -8.0, "noise")
    score = max(-20.0, min(80.0, score))
    reasons.sort(key=lambda item: abs(float(item.get("weight") or 0)), reverse=True)
    matched_entities.sort(key=lambda item: float(item.get("weight") or 0), reverse=True)
    return {
        "message_id": row["message_id"],
        "thread_id": row["thread_id"] or "",
        "gmail_message_row_id": int(row["id"]),
        "file_id": row["file_id"],
        "score": round(score, 2),
        "score_band": _score_band(score),
        "reasons": reasons[:16],
        "matched_entities": matched_entities[:24],
    }


def _candidate_row(row) -> dict:
    reasons = _safe_json_loads(row["reasons_json"], [])
    matched_entities = _safe_json_loads(row["matched_entities_json"], [])
    return {
        "message_id": row["message_id"],
        "thread_id": row["thread_id"] or "",
        "gmail_message_row_id": row["gmail_message_row_id"],
        "file_id": row["file_id"],
        "score": float(row["score"] or 0.0),
        "score_band": row["score_band"] or "noise",
        "review_status": row["review_status"] or "unreviewed",
        "user_label": row["user_label"] or "",
        "notes": row["notes"] or "",
        "subject": row["subject"] or "",
        "sender": row["sender"] or "",
        "recipients": row["recipients"] or "",
        "message_date": row["message_date"] or "",
        "message_ts": row["message_ts"],
        "snippet": row["snippet"] or "",
        "body_status": row["body_status"] or "metadata_only",
        "attachment_status": row["attachment_status"] or "unknown",
        "attachment_count": int(row["attachment_count"] or 0),
        "reasons": reasons if isinstance(reasons, list) else [],
        "matched_entities": matched_entities if isinstance(matched_entities, list) else [],
        "updated_ts": row["candidate_updated_ts"],
    }


def _candidate_summary(cur) -> dict:
    cur.execute(
        """
        SELECT score_band, COUNT(*) AS count
        FROM gmail_candidate_scores
        GROUP BY score_band
        """
    )
    by_band = {row["score_band"] or "noise": int(row["count"] or 0) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT review_status, COUNT(*) AS count
        FROM gmail_candidate_scores
        GROUP BY review_status
        """
    )
    by_review = {row["review_status"] or "unreviewed": int(row["count"] or 0) for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS count FROM gmail_candidate_scores")
    total = int(cur.fetchone()["count"] or 0)
    cur.execute("SELECT COUNT(*) AS count FROM gmail_messages")
    message_total = int(cur.fetchone()["count"] or 0)
    cur.execute("SELECT COUNT(*) AS count FROM relevance_signals")
    signal_total = int(cur.fetchone()["count"] or 0)
    cur.execute("SELECT MAX(updated_ts) AS updated_ts FROM gmail_candidate_scores")
    updated = cur.fetchone()["updated_ts"]
    return {
        "total_count": total,
        "gmail_message_count": message_total,
        "signal_count": signal_total,
        "by_band": by_band,
        "by_review_status": by_review,
        "last_scored_ts": updated,
    }


def list_gmail_relevance_candidates(
    *,
    score_band: str | None = None,
    review_status: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    limit: int = 80,
) -> dict:
    clauses = []
    params: list = []
    if score_band:
        clauses.append("c.score_band = ?")
        params.append(score_band)
    if review_status:
        clauses.append("c.review_status = ?")
        params.append(review_status)
    if min_score is not None:
        clauses.append("c.score >= ?")
        params.append(float(min_score))
    q = str(query or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append(
            "(m.subject LIKE ? OR m.sender LIKE ? OR m.recipients LIKE ? OR m.cc LIKE ? OR m.snippet LIKE ? OR c.reasons_json LIKE ? OR c.matched_entities_json LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            c.*,
            c.updated_ts AS candidate_updated_ts,
            m.subject, m.sender, m.recipients, m.cc, m.message_date,
            m.message_ts, m.snippet, m.body_status, m.attachment_status,
            m.attachment_count
        FROM gmail_candidate_scores c
        LEFT JOIN gmail_messages m ON m.message_id = c.message_id
        {where}
        ORDER BY c.score DESC, m.message_ts DESC, c.updated_ts DESC
        LIMIT ?
        """,
        [*params, max(1, min(int(limit or 80), 1000))],
    )
    candidates = [_candidate_row(row) for row in cur.fetchall()]
    summary = _candidate_summary(cur)
    conn.close()
    return {"candidates": candidates, "summary": summary}


def _candidate_filter_sql(options: dict | None = None) -> tuple[list[str], list]:
    opts = options or {}
    clauses = []
    params: list = []
    message_ids = opts.get("message_ids") or []
    if message_ids:
        clean_ids = [str(item).strip() for item in message_ids if str(item).strip()]
        if clean_ids:
            placeholders = ",".join("?" for _ in clean_ids)
            clauses.append(f"c.message_id IN ({placeholders})")
            params.extend(clean_ids)
    review_status = str(opts.get("review_status") or "").strip()
    if review_status:
        clauses.append("c.review_status = ?")
        params.append(review_status)
    score_band = str(opts.get("score_band") or "").strip()
    if score_band:
        clauses.append("c.score_band = ?")
        params.append(score_band)
    if opts.get("min_score") is not None:
        clauses.append("c.score >= ?")
        params.append(float(opts.get("min_score")))
    query = str(opts.get("query") or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append(
            "(m.subject LIKE ? OR m.sender LIKE ? OR m.recipients LIKE ? OR m.cc LIKE ? OR m.snippet LIKE ? OR c.reasons_json LIKE ? OR c.matched_entities_json LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])
    return clauses, params


def select_gmail_relevance_body_targets(options: dict | None = None) -> dict:
    opts = options or {}
    limit = max(1, min(int(opts.get("limit") or 25), 1000))
    clauses, params = _candidate_filter_sql(opts)
    clauses.append("COALESCE(m.body_status, 'metadata_only') = 'metadata_only'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            c.message_id,
            c.score,
            c.score_band,
            c.review_status,
            m.id AS gmail_message_row_id,
            m.subject,
            m.sender,
            m.body_status,
            m.attachment_count
        FROM gmail_candidate_scores c
        JOIN gmail_messages m ON m.message_id = c.message_id
        {where}
        ORDER BY c.score DESC, m.message_ts DESC, c.updated_ts DESC
        LIMIT ?
        """,
        [*params, limit],
    )
    rows = [dict(row) for row in cur.fetchall()]
    summary = _candidate_summary(cur)
    conn.close()
    return {
        "message_ids": [row["message_id"] for row in rows],
        "gmail_message_row_ids": [int(row["gmail_message_row_id"]) for row in rows],
        "selected_count": len(rows),
        "targets": rows,
        "summary": summary,
    }


def select_gmail_relevance_attachment_targets(options: dict | None = None) -> dict:
    opts = options or {}
    limit = max(1, min(int(opts.get("limit") or 25), 1000))
    status = str(opts.get("attachment_status") or "pending").strip() or "pending"
    clauses, params = _candidate_filter_sql(opts)
    clauses.append("a.status = ?")
    params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            c.message_id,
            c.score,
            c.score_band,
            c.review_status,
            a.id AS gmail_attachment_row_id,
            a.filename,
            a.mime_type,
            a.size_bytes,
            m.subject,
            m.sender
        FROM gmail_candidate_scores c
        JOIN gmail_messages m ON m.message_id = c.message_id
        JOIN gmail_attachments a ON a.message_id = c.message_id
        {where}
        ORDER BY c.score DESC, m.message_ts DESC, a.id DESC
        LIMIT ?
        """,
        [*params, limit],
    )
    rows = [dict(row) for row in cur.fetchall()]
    summary = _candidate_summary(cur)
    conn.close()
    return {
        "message_ids": [row["message_id"] for row in rows],
        "gmail_attachment_row_ids": [int(row["gmail_attachment_row_id"]) for row in rows],
        "selected_count": len(rows),
        "targets": rows,
        "summary": summary,
    }


def gmail_relevance_status(limit: int = 12) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    summary = _candidate_summary(cur)
    conn.close()
    payload = list_gmail_relevance_candidates(min_score=3, limit=limit)
    summary = {**summary, **payload["summary"]}
    if not summary["gmail_message_count"]:
        state = "no_gmail_metadata"
        message = "Import Gmail headers/snippets first. No relevance score can be built yet."
    elif not summary["total_count"]:
        state = "not_scored"
        message = "Gmail metadata is present. Run relevance scoring to find likely important messages."
    else:
        state = "ready"
        strong = summary["by_band"].get("strong", 0)
        maybe = summary["by_band"].get("maybe", 0)
        message = f"Relevance scoring is ready: {strong} strong and {maybe} maybe candidate(s)."
    return {
        "state": state,
        "summary_text": message,
        "summary": summary,
        "candidates": payload["candidates"],
    }


def score_gmail_relevance(options: dict | None = None) -> dict:
    opts = options or {}
    profile = build_relevance_profile(opts, persist=True)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM relevance_signals ORDER BY weight DESC, evidence_count DESC")
    signals = [dict(row) for row in cur.fetchall()]
    clauses = []
    params: list = []
    q = str(opts.get("query") or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(subject LIKE ? OR sender LIKE ? OR recipients LIKE ? OR cc LIKE ? OR snippet LIKE ? OR labels_json LIKE ?)")
        params.extend([like, like, like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = opts.get("limit")
    limit_clause = ""
    if limit:
        limit_clause = "LIMIT ?"
        params.append(max(1, min(int(limit), 100000)))
    cur.execute(
        f"""
        SELECT *
        FROM gmail_messages
        {where}
        ORDER BY message_ts DESC, id DESC
        {limit_clause}
        """,
        params,
    )
    rows = cur.fetchall()
    now = _now()
    scored = []
    for row in rows:
        item = _score_row(row, signals)
        scored.append(item)
        cur.execute("SELECT review_status, user_label, notes, created_ts FROM gmail_candidate_scores WHERE message_id = ?", (item["message_id"],))
        existing = cur.fetchone()
        cur.execute(
            """
            INSERT INTO gmail_candidate_scores (
                message_id, thread_id, gmail_message_row_id, file_id, score, score_band,
                reasons_json, matched_entities_json, review_status, user_label, notes,
                created_ts, updated_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id=excluded.thread_id,
                gmail_message_row_id=excluded.gmail_message_row_id,
                file_id=excluded.file_id,
                score=excluded.score,
                score_band=excluded.score_band,
                reasons_json=excluded.reasons_json,
                matched_entities_json=excluded.matched_entities_json,
                review_status=excluded.review_status,
                user_label=excluded.user_label,
                notes=excluded.notes,
                updated_ts=excluded.updated_ts
            """,
            (
                item["message_id"],
                item["thread_id"],
                item["gmail_message_row_id"],
                item["file_id"],
                item["score"],
                item["score_band"],
                _safe_json_dumps(item["reasons"]),
                _safe_json_dumps(item["matched_entities"]),
                existing["review_status"] if existing else "unreviewed",
                existing["user_label"] if existing else None,
                existing["notes"] if existing else None,
                existing["created_ts"] if existing else now,
                now,
            ),
        )
    conn.commit()
    summary = _candidate_summary(cur)
    conn.close()
    min_score = opts.get("min_score")
    candidates = list_gmail_relevance_candidates(
        min_score=float(min_score) if min_score is not None else 3.0,
        query=q or None,
        limit=80,
    )
    bands = Counter(item["score_band"] for item in scored)
    return {
        "scored_count": len(scored),
        "by_band": dict(bands),
        "profile": profile,
        "summary": summary,
        "candidates": candidates["candidates"],
        "state": "ready" if scored else "no_matches",
    }


def review_gmail_relevance_candidate(message_id: str, payload: dict | None = None) -> dict:
    clean_id = str(message_id or "").strip()
    if not clean_id:
        raise ValueError("A Gmail message id is required.")
    data = payload or {}
    status = str(data.get("review_status") or "reviewed").strip().lower()
    allowed = {"unreviewed", "important", "not_relevant", "maybe", "reviewed", "download_body", "download_attachments"}
    if status not in allowed:
        raise ValueError(f"review_status must be one of: {', '.join(sorted(allowed))}.")
    user_label = str(data.get("user_label") or "").strip() or None
    notes = str(data.get("notes") or "").strip() or None
    now = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT message_id FROM gmail_candidate_scores WHERE message_id = ?", (clean_id,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("Candidate has not been scored yet.")
    cur.execute(
        """
        UPDATE gmail_candidate_scores
        SET review_status = ?, user_label = ?, notes = ?, updated_ts = ?
        WHERE message_id = ?
        """,
        (status, user_label, notes, now, clean_id),
    )
    cur.execute(
        """
        INSERT INTO relevance_review_decisions (target_type, target_id, decision, notes, created_ts)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gmail_message", clean_id, status, notes or user_label or "", now),
    )
    conn.commit()
    conn.close()
    result = list_gmail_relevance_candidates(query=clean_id, limit=1)
    return {"candidate": result["candidates"][0] if result["candidates"] else None, "summary": result["summary"]}
