# fauxnix-tools

**Shared Python library for FauxnixOS.** Provides all file operations, vision processing, media handling, and LLM integration used by both Membrie and Archivist.

## Installation

```bash
pip install -e .
# or, with optional extras:
pip install -e ".[vision,media,llm]"
```

## Configuration

All paths are XDG-compliant. Override with environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `FAUXNIX_DATA_DIR` | `~/.local/share/fauxnix` | All data, DB, vectors, thumbnails |
| `FAUXNIX_CHAT_MODEL` | `qwen2.5:7b` | Main chat/instruction model |
| `FAUXNIX_EMBED_MODEL` | `nomic-embed-text` | Text embedding model |
| `FAUXNIX_VISION_MODEL` | `qwen3-vl:8b` | Image vision model |
| `FAUXNIX_VISION_FALLBACK` | `minicpm-v4.6:latest` | Fallback vision model |
| `FAUXNIX_REASON_MODEL` | `qwen2.5:7b` | Reasoning model |
| `FAUXNIX_SUMMARY_MODEL` | `qwen2.5:1.5b` | Lightweight summary model |
| `FAUXNIX_TESSERACT_CMD` | `tesseract` | Tesseract OCR binary |
| `FAUXNIX_FFMPEG_BIN` | `ffmpeg` | FFmpeg binary path |
| `FAUXNIX_WHISPER_MODEL` | `base` | Whisper model size |
| `FAUXNIX_FACE_SCAN_IMAGES` | `true` | Auto-detect faces in indexed images |
| `FAUXNIX_FACE_SCAN_VIDEOS` | `true` | Auto-detect faces in indexed videos |

## API Reference

### File Extraction

```python
from fauxnix_tools.files import extract_any, extract_text

# Extract text from any supported file type:
text = extract_any(Path("document.pdf"))     # → str
text = extract_any(Path("spreadsheet.xlsx")) # → str
text = extract_any(Path("photo.jpg"))        # → OCR text

# Extract with format hint:
text = extract_text(Path("document.pdf"), format="pdf")
text = extract_text(Path("photo.jpg"), format="ocr")
```

Supported formats: PDF, DOCX, XLSX, CSV, TXT, MD, JSON, XML, YAML, TOML, INI, LOG. Images get OCR via Tesseract.

### File Indexing

```python
from fauxnix_tools.files import index_file, index_directory, search_indexed_files

# Index a single file:
result = index_file("/path/to/file.pdf")
# → {"indexed": True, "file_id": 1, "category": "document", "face_count": 0}

# Index a whole directory (recursive):
result = index_directory("/path/to/directory", label="My Photos")
# → {"indexed": 42, "skipped": 3, "source_dir": "..."}

# Search indexed files:
results = search_indexed_files("invoice")
# → [{"id": 1, "path": "...", "name": "invoice_2024.pdf", ...}, ...]
```

Indexing automatically:
- Hashes the file (SHA-256) for deduplication
- Extracts text content
- Generates thumbnails for images
- Detects faces (if enabled)
- Applies auto-tags based on content and metadata

### File Tagging

```python
from fauxnix_tools.files import apply_auto_tags, suggested_auto_tags, file_tag_names, clean_tag_name

# Suggest tags for a file record:
tags = suggested_auto_tags(record, face_count=3)
# → ["image", "has faces", "has text", "screenshot"]

# Apply tags to the database:
apply_auto_tags(record, face_count=3, extra_tags=["important"])

# Get tags for a file:
tags = file_tag_names(file_id=42)
# → ["image", "has faces", "screenshot", "important"]

# Clean a tag name:
clean_tag_name("  My Tag!  ") → "My Tag!"
```

### Directory Snapshots

```python
from fauxnix_tools.files import snapshot_directory, list_snapshots, restore_snapshot

# Create a point-in-time backup:
snap = snapshot_directory("/path/to/project", reason="Pre-upgrade backup")
# → {"ok": True, "snapshot_id": "snapshot_20250101_120000", "file_count": 150}

# List recent snapshots:
snapshots = list_snapshots(limit=10)

# Restore a snapshot:
restore_snapshot("snapshot_20250101_120000", target_dir="/path/to/restore")
```

### Face Detection

```python
from fauxnix_tools.vision import (
    detect_faces_in_image, detect_faces_in_video,
    recognize_faces_in_image, match_face, name_face, get_known_faces
)

# Quick detection (OpenCV Haar cascades):
result = detect_faces_in_image("/path/to/photo.jpg")
# → {"ok": True, "face_count": 3, "observations": [...]}

# Deep recognition (InsightFace):
result = recognize_faces_in_image("/path/to/photo.jpg")
# → {"ok": True, "face_count": 3, "faces": [{"gender": "female", "age": 28, "match": {...}}, ...]}

# Match a face embedding against known faces:
match = match_face(embedding)
# → {"name": "Alice", "cluster_id": "face:abc123", "similarity": 0.85} or None

# Name a face cluster:
name_face("face:abc123", "Alice", embedding=embedding)

# List known faces:
faces = get_known_faces()
# → [{"cluster_id": "face:abc123", "name": "Alice", "observation_count": 42}, ...]
```

### Vision Analysis

```python
from fauxnix_tools.vision import analyze_image_path, analyze_image_file, vision_status

# Check if a vision model is available:
status = vision_status()
# → {"ready": True, "model": "qwen3-vl:8b", "installed": [...]}

# Analyze an image (uses Ollama vision model):
result = analyze_image_path("/path/to/photo.jpg")
analysis = result["analysis"]
# → {
#     "caption": "A person sitting at a desk with a laptop",
#     "objects": ["laptop", "desk", "keyboard", "monitor", "coffee mug"],
#     "scene_tags": ["office", "indoor", "workspace"],
#     "text": "Meeting notes on screen",
#     "people_count": 1,
#     "warnings": []
# }

# Analyze and save tags to DB:
analyze_image_file("/path/to/photo.jpg", file_id=42)
```

