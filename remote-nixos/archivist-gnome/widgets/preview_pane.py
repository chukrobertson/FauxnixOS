"""Preview pane — file details, text/image preview, tags, summary."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, GObject

from .tag_editor import TagEditor


class PreviewPane(Gtk.Box):
    __gsignals__ = {
        "apply_tag": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
        "remove_tag": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)

        self._file_id: int | None = None
        self._current_path: str = ""

        self._title = Gtk.Label()
        self._title.add_css_class("title")
        self._title.set_wrap(True)
        self._title.set_halign(Gtk.Align.START)
        self.append(self._title)

        self._meta_grid = Gtk.Grid()
        self._meta_grid.set_column_spacing(12)
        self._meta_grid.set_row_spacing(4)
        self._meta_grid.set_margin_top(4)
        self._meta_grid.set_margin_bottom(8)
        self._populate_meta()
        self.append(self._meta_grid)

        self._image_preview = Gtk.Picture()
        self._image_preview.set_size_request(280, 200)
        self._image_preview.set_halign(Gtk.Align.CENTER)
        self._image_preview.set_visible(False)
        self._image_preview.add_css_class("preview-image")
        self.append(self._image_preview)

        self._text_preview = Gtk.TextView()
        self._text_preview.set_wrap_mode(Gtk.WrapMode.WORD)
        self._text_preview.set_editable(False)
        self._text_preview.set_cursor_visible(False)
        self._text_preview.set_visible(False)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_child(self._text_preview)
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_max_content_height(300)
        self.append(text_scroll)

        self._summary_label = Gtk.Label()
        self._summary_label.set_wrap(True)
        self._summary_label.set_halign(Gtk.Align.START)
        self._summary_label.set_visible(False)
        self._summary_label.add_css_class("caption")
        self.append(self._summary_label)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)

        self._tag_editor = TagEditor()
        self._tag_editor.connect("tag_added", self._on_tag_added)
        self._tag_editor.connect("tag_removed", self._on_tag_removed)
        self.append(self._tag_editor)

        self._empty = Gtk.Label(label="Select a file to view details")
        self._empty.add_css_class("large-title")
        self._empty.set_opacity(0.3)
        self._empty.set_valign(Gtk.Align.CENTER)
        self._empty.set_halign(Gtk.Align.CENTER)
        self.append(self._empty)

    def _populate_meta(self):
        self._path_label = Gtk.Label()
        self._type_label = Gtk.Label()
        self._size_label = Gtk.Label()
        self._modified_label = Gtk.Label()
        self._sha_label = Gtk.Label()
        labels = [
            ("Path:", self._path_label),
            ("Type:", self._type_label),
            ("Size:", self._size_label),
            ("Modified:", self._modified_label),
            ("SHA-256:", self._sha_label),
        ]
        for i, (title, widget) in enumerate(labels):
            title_lbl = Gtk.Label(label=title)
            title_lbl.set_halign(Gtk.Align.END)
            title_lbl.add_css_class("caption")
            widget.set_halign(Gtk.Align.START)
            widget.set_ellipsize(True)
            widget.add_css_class("caption")
            self._meta_grid.attach(title_lbl, 0, i, 1, 1)
            self._meta_grid.attach(widget, 1, i, 1, 1)

    def show_file(self, info: dict, bridge=None):
        self._empty.set_visible(False)
        self._file_id = info.get("id")
        self._current_path = info.get("path", "")

        self._title.set_text(info.get("name", ""))
        self._path_label.set_text(self._current_path)
        self._type_label.set_text(info.get("category", info.get("ext", "")))
        size = info.get("size_bytes", 0)
        self._size_label.set_text(self._format_size(size))

        modified = info.get("modified_ts", 0)
        if modified:
            try:
                self._modified_label.set_text(
                    datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S")
                )
            except (OSError, ValueError):
                self._modified_label.set_text("")
        else:
            self._modified_label.set_text("")

        sha = info.get("sha256", "")
        self._sha_label.set_text(sha[:16] + "..." if sha else "")

        self._show_content_preview(info, bridge)
        summary = info.get("summary", "")
        if summary:
            self._summary_label.set_text(summary)
            self._summary_label.set_visible(True)

        self._tag_editor.load_file_tags(self._file_id, bridge)

    def _show_content_preview(self, info: dict, bridge):
        self._image_preview.set_visible(False)
        self._text_preview.set_visible(False)
        buffer = self._text_preview.get_buffer()

        path_str = info.get("path", "")
        if not path_str or not bridge:
            return

        path = Path(path_str)
        category = info.get("category", "")

        if category == "image" or path.suffix.lower() in {
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
        }:
            thumb = info.get("thumb_path") or info.get("preview_path", "")
            if thumb and Path(thumb).exists():
                texture = GdkPixbuf.Pixbuf.new_from_file(thumb)
                self._image_preview.set_pixbuf(texture)
                self._image_preview.set_visible(True)
            elif path.exists():
                try:
                    texture = GdkPixbuf.Pixbuf.new_from_file(str(path))
                    self._image_preview.set_pixbuf(texture)
                    self._image_preview.set_visible(True)
                except Exception:
                    pass
            return

        if category in {"document", "text", "code"}:
            text = bridge.extract_text(path)
            if text:
                buffer.set_text(text[:2000])
                self._text_preview.set_visible(True)

    def _on_tag_added(self, editor, tag: str):
        if self._file_id is not None:
            self.emit("apply_tag", self._file_id, tag)

    def _on_tag_removed(self, editor, tag: str):
        if self._file_id is not None:
            self.emit("remove_tag", self._file_id, tag)

    @staticmethod
    def _format_size(b: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if b < 1024:
                return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def clear(self):
        self._file_id = None
        self._current_path = ""
        self._title.set_text("")
        self._path_label.set_text("")
        self._type_label.set_text("")
        self._size_label.set_text("")
        self._modified_label.set_text("")
        self._sha_label.set_text("")
        self._image_preview.set_visible(False)
        self._text_preview.set_visible(False)
        self._summary_label.set_visible(False)
        self._tag_editor.clear()
        self._empty.set_visible(True)
