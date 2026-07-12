# Archivist

**AI-powered intelligent file manager for FauxnixOS.**

Archivist is the default file manager for FauxnixOS. It combines traditional file browsing with AI-powered features: smart classification, duplicate detection, LLM-powered rename suggestions, media translation, face-aware search, and automated organization rules.

## What Archivist Does

- **Browse files** — traditional file manager with category colors, sorting, filtering
- **Preview files** — text, code, images (with vision analysis), video (with thumbnails)
- **Search everything** — by name, content, tags, detected faces, media segments
- **Auto-classify** — LLM-powered file classification (invoice, receipt, photo, contract, etc.)
- **Detect duplicates** — exact (SHA-256) and similar (name + size) matches
- **Smart rename** — LLM suggests better filenames based on content
- **Translate** — documents and video subtitles to 9 languages via LLM
- **Organize** — rules engine (match by extension/name/size → move/copy to target)
- **Watch folders** — background daemon auto-indexes and organizes watched directories
- **Face search** — find all photos containing a named person

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ARCHIVIST_TRANSLATION_LANGS` | `en,es,fr,de,zh,ja,ko,ru,ar` | Supported translation languages |
| `ARCHIVIST_AUTO_ORGANIZE` | `true` | Apply organization rules during auto-scan |
| `ARCHIVIST_AUTO_DEDUP` | `true` | Check for duplicates during indexing |
| `ARCHIVIST_AUTO_CLASSIFY` | `true` | Auto-classify files with LLM |
| `ARCHIVIST_MAX_PREVIEW_MB` | `50` | Max file size for text preview |
| `ARCHIVIST_SHOW_HIDDEN` | `0` | Show hidden dotfiles in browser |

## API Reference

```python
from archivist import (
    # File browser
    browse_directory, browse_indexed, get_file_detail,
    recent_files, file_statistics,

    # File viewer
    preview_file,

    # Smart actions
    auto_classify_file, detect_duplicates, suggest_rename,
    smart_summarize_directory,

    # Translation
    translate_document, translate_video_subtitles,
    translation_status, get_cached_translation,

    # Organizer
    add_rule, list_rules, delete_rule, toggle_rule,
    apply_rules_to_file, apply_rules_to_directory,
    suggest_organization,

    # Search
    search_everything, search_files, search_by_content,
    search_by_tag, search_faces, search_media,
    search_duplicates, list_all_tags,
)
```

### File Browsing

```python
from archivist.file_manager import browse_directory, browse_indexed, get_file_detail, file_statistics

# Browse a directory:
result = browse_directory("/home/user/Documents")
# → {"ok": True, "entries": [{name, path, is_dir, size, category, ...}, ...]}

# Browse indexed files with filters:
result = browse_indexed(query="report", category="document", tag="important")

# Get detailed file info:
detail = get_file_detail(file_id=42)
# → {"ok": True, "file": {path, tags, faces, media_segments, actions, ...}}

# Get overall statistics:
stats = file_statistics()
# → {"total_files": 1500, "total_bytes": ..., "by_category": {...}, "total_faces": 42, ...}
```

### File Preview

```python
from archivist.file_manager.viewer import preview_file

# Preview any file:
result = preview_file("/path/to/file.pdf")
# → {"ok": True, "preview": "Document content...", "preview_type": "text", "chars": 5000}

# Image gets dimensions + vision analysis:
result = preview_file("/path/to/photo.jpg")
# → {"ok": True, "preview_type": "image", "width": 1920, "height": 1080,
#    "vision": {"caption": "...", "objects": [...], "scene_tags": [...]}}

# Video gets duration + storyboard thumbnails:
result = preview_file("/path/to/video.mp4")
# → {"ok": True, "preview_type": "video", "duration": 142.5,
#    "thumbnails": ["/path/to/thumb1.jpg", ...]}
```

### Smart Actions

```python
from archivist.smart_actions import auto_classify_file, detect_duplicates, suggest_rename, smart_summarize_directory

# AI classification:
result = auto_classify_file("/path/to/file.pdf")
# → {"ok": True, "classification": {
#     "category": "invoice", "title": "AWS Invoice March 2024",
#     "tags": ["aws", "cloud", "billing"],
#     "confidentiality": "internal"
# }}

# Duplicate detection:
result = detect_duplicates("/path/to/file.pdf")
# → {"ok": True, "has_exact_dupes": True,
#    "exact_duplicates": [{"path": "/backup/file.pdf", ...}],
#    "similar": [{"name": "file_copy.pdf", ...}]}

# Smart rename:
result = suggest_rename("/path/to/IMG_20240301_142530.jpg")
# → {"ok": True, "suggested_name": "Sunset_over_Golden_Gate_Bridge.jpg",
#    "reason": "Descriptive name based on image content"}

