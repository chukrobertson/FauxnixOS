import hashlib
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Iterable


def now_ts() -> float:
    return time.time()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def resolve_allowed_path(raw_path: str, allowed_roots: Iterable[Path]) -> Path:
    path = Path(raw_path).expanduser().resolve(strict=False)
    for root in allowed_roots:
        resolved_root = root.resolve(strict=False)
        if path == resolved_root or path_is_inside(path, resolved_root):
            return path
    raise ValueError("Path is outside allowed archive roots")


def clean_filename(filename: str) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    invalid_chars = '<>:"/\\|?*'
    cleaned = "".join("_" if c in invalid_chars or ord(c) < 32 else c for c in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "upload"


def safe_relative_folder(raw_folder: str) -> Path:
    normalized = (raw_folder or "").strip().replace("\\", "/").strip("/")
    normalized = normalized.strip("`").strip()
    if "\n" in normalized:
        normalized = normalized.splitlines()[0].strip().strip("/")
    folder = Path(normalized)
    if folder.is_absolute() or folder.drive or any(part in {"..", ""} for part in folder.parts):
        raise ValueError("Folder must be a relative path inside the archive")
    invalid_chars = '<>:"\\|?*'
    if any(any(c in invalid_chars or ord(c) < 32 for c in part) for part in folder.parts):
        raise ValueError("Folder contains invalid characters")
    return folder


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find available filename for {path.name}")


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def file_extension(path: Path) -> str:
    ext = path.suffix.lower()
    if ext:
        return ext
    name = path.name.lower()
    if name.startswith(".") and name.count(".") == 1 and len(name) > 1:
        return name
    return ""


def file_category(path: Path, mime: str) -> str:
    ext = file_extension(path)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    image_exts = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
        ".heic", ".heif", ".avif", ".raw", ".cr2", ".cr3", ".nef", ".arw",
        ".dng", ".orf", ".rw2", ".tga", ".psd", ".xcf", ".kra", ".thm",
    }
    video_exts = {
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".mpg",
        ".mpeg", ".3gp", ".3g2", ".mts", ".m2ts", ".ts", ".vob", ".ogv",
        ".flv", ".f4v", ".divx", ".mod", ".lrv", ".insv",
    }
    audio_exts = {
        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
        ".wma", ".aif", ".aiff", ".alac", ".amr", ".mid", ".midi",
    }
    document_exts = {
        ".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".markdown", ".rtf",
        ".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".ods", ".ppt", ".pptx",
        ".odp", ".json", ".xml", ".log", ".yaml", ".yml", ".toml", ".ini",
        ".cfg", ".conf", ".rst", ".tex", ".pages", ".numbers", ".key",
    }
    archive_exts = {
        ".zip", ".7z", ".rar", ".iso", ".tar", ".gz", ".bz2", ".xz", ".tgz",
        ".tbz", ".tbz2", ".cab", ".jar", ".war", ".whl", ".dungeondraft_pack",
        ".pack",
    }
    software_exts = {
        ".exe", ".msi", ".apk", ".dmg", ".app", ".pkg", ".deb", ".rpm",
        ".dll", ".so", ".dylib", ".lib", ".pyd", ".a",
    }
    rom_exts = {
        ".nes", ".sfc", ".smc", ".gba", ".gb", ".gbc", ".n64", ".z64", ".cue",
        ".bin", ".chd", ".wbfs", ".gdi", ".cdi",
    }
    code_exts = {
        ".py", ".pyw", ".pyi", ".pyc", ".js", ".jsx", ".ts", ".tsx", ".css",
        ".scss", ".sass", ".html", ".htm", ".c", ".h", ".cpp", ".hpp", ".cc",
        ".cs", ".java", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts",
        ".m", ".mm", ".r", ".lua", ".sh", ".bash", ".zsh", ".fish", ".ps1",
        ".bat", ".cmd", ".vbs", ".sql", ".ipynb", ".proto", ".f", ".f90",
        ".pyx", ".pxd", ".pyf", ".tmpl", ".tpl", ".vue", ".svelte",
    }
    data_exts = {
        ".db", ".sqlite", ".sqlite3", ".dat", ".npy", ".npz", ".mat", ".sav",
        ".pkl", ".pickle", ".arff", ".fits", ".fit", ".nc", ".idx", ".parquet",
        ".feather", ".orc", ".h5", ".hdf5", ".sample", ".tab",
    }
    font_exts = {".ttf", ".otf", ".woff", ".woff2", ".afm", ".pfb"}
    shortcut_exts = {".url", ".lnk", ".webloc"}

    if ".git" in parts:
        return "code"
    if name in {"license", "readme", "changelog", "notice", "authors", "contributors", "copying"}:
        return "document"
    if name in {".ds_store", "thumbs.db", "desktop.ini"}:
        return "system"
    if name in {".gitignore", ".gitattributes", ".editorconfig", "makefile", "dockerfile", "gemfile", "rakefile"}:
        return "code"

    if mime.startswith("image/") or ext in image_exts:
        return "image"
    if mime.startswith("video/") or ext in video_exts:
        return "video"
    if mime.startswith("audio/") or ext in audio_exts:
        return "audio"
    if ext in document_exts:
        return "document"
    if ext in archive_exts:
        return "archive"
    if ext in software_exts:
        return "software"
    if ext in rom_exts:
        return "rom"
    if ext in code_exts:
        return "code"
    if ext in data_exts:
        return "data"
    if ext in font_exts:
        return "font"
    if ext in shortcut_exts:
        return "shortcut"
    return "other"


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def move_to(path_src: Path, path_dst: Path):
    ensure_parent(path_dst)
    shutil.move(str(path_src), str(path_dst))