### Object Detection

```python
from fauxnix_tools.vision import detect_objects_in_image, detect_objects_in_video

# Detect objects using vision model:
result = detect_objects_in_image("/path/to/photo.jpg")
# → {"ok": True, "objects": ["chair", "table", "lamp"], "scene_tags": [...], "model": "qwen3-vl:8b"}

# Video object detection (stub — full YOLO/OWL-ViT planned):
result = detect_objects_in_video("/path/to/video.mp4")
```

### Media Processing

```python
from fauxnix_tools.media import probe_video, extract_storyboard_frames, extract_subtitle_text, transcribe_video, analyze_video

# Probe video metadata:
probe = probe_video(Path("/path/to/video.mp4"))
# → {"duration_seconds": 142.5, "streams": [...], "summary": "Video: my_video. Duration: 2:22."}

# Extract storyboard frames:
frames = extract_storyboard_frames(Path("/path/to/video.mp4"), probe, interval_seconds=30)

# Extract embedded subtitles:
subs = extract_subtitle_text(Path("/path/to/video.mp4"), probe)
# → {"available": True, "streams": 1, "text": "Hello world\n..."}

# Transcribe speech to text:
result = transcribe_video("/path/to/video.mp4")
# → {"engine": "faster_whisper", "transcript_chars": 2500}

# Full video analysis (storyboard + subtitles + faces + objects):
result = analyze_video("/path/to/video.mp4", file_id=42, detect_faces=True, detect_objects=True)
# → {"segment_count": 12, "face_scan": {...}, "object_scan": {...}}
```

### LLM Integration

```python
from fauxnix_tools.llm import model_for_task, embed_text, chat_messages, route_for_task

# Get the best available model for a task:
model = model_for_task("chat")        # → "qwen2.5:7b"
model = model_for_task("summary")     # → "qwen2.5:1.5b"
model = model_for_task("vision")      # → "qwen3-vl:8b"
model = model_for_task("reasoning")   # → "qwen2.5:7b"
model = model_for_task("embedding")   # → "nomic-embed-text"

# Get full routing info:
route = route_for_task("vision")
# → {"task": "vision", "model": "qwen3-vl:8b", "fallback_chain": ["qwen3-vl:8b", "minicpm-v4.6:latest"]}

# Generate embeddings:
vector = embed_text("Hello world")

# Send a chat message:
response = chat_messages([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"}
], task="chat")
# → {"message": {"role": "assistant", "content": "Paris."}, ...}
```

### Utilities

```python
from fauxnix_tools.utils import sha256_file, guess_mime, clean_filename, unique_path, now_ts

hash = sha256_file(Path("/path/to/file"))
mime = guess_mime(Path("photo.jpg"))   # → "image/jpeg"
name = clean_filename("my file!.txt")  # → "my file_.txt"
path = unique_path(Path("/tmp/file.txt"))  # → /tmp/file_1.txt if exists
ts = now_ts()  # → 1735689600.123
```

### File Categories

```python
from fauxnix_tools.utils.categories import file_category, IMAGE_EXTS, VIDEO_EXTS

cat = file_category(Path("photo.jpg"))     # → "image"
cat = file_category(Path("video.mp4"))     # → "video"
cat = file_category(Path("doc.pdf"))       # → "document"
cat = file_category(Path("main.py"))       # → "code"
cat = file_category(Path("archive.zip"))    # → "archive"
cat = file_category(Path("song.mp3"))      # → "audio"

".jpg" in IMAGE_EXTS   # → True
".mp4" in VIDEO_EXTS   # → True
```

### Database

```python
from fauxnix_tools.db import get_conn, init_base_tables, ensure_column

# Get a database connection:
conn = get_conn()  # Uses default path: ~/.local/share/fauxnix/data/fauxnix.db
conn = get_conn(Path("/custom/path.db"))  # Custom path

# Initialize tables:
init_base_tables()  # Creates: files, tags, file_tags, media_segments, etc.

# Add a column to an existing table:
cur = conn.cursor()
ensure_column(cur, "files", "my_new_column", "TEXT DEFAULT ''")
```

### Context Discovery

```python
from fauxnix_tools.context import (
    discover_archive_sources, get_active_archive_state,
    list_available_context_sources, get_context_constellation
)

sources = discover_archive_sources()
state = get_active_archive_state(include_workspace=True)
available = list_available_context_sources()
graph = get_context_constellation()
```

## Data Layout

```
~/.local/share/fauxnix/
├── data/
│   ├── fauxnix.db              # SQLite database
│   ├── chroma/                 # ChromaDB vector store
│   ├── thumbs/                 # Generated thumbnails
│   ├── previews/               # File previews
│   ├── media/
│   │   ├── video_context/      # Storyboard frames, audio extracts
│   │   ├── faces/              # Face crop images
│   │   └── insight_faces/      # InsightFace recognition crops
│   ├── snapshots/              # Directory backup snapshots
│   └── archive/                # Archive root
└── knowledgebase/              # Knowledge base root
```

## Dependencies

- **Required**: ollama, chromadb, Pillow, numpy, requests
- **Files**: PyMuPDF (PDF), python-docx (DOCX), openpyxl (XLSX), pytesseract (OCR)
- **Vision**: opencv-python-headless (faces), insightface (recognition)
- **Media**: faster-whisper (transcription), ffmpeg/ffprobe (system)
- **System**: tesseract (system), ffmpeg (system)
