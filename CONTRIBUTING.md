# Contributing to FauxnixOS Core

## Getting Started

```bash
git clone <repo-url> fauxnix-core
cd fauxnix-core

# Option 1: Nix dev shell (recommended)
nix develop

# Option 2: Manual virtualenv
python -m venv .venv
source .venv/bin/activate
pip install -e ./packages/fauxnix-tools
pip install -e ./packages/membrie
pip install -e ./packages/archivist
```

## Dependency Rules

**This is the most important rule in the codebase:**

```
fauxnix-tools  ←  membrie
             ↖  ←  archivist

membrie ←/→ archivist  (never import each other)
```

- `fauxnix-tools` has zero dependencies on `membrie` or `archivist`
- `membrie` and `archivist` may NOT import from each other
- Both depend ONLY on `fauxnix-tools`

## Project Structure

```
packages/
├── fauxnix-tools/fauxnix_tools/
│   ├── config.py          # XDG paths, env vars, model names
│   ├── db/                # SQLite schema, get_conn(), migrations
│   ├── files/             # extraction, indexing, tagging, snapshots
│   ├── vision/            # faces (OpenCV+InsightFace), analysis, objects
│   ├── media/             # probing, storyboard, transcription
│   ├── llm/               # model router, embeddings, chat
│   ├── utils/             # hashing, MIME, file categories
│   ├── context/           # source discovery, constellation
│   └── enrichment/        # doc enrichment pipeline
├── membrie/membrie/
│   ├── awareness/         # process.py (Linux), drift.py
│   ├── session/           # lifecycle, timelines, workspaces
│   ├── chat/              # orchestrator, memory, persona
│   ├── ui/                # tray.py, window.py (PyQt6)
│   ├── web/               # otg_server.py (FastAPI)
│   ├── services.py        # 6 background daemon threads
│   └── db.py              # membrie-specific tables
└── archivist/archivist/
    ├── file_manager/       # browser, viewer, daemon, gui
    ├── smart_actions/      # classify, dedup, rename, summarize
    ├── translation/        # doc + video subtitle translation
    ├── organizer/          # rules engine, auto-organize
    ├── search/             # unified search across all sources
    └── db.py               # archivist-specific tables
```

## Code Style

- `from __future__ import annotations` at the top of every `.py` file
- Type hints on all function signatures (use `str | None`, not `Optional[str]`)
- Module-level docstrings only — no function-level docstrings
- No comments in code unless the logic is genuinely non-obvious
- Always use `pathlib.Path` for filesystem paths, never `os.path`
- Config goes through `config.py` in each package, never `os.getenv()` inline
- Database access via `fauxnix_tools.db.get_conn()`
- Lazy-import heavy dependencies (PyQt6, cv2, fitz, fastapi, insightface)
- Environment variables: `FAUXNIX_*` (shared), `MEMBRIE_*` (membrie), `ARCHIVIST_*` (archivist)

## Testing

There is no test suite yet. For now, verify code compiles:

```bash
python3 -c "
import py_compile, os
for dp,_,fs in os.walk('packages'):
    for f in fs:
        if f.endswith('.py'):
            py_compile.compile(os.path.join(dp,f), doraise=True)
print('All files OK')
"
```

## Adding a New Feature

### Adding to fauxnix-tools (shared library)
1. Create your module in `fauxnix_tools/<category>/`
2. Export public API in the `__init__.py`
3. If it needs Ollama, use `fauxnix_tools.llm.embeddings.chat_messages()`
4. If it needs DB, use `fauxnix_tools.db.get_conn()`
5. If it writes files, use paths from `fauxnix_tools.config.config`

### Adding to membrie
1. Create your module in `membrie/<category>/`
2. Import shared tools from `fauxnix_tools.<module>`
3. Add any new DB tables to `membrie.db.init_membrie_db()`
4. Add config values to `fauxnix_tools.config` or use env vars with `MEMBRIE_` prefix

### Adding to archivist
1. Create your module in `archivist/<category>/`
2. Import shared tools from `fauxnix_tools.<module>`
3. Add any new DB tables to `archivist.db.init_archivist_db()`
4. Add config values to `archivist.config` or use env vars with `ARCHIVIST_` prefix

## Database Migrations

SQLite is used for all structured data. ChromaDB for vector embeddings.

To add a new table:
1. Add `CREATE TABLE IF NOT EXISTS` to the appropriate `init_*` function
2. Add indexes for frequently queried columns
3. Use `ensure_column()` from `fauxnix_tools.db` for adding columns to existing tables

```python
from fauxnix_tools.db import get_conn, ensure_column

def init_my_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS my_table (...)")
    # Add column to existing table:
    ensure_column(cur, "existing_table", "new_column", "TEXT DEFAULT ''")
    conn.commit()
    conn.close()
```

## Nix Packaging

Each package has:
- `pyproject.toml` — Python package metadata
- `default.nix` — Nix derivation

To add a Python dependency:
1. Add to `pyproject.toml` under `dependencies`
2. Add the corresponding `python.pkgs.<name>` to `propagatedBuildInputs` in `default.nix`

## Common Mistakes

- **Don't** use `os.path.join()` — always `Path.home() / "dir" / "file"`
- **Don't** hardcode paths — always use the config object
- **Don't** import between membrie and archivist — they are separate apps
- **Don't** assume Windows — no Win32, no `C:\`, no `.exe`
- **Don't** eagerly import heavy deps — use try/except and lazy loading
- **Don't** assume GPU acceleration — CPU fallbacks exist everywhere
- **Don't** commit `__pycache__/` or `.pyc` files
