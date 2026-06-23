"""File list — Gtk.ColumnView with sortable columns and search display."""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gio, GLib, GdkPixbuf, GObject


class FileListWidget(Gtk.Box):
    __gsignals__ = {
        "file_selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    COLUMNS = ["name", "ext", "category", "size_bytes", "modified_ts"]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._search_label = Gtk.Label(label="")
        self._search_label.add_css_class("heading")
        self._search_label.set_halign(Gtk.Align.START)
        self._search_label.set_visible(False)
        self.append(self._search_label)

        self._store = Gio.ListStore.new(FileItem)
        self._selection = Gtk.SingleSelection.new(self._store)
        self._selection.connect("selection_changed", self._on_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_item)
        factory.connect("bind", self._bind_item)

        col_view = Gtk.ColumnView(model=self._selection)
        col_view.set_show_column_separators(True)
        col_view.set_show_row_separators(True)

        cols = [
            ("Name", "name", True),
            ("Type", "category", True),
            ("Size", "size_str", False),
            ("Modified", "modified_str", True),
        ]
        for title, attr, sortable in cols:
            col = Gtk.ColumnViewColumn(
                title=title,
                factory=factory,
            )
            col.set_resizable(True)
            col_view.append_column(col)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(col_view)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._empty_label = Gtk.Label(label="Select a directory to browse")
        self._empty_label.add_css_class("large-title")
        self._empty_label.set_opacity(0.4)
        self._empty_label.set_valign(Gtk.Align.CENTER)
        self._empty_label.set_halign(Gtk.Align.CENTER)
        self._overlay = Gtk.Overlay()
        self._overlay.set_child(scrolled)
        self._overlay.add_overlay(self._empty_label)
        self.append(self._overlay)

    def _setup_item(self, factory, item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(8)
        box.set_margin_end(8)

        icon = Gtk.Image()
        icon.set_pixel_size(20)
        box.append(icon)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(True)
        box.append(label)

        item.set_child(box)

    def _bind_item(self, factory, item):
        box = item.get_child()
        file_item = item.get_item()
        icon = box.get_first_child()
        label = icon.get_next_sibling()
        label.set_text(file_item.name)
        icon.set_from_icon_name(file_item.icon_name())

    def _on_selection_changed(self, selection, position, n_items):
        selected = selection.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        item = self._store.get_item(selected)
        if item:
            self.emit("file_selected", item.to_dict())

    def load_directory(self, path: Path, bridge=None):
        self._search_label.set_visible(False)
        self._store.remove_all()
        self._empty_label.set_visible(False)

        try:
            entries = sorted(
                path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except (PermissionError, OSError):
            self._empty_label.set_text("Permission denied")
            self._empty_label.set_visible(True)
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            self._store.append(FileItem.from_path(entry))

        if len(self._store) == 0:
            self._empty_label.set_text("Empty directory")
            self._empty_label.set_visible(True)

    def show_rows(self, results: list[dict], title: str):
        self._store.remove_all()
        self._empty_label.set_visible(False)
        self._search_label.set_text(title)
        self._search_label.set_visible(True)

        for r in results:
            path = r.get("path", "")
            name = r.get("name", Path(path).name)
            ext = r.get("ext", "")
            category = r.get("category", "other")
            size = r.get("size_bytes", 0)
            modified = r.get("modified_ts", 0)
            summary = r.get("summary", "")
            preview = r.get("preview_path", "")
            thumb = r.get("thumb_path", "")

            self._store.append(FileItem(
                name=name, path=path, ext=ext, category=category,
                size_bytes=size, modified_ts=modified,
                is_dir=False, summary=summary,
                preview_path=preview, thumb_path=thumb,
                file_id=r.get("id"),
            ))

        if len(self._store) == 0:
            self._empty_label.set_text("No files found")
            self._empty_label.set_visible(True)

    def show_search_results(self, results: list[dict], query: str):
        self.show_rows(results, f'Results for "{query}"')


class FileItem(GObject.Object):
    __gtype_name__ = "FileItem"

    def __init__(self, name="", path="", ext="", category="other",
                 size_bytes=0, modified_ts=0, is_dir=False,
                 summary="", preview_path="", thumb_path="", file_id=None):
        super().__init__()
        self.name = name
        self.path = path
        self.ext = ext
        self.category = category
        self.size_bytes = size_bytes
        self.modified_ts = modified_ts
        self.is_dir = is_dir
        self.summary = summary
        self.preview_path = preview_path
        self.thumb_path = thumb_path
        self.file_id = file_id

    @property
    def size_str(self):
        if self.is_dir:
            return ""
        b = self.size_bytes
        for unit in ["B", "KB", "MB", "GB"]:
            if b < 1024:
                return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    @property
    def modified_str(self):
        if not self.modified_ts:
            return ""
        try:
            dt = datetime.fromtimestamp(self.modified_ts)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return ""

    def icon_name(self):
        icons = {
            "folder": "folder-symbolic",
            "image": "image-x-generic-symbolic",
            "video": "video-x-generic-symbolic",
            "audio": "audio-x-generic-symbolic",
            "document": "x-office-document-symbolic",
            "code": "text-x-preview-symbolic",
            "archive": "package-x-generic-symbolic",
        }
        if self.is_dir:
            return "folder-symbolic"
        return icons.get(self.category, "text-x-generic-symbolic")

    @classmethod
    def from_path(cls, path: Path) -> "FileItem":
        stat = path.stat()
        is_dir = path.is_dir()
        ext = path.suffix.lower() if not is_dir else ""
        from ..services.archivist_bridge import file_category
        cat = "folder" if is_dir else file_category(path)
        return cls(
            name=path.name, path=str(path), ext=ext, category=cat,
            size_bytes=0 if is_dir else stat.st_size,
            modified_ts=stat.st_mtime, is_dir=is_dir,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.file_id,
            "name": self.name,
            "path": self.path,
            "ext": self.ext,
            "category": self.category,
            "size_bytes": self.size_bytes,
            "modified_ts": self.modified_ts,
            "is_dir": self.is_dir,
            "summary": self.summary,
            "preview_path": self.preview_path,
            "thumb_path": self.thumb_path,
        }


def file_category(path: Path) -> str:
    from ..services.archivist_bridge import ARCHIVIST_SRC
    try:
        from archivist_app.app.utils import file_category as cat_fn
        return cat_fn(path, f"application/{path.suffix}")
    except Exception:
        ext = path.suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            return "image"
        if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return "video"
        if ext in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            return "audio"
        if ext in {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"}:
            return "document"
        if ext in {".py", ".js", ".ts", ".rs", ".go", ".c", ".cpp", ".h"}:
            return "code"
        if ext in {".zip", ".tar", ".gz", ".7z", ".rar"}:
            return "archive"
        return "other"
