"""Index progress dialog — scan watched directories with progress reporting."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

if TYPE_CHECKING:
    from ..services.archivist_bridge import ArchivistBridge


class IndexProgressDialog(Adw.Dialog):
    def __init__(self, parent, bridge: ArchivistBridge, roots: list[Path]):
        super().__init__()
        self.set_title("Indexing Files")
        self.set_content_width(400)
        self.set_content_height(300)

        self._bridge = bridge
        self._roots = roots
        self._cancelled = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        self._label = Gtk.Label(label="Indexing watched directories...")
        self._label.set_wrap(True)
        self._label.set_halign(Gtk.Align.START)
        box.append(self._label)

        self._progress = Gtk.ProgressBar()
        self._progress.set_fraction(0.0)
        self._progress.set_show_text(True)
        box.append(self._progress)

        self._file_count = Gtk.Label(label="")
        self._file_count.set_halign(Gtk.Align.START)
        self._file_count.add_css_class("caption")
        box.append(self._file_count)

        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.set_halign(Gtk.Align.CENTER)
        self._cancel_btn.connect("clicked", self._on_cancel)
        box.append(self._cancel_btn)

        self.set_child(box)
        self.present(parent)

        GLib.idle_add(self._run_index)

    def _on_cancel(self, *args):
        self._cancelled = True
        self._label.set_text("Cancelling...")

    def _run_index(self):
        all_files = []
        for root in self._roots:
            if not root.exists():
                continue
            try:
                all_files.extend(
                    p for p in root.rglob("*")
                    if p.is_file() and not p.name.startswith(".")
                )
            except (PermissionError, OSError):
                continue

        total = len(all_files)
        if total == 0:
            self._label.set_text("No new files to index.")
            self._progress.set_fraction(1.0)
            self._cancel_btn.set_label("Close")
            self._cancel_btn.remove_css_class("destructive-action")
            self._cancel_btn.connect("clicked", self.close)
            return False

        self._label.set_text(f"Indexing {total} files...")
        self._bridge.index_paths(
            all_files,
            progress_cb=self._on_progress,
        )
        self._label.set_text(f"Indexed {total} files.")
        self._progress.set_fraction(1.0)
        self._cancel_btn.set_label("Close")
        self._cancel_btn.remove_css_class("destructive-action")
        self._cancel_btn.connect("clicked", self.close)
        return False

    def _on_progress(self, current: int, total: int):
        self._progress.set_fraction(min(1.0, current / total))
        self._file_count.set_text(f"{current} / {total}")
        return not self._cancelled
