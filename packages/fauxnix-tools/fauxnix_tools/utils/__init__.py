from __future__ import annotations

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
    raise ValueError("Path is outside allowed directories")


def clean_filename(filename: str) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    invalid_chars = '<>:"/\\|?*'
    cleaned = "".join("_" if c in invalid_chars or ord(c) < 32 else c for c in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "upload"


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


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def move_to(path_src: Path, path_dst: Path):
    ensure_parent(path_dst)
    shutil.move(str(path_src), str(path_dst))
