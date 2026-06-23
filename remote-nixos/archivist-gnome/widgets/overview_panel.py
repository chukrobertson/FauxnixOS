"""Archivist overview strip with status and common actions."""

from __future__ import annotations

from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, GObject, Pango


class OverviewPanel(Gtk.Box):
    __gsignals__ = {
        "refresh_requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "index_requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "show_recent_requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "show_duplicates_requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "show_failures_requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(8)
        self.set_margin_bottom(8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_hexpand(True)
        self.append(header)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        header.append(title_box)

        title = Gtk.Label(label="Archivist Control")
        title.add_css_class("heading")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        self._root = Gtk.Label(label="Archive root: unknown")
        self._root.add_css_class("caption")
        self._root.set_halign(Gtk.Align.START)
        self._root.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title_box.append(self._root)

        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self.emit("refresh_requested"))
        header.append(refresh)

        index = Gtk.Button(label="Index watched roots")
        index.add_css_class("suggested-action")
        index.connect("clicked", lambda *_: self.emit("index_requested"))
        header.append(index)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        self.append(grid)

        self._files = self._stat_card(grid, 0, 0, "Files", "0")
        self._size = self._stat_card(grid, 1, 0, "Indexed size", "0 B")
        self._dupes = self._stat_card(grid, 2, 0, "Duplicates", "0")
        self._failures = self._stat_card(grid, 3, 0, "Failures", "0")
        self._delete_queue = self._stat_card(grid, 4, 0, "Delete queue", "0")
        self._disk = self._stat_card(grid, 5, 0, "Disk", "0%")

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.append(actions)
        for label, signal in (
            ("Recent indexed", "show_recent_requested"),
            ("Duplicates", "show_duplicates_requested"),
            ("Failures", "show_failures_requested"),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _btn, sig=signal: self.emit(sig))
            actions.append(button)

        self._last_indexed = Gtk.Label(label="Last indexed: never")
        self._last_indexed.add_css_class("caption")
        self._last_indexed.set_halign(Gtk.Align.START)
        self.append(self._last_indexed)

    def _stat_card(self, grid: Gtk.Grid, col: int, row: int, title: str, value: str) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("card")
        box.set_hexpand(True)
        box.set_margin_top(2)
        box.set_margin_bottom(2)
        box.set_margin_start(2)
        box.set_margin_end(2)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("caption")
        title_label.set_halign(Gtk.Align.START)
        box.append(title_label)

        value_label = Gtk.Label(label=value)
        value_label.add_css_class("title-3")
        value_label.set_halign(Gtk.Align.START)
        box.append(value_label)
        grid.attach(box, col, row, 1, 1)
        return value_label

    def update_stats(self, stats: dict):
        self._root.set_text(f"Archive root: {stats.get('archive_root') or 'unknown'}")
        self._files.set_text(str(stats.get("active_file_count") or stats.get("file_count") or 0))
        self._size.set_text(_format_size(stats.get("active_bytes") or stats.get("total_bytes") or 0))
        self._dupes.set_text(
            f"{stats.get('duplicate_groups') or 0} / "
            f"{_format_size(stats.get('duplicate_reclaimable_bytes') or 0)}"
        )
        self._failures.set_text(str(stats.get("index_failure_count") or 0))
        self._delete_queue.set_text(str(stats.get("delete_queue_count") or 0))
        disk = stats.get("disk_usage") or {}
        self._disk.set_text(f"{disk.get('percent_used') or 0}%")
        self._last_indexed.set_text(f"Last indexed: {_format_ts(stats.get('last_indexed_ts'))}")


def _format_size(size_bytes: int | float | None) -> str:
    value = float(size_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def _format_ts(ts) -> str:
    if not ts:
        return "never"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(ts)
