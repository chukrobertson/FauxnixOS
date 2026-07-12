# Phase 4: Embedding Pipeline + Topic Clustering

## Objective

Turn raw activity events from Phase 3 into topic vectors, workspace similarity scores, drift detection, and workspace overlap detection. Runs on the base system.

## Deliverables

- `fennix.embeddings` module (extending `fauxnix_tools.llm.embeddings`)
- Background service that processes activity logs
- Topic cluster assignments per workspace
- Drift detection (workspace activity shifting from its known topic)
- Overlap detection (two workspaces active on similar topics)

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                  Base System                           │
│                                                        │
│  ┌──────────────┐    ┌──────────────┐                 │
│  │ ctx-aggregator│   │ embed-pipeline│                │
│  │ reads sockets │──▶│ textify       │                │
│  │ from all ws   │   │ embed         │                │
│  └──────────────┘    │ store vectors │                │
│                       │ cluster       │                │
│                       └──────┬───────┘                 │
│                              │                         │
│                  ┌───────────▼──────────┐              │
│                  │   SQLite + sqlite-vec│              │
│                  │   workspace_vectors  │              │
│                  │   topic_clusters     │              │
│                  │   drift_events       │              │
│                  └──────────────────────┘              │
│                              │                         │
│                  ┌───────────▼──────────┐              │
│                  │   Fennix Assistant   │  (Phase 5)  │
│                  │   reads cluster data │              │
│                  └──────────────────────┘              │
└───────────────────────────────────────────────────────┘
```

## Tasks

### 4.1 Activity Summarization (Textify)

Every 5 minutes, for each active workspace:

1. Collect all events in the window
2. Aggregate by source, picking the most significant per source
3. Textify into a natural language summary:

```
Input events:
  window: zathura "attention_is_all_you_need.pdf" (25min)
  file: modify /shared/notes/attention.md
  terminal: python train.py --epochs 100
  git: commit "Add multi-head attention" on branch experiment-1
  browser: arxiv.org "Attention Is All You Need"

Output summary:
  "Working in workspace 'ml-paper'. Reading 'attention_is_all_you_need.pdf'
   in zathura. Modified file attention.md. Ran 'python train.py --epochs 100'.
   Committed 'Add multi-head attention' on branch experiment-1.
   Browsing arXiv for attention mechanism papers."
```

### 4.2 Embedding

Run the textified summary through an embedding model:

```python
from fauxnix_tools.llm.embeddings import embed_text

summary = textify_events(events)  # from 4.1
vector = embed_text(summary)      # → 384-dim float vector (all-MiniLM-L6-v2)
```

Model: `all-MiniLM-L6-v2` (~80MB, CPU inference, ~5ms per embedding)
Fallback: `nomic-embed-text` via Ollama (if sentence-transformers not available)

### 4.3 Vector Storage

SQLite table with `sqlite-vec` extension:

```sql
CREATE TABLE workspace_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    vector BLOB NOT NULL,        -- serialized float32 array
    text_summary TEXT NOT NULL,
    activity_window_start TEXT,
    activity_window_end TEXT
);

CREATE VIRTUAL TABLE workspace_vectors_embedding USING vec0(
    vector float[384]
);
```

### 4.4 Topic Clustering

For each workspace, maintain an exponential moving average (EMA) of its vector:

```
ema[t] = alpha * new_vector + (1 - alpha) * ema[t-1]
alpha = 0.3  (recent activity weighted)
```

Cluster workspaces:
- Compute cosine similarity between all workspace EMA vectors
- Workspaces with similarity > 0.7 are "related"
- Workspaces with similarity > 0.85 are "highly overlapping"

Store cluster assignments:

```sql
CREATE TABLE topic_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    cluster_label TEXT,          -- auto-generated topic label
    topic_keywords TEXT,         -- "ml, research, transformers"
    confidence REAL,
    updated_at TEXT
);
```

### 4.5 Topic Labeling

Use the lightweight LLM (qwen2.5:1.5b via Ollama) to generate topic labels for each cluster.
This runs infrequently (every 6 hours or on manual trigger) and is cached.

```
Prompt: "Given these activity summaries, generate 3-5 topic keywords
         for this workspace:
         [summary 1]
         [summary 2]
         [summary 3]

         Output format: keyword1, keyword2, keyword3"

