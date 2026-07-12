from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".raw", ".cr2", ".cr3", ".nef", ".arw",
    ".dng", ".orf", ".rw2", ".tga", ".psd", ".xcf", ".kra",
}
VIDEO_EXTS: set[str] = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".mpg",
    ".mpeg", ".3gp", ".3g2", ".mts", ".m2ts", ".ts", ".vob", ".ogv",
    ".flv", ".f4v", ".divx",
}
AUDIO_EXTS: set[str] = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wma", ".aif", ".aiff",
}


def file_extension(path: Path) -> str:
    ext = path.suffix.lower()
    if ext:
        return ext
    name = path.name.lower()
    if name.startswith(".") and name.count(".") == 1 and len(name) > 1:
        return name
    return ""


def file_category(path: Path, mime: str = "") -> str:
    ext = file_extension(path)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}

    document_exts = {
        ".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".markdown", ".rtf",
        ".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".ods", ".ppt", ".pptx",
        ".odp", ".json", ".xml", ".log", ".yaml", ".yml", ".toml", ".ini",
        ".cfg", ".conf", ".rst", ".tex", ".pages", ".numbers", ".key",
    }
    code_exts = {
        ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html",
        ".htm", ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".go", ".rs", ".rb",
        ".php", ".swift", ".kt", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".sql",
        ".ipynb", ".vue", ".svelte",
    }
    archive_exts = {
        ".zip", ".7z", ".rar", ".iso", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".cab",
    }

    if name in {"license", "readme", "changelog", "makefile", "dockerfile"}:
        return "document"
    if name in {".ds_store", "thumbs.db", "desktop.ini"}:
        return "system"
    if name in {".gitignore", ".gitattributes", ".editorconfig"}:
        return "code"
    if ".git" in parts:
        return "code"

    mime_lower = mime.lower()
    if mime_lower.startswith("image/") or ext in IMAGE_EXTS:
        return "image"
    if mime_lower.startswith("video/") or ext in VIDEO_EXTS:
        return "video"
    if mime_lower.startswith("audio/") or ext in AUDIO_EXTS:
        return "audio"
    if ext in document_exts:
        return "document"
    if ext in code_exts:
        return "code"
    if ext in archive_exts:
        return "archive"
    return "other"