# Summarize directory:
result = smart_summarize_directory("/path/to/project")
# → {"ok": True, "analysis": {
#     "summary": "Project source for a React web application",
#     "purpose": "project source",
#     "organization_hint": "Separate components, hooks, and utils into subdirectories"
# }}
```

### Translation

```python
from archivist.translation import translate_document, translate_video_subtitles

# Translate a document:
result = translate_document("/path/to/report_fr.pdf", target_lang="english")
# → {"ok": True, "source_chars": 4500, "translated_chars": 4200,
#    "translated_text": "The quarterly results show..."}

# Translate video subtitles:
result = translate_video_subtitles("/path/to/video.mp4", target_lang="spanish")
# → {"ok": True, "engine": "faster_whisper", "translated_text": "Hola..."}

# Check cached translation:
cached = get_cached_translation(file_id=42, target_lang="french")
```

### Organization Rules

```python
from archivist.organizer import add_rule, list_rules, apply_rules_to_file, suggest_organization

# Add a rule: move all PDF invoices to ~/Documents/Invoices
add_rule(
    name="PDF Invoices",
    conditions={"extensions": [".pdf"], "name_patterns": ["invoice", "receipt"]},
    target_path="/home/user/Documents/Invoices",
    action="move",
    priority=10,
)

# Apply rules to a file:
result = apply_rules_to_file("/path/to/invoice_2024.pdf")
# → {"ok": True, "dest": "/home/user/Documents/Invoices/invoice_2024.pdf", "rule": "PDF Invoices"}

# Apply rules to an entire directory:
result = apply_rules_to_directory("/home/user/Downloads")
# → {"ok": True, "moved": 15, "skipped": 200}

# Get organization suggestions:
suggestions = suggest_organization("/path/to/file.pdf")
# → [{"folder": "~/Documents", "reason": "Document files belong in Documents", "confidence": 0.85}]

# List all rules:
rules = list_rules()
```

### Unified Search

```python
from archivist.search import search_everything, search_duplicates, list_all_tags

# Search across all sources:
result = search_everything("alice birthday")
# → {"results": {
#     "files": [...],         # filename matches
#     "by_content": [...],    # content matches
#     "by_tag": [...],        # tag matches
#     "faces": [...],         # face name matches
#     "media": [...],         # media segment matches
# }, "total_hits": 23}

# Find duplicate files:
dupes = search_duplicates()
# → {"duplicate_groups": [{"hash": "abc...", "count": 3, "potential_waste": 2048}, ...]}

# List all tags:
tags = list_all_tags()
# → {"tags": [{"name": "image", "file_count": 500}, {"name": "invoice", "file_count": 42}, ...]}
```

### File Manager Daemon

```python
from archivist.file_manager.daemon import (
    add_watched_directory, remove_watched_directory,
    list_watched_directories, scan_now, ArchivistDaemon
)

# Add a directory to watch:
add_watched_directory("/home/user/Documents", label="My Documents")

# List watched directories:
watched = list_watched_directories()

# Manually trigger a scan:
result = scan_now()  # Scans all watched dirs
result = scan_now("/home/user/Downloads")  # Scan specific dir

# Start the background daemon:
daemon = ArchivistDaemon()
daemon.start()
# ... runs every 60 seconds ...
daemon.stop()
```

## GUI

### File Manager Window

The PyQt6 window provides:

- **Toolbar** — Home button, path input bar, Go button
- **Search bar** — searches indexed files (name, content, tags)
- **Split-pane layout**:
  - **Left**: File list with category colors, double-click to navigate/select
  - **Right**: Preview tab + Details tab
- **Menu bar**:
  - **File** — Add Watched Directory, Exit
  - **Tools** — Scan All, Find Duplicates, Statistics
  - **Organize** — Organize Current File, Suggest Organization, AI Classify, Detect Duplicates
  - **Translate** — 9 language options
- **Right-click context menu** on any file: Preview, Details, Organize, AI Classify, Detect Duplicates, Suggest Rename, Translate
- **Status bar** — shows current operation feedback

### Headless Mode

Without PyQt6, Archivist runs as a background daemon that watches directories and applies rules:

```bash
ARCHIVIST_AUTO_ORGANIZE=1 python -m archivist
```

## Data Layout

```
~/.local/share/fauxnix/data/archivist/
└── archivist.db    # watched_dirs, rules, translations, relationships
```

Archivist shares all file data, tags, faces, and media with Membrie via the shared `fauxnix.db`.

## Dependencies

Archivist depends on `fauxnix-tools` (which provides all file/vision/media/LLM operations) and optionally `PyQt6` for the GUI.
