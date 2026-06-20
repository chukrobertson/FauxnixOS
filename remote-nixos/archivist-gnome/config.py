from pathlib import Path
import os

ARCHIVIST_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("FAUXNIX_ARCHIVIST_DATA", Path.home() / ".local" / "share" / "fauxnix-archivist"))
DB_PATH = DATA_DIR / "archive.db"
CHROMA_DIR = DATA_DIR / "chroma"
PREVIEW_DIR = DATA_DIR / "previews"
THUMBS_DIR = DATA_DIR / "thumbs"
CACHE_DIR = DATA_DIR / "cache"

for p in [DATA_DIR, PREVIEW_DIR, THUMBS_DIR, CACHE_DIR, CHROMA_DIR]:
    p.mkdir(parents=True, exist_ok=True)

WATCHED_ROOTS = [
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Documents",
    Path.home() / "Fauxnix",
]

APP_ID = "org.fauxnix.Archivist"
APP_NAME = "Fauxnix Archivist"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:0.6b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:8b")

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")