Response: "machine-learning, transformers, paper-writing"
```

### 4.6 Drift Detection

Maintain a rolling window of recent vectors per workspace (last 2 hours).

```python
def detect_drift(workspace_id: str) -> DriftResult | None:
    ema = get_workspace_ema(workspace_id)
    recent = get_recent_vectors(workspace_id, hours=2)

    if not recent:
        return None

    avg_recent = np.mean(recent, axis=0)
    similarity = cosine_similarity(ema, avg_recent)

    if similarity < 0.5:
        # Find nearest workspace to avg_recent
        nearest = find_nearest_workspace(avg_recent, exclude=workspace_id)
        return DriftResult(
            workspace_id=workspace_id,
            original_topic=ema.topic_label,
            drifted_toward=nearest.topic_label,
            nearest_workspace=nearest.workspace_id,
            similarity=scores.similarity,
        )

    return None
```

When drift is detected, queue a suggestion for Phase 5.
If the recent vector is closest to an EXISTING workspace → suggest merge.
If the recent vector doesn't match any existing workspace well → suggest fork.

### 4.7 Overlap Detection

Runs periodically (every 30 min):

```python
def detect_overlaps() -> list[OverlapResult]:
    ema_vectors = get_all_workspace_emas()
    results = []

    for ws1, ws2 in combinations(ema_vectors, 2):
        similarity = cosine_similarity(ws1.vector, ws2.vector)
        if similarity > 0.75:
            results.append(OverlapResult(
                workspace_a=ws1.id,
                workspace_b=ws2.id,
                similarity=similarity,
                shared_topic=find_common_keywords(ws1, ws2),
            ))

    return sorted(results, key=lambda r: r.similarity, reverse=True)
```

### 4.8 Integration with Fennix

New `fennix.embeddings` module, following existing project patterns:

```
packages/fennix/fennix/embeddings/
├── __init__.py
├── textify.py       # Event → text summary
├── pipeline.py      # Embedding + storage pipeline
├── clustering.py    # EMA, similarity, cluster assignment
├── drift.py         # Drift detection logic
└── overlap.py       # Workspace overlap detection
```

Uses `fauxnix_tools.llm.embeddings` for embedding and `fauxnix_tools.db` for storage.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Embedding model | all-MiniLM-L6-v2 (sentence-transformers) | Fast CPU inference, small, good enough for topic detection |
| Fallback embedding | nomic-embed-text (Ollama) | Already in the stack, zero additional dependencies |
| Vector DB | SQLite + sqlite-vec | Single-file, no daemon, already use SQLite |
| EMA alpha | 0.3 | Favors recent activity without over-fitting to noise |
| Drift threshold | cosine similarity < 0.5 | Conservative — fewer false positives |
| Overlap threshold | cosine similarity > 0.75 | Moderately aggressive — catches meaningful overlaps |
| Topic labeling | qwen2.5:1.5b via Ollama | Already configured in Fennix stack |

## Success Criteria

- [ ] Activity events are aggregated and textified every 5 minutes
- [ ] Textified summaries produce meaningful embeddings
- [ ] Workspace EMA vectors converge to stable topic representation within ~2 hours of consistent activity
- [ ] Drift detection fires when user switches from coding → browsing in same workspace
- [ ] Overlap detection identifies two workspaces working on same topic
- [ ] Topic labels generated by LLM are accurate (keyword matches topic)
- [ ] sqlite-vec queries return similar workspace vectors in < 100ms
