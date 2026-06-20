from pathlib import Path
import json
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CLIPBOARD_DIR = DATA_DIR / "clipboard"
NOTES_DIR = DATA_DIR / "notes"
PREVIEW_DIR = DATA_DIR / "previews"
THUMBS_DIR = DATA_DIR / "thumbs"
REVIEW_DIR = DATA_DIR / "review"
REVIEW_DUP_DIR = REVIEW_DIR / "duplicates"
REVIEW_DEL_DIR = REVIEW_DIR / "deletions"
REVIEW_UNCERTAIN_DIR = REVIEW_DIR / "uncertain"
CHROMA_DIR = DATA_DIR / "chroma"
ARCHIVE_SOURCES_FILE = DATA_DIR / "archive_sources.json"

for p in [
    DATA_DIR, UPLOAD_DIR, CLIPBOARD_DIR, NOTES_DIR, PREVIEW_DIR, THUMBS_DIR,
    REVIEW_DIR, REVIEW_DUP_DIR, REVIEW_DEL_DIR, REVIEW_UNCERTAIN_DIR, CHROMA_DIR
]:
    p.mkdir(parents=True, exist_ok=True)

LOCAL_DEFAULT_ARCHIVE_ROOT = BASE_DIR.parent / "SharedBackup"
DEFAULT_ARCHIVE_ROOT = LOCAL_DEFAULT_ARCHIVE_ROOT if LOCAL_DEFAULT_ARCHIVE_ROOT.exists() else Path(r"Z:\Archive")


def configured_archive_root() -> str:
    try:
        data = json.loads(ARCHIVE_SOURCES_FILE.read_text(encoding="utf-8"))
        root = data.get("archive_root")
        if root:
            return str(root)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return str(DEFAULT_ARCHIVE_ROOT)


def configured_knowledgebase_root(archive_root: Path | str | None = None) -> str:
    fallback_root = Path(archive_root or configured_archive_root()) / "_KNOWLEDGEBASE"
    try:
        data = json.loads(ARCHIVE_SOURCES_FILE.read_text(encoding="utf-8"))
        root = data.get("knowledgebase_root")
        if root:
            return str(root)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return str(fallback_root)


ARCHIVE_ROOT = Path(os.getenv("ARCHIVE_ROOT", configured_archive_root()))
ARCHIVE_INBOX = ARCHIVE_ROOT / "_INBOX"
ARCHIVE_REVIEW_DIR = ARCHIVE_ROOT / "_ARCHIVE_REVIEW"
ARCHIVE_DUP_REVIEW_DIR = ARCHIVE_REVIEW_DIR / "Duplicates"
KNOWLEDGEBASE_DIR = Path(os.getenv("KNOWLEDGEBASE_ROOT", configured_knowledgebase_root(ARCHIVE_ROOT)))

if ARCHIVE_ROOT.exists():
    for p in [ARCHIVE_INBOX, ARCHIVE_REVIEW_DIR, ARCHIVE_DUP_REVIEW_DIR, KNOWLEDGEBASE_DIR]:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            pass

    OLLAMA_ARCHIVIST_MODEL = os.getenv("OLLAMA_ARCHIVIST_MODEL", "RageBait/LadySophiaNoctua:latest")
    OLLAMA_COWRITER_MODEL = os.getenv("OLLAMA_COWRITER_MODEL", "gemma4:12b")
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", "lfm2.5:8b")
OLLAMA_CODER_MODEL = os.getenv("OLLAMA_CODER_MODEL", "gemma4:12b")
OLLAMA_FAST_CODER_MODEL = os.getenv("OLLAMA_FAST_CODER_MODEL", "minicpm-v4.6:latest")
OLLAMA_REASON_MODEL = os.getenv("OLLAMA_REASON_MODEL", "huihui_ai/huihui-moe-abliterated:1.5b")
OLLAMA_SUMMARY_MODEL = os.getenv("OLLAMA_SUMMARY_MODEL", "qwen3.5:0.8b")
OLLAMA_ORGANIZER_MODEL = os.getenv("OLLAMA_ORGANIZER_MODEL", "qwen3.5:0.8b")
OLLAMA_MAINTENANCE_MODEL = os.getenv("OLLAMA_MAINTENANCE_MODEL", "gemma4:12b")
OLLAMA_TAGGER_MODEL = os.getenv("OLLAMA_TAGGER_MODEL", "gemma4:12b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:8b")
OLLAMA_VISION_FALLBACK_MODEL = os.getenv("OLLAMA_VISION_FALLBACK_MODEL", "minicpm-v4.6:latest")
OLLAMA_FACE_MODEL = os.getenv("OLLAMA_FACE_MODEL", "qwen3-vl:8b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
OLLAMA_EXPERIMENTAL_EMBED_MODEL = os.getenv("OLLAMA_EXPERIMENTAL_EMBED_MODEL", "embeddinggemma:latest")
OLLAMA_ADMIN_PATCH_PROPOSAL_MODEL = os.getenv("OLLAMA_ADMIN_PATCH_PROPOSAL_MODEL", "gemma4:12b")
OLLAMA_ADMIN_DIFF_VALIDATION_MODEL = os.getenv("OLLAMA_ADMIN_DIFF_VALIDATION_MODEL", "minicpm-v4.6:latest")
OLLAMA_ADMIN_PATCH_SNAPSHOT_MODEL = os.getenv("OLLAMA_ADMIN_PATCH_SNAPSHOT_MODEL", "granite4:350m")
OLLAMA_ADMIN_APPLY_READINESS_MODEL = os.getenv("OLLAMA_ADMIN_APPLY_READINESS_MODEL", "gemma4:12b")
OLLAMA_ADMIN_PATCH_APPLY_MODEL = os.getenv("OLLAMA_ADMIN_PATCH_APPLY_MODEL", "gemma4:12b")
OLLAMA_ADMIN_VERIFICATION_CHECKS_MODEL = os.getenv("OLLAMA_ADMIN_VERIFICATION_CHECKS_MODEL", "minicpm-v4.6:latest")

TESSERACT_CMD = os.getenv(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
