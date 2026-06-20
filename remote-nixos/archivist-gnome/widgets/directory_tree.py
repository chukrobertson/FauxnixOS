"""Sidebar directory tree — browse filesystem roots."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, GObject


class DirectoryTreeWidget(Gtk.ScrolledWindow):
    __gsignals__ = {
        "row_activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, roots: list[Path] | None = None):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._roots = roots or [
            Path.home(),
            Path.home() / "Downloads",
            Path.home() / "Documents",
            Path.home() / "Pictures",
            Path.home() / "Desktop",
        ]
        self._active_path: Path | None = None
        self._store = Gtk.TreeStore.new([str, str, bool])
        self._tree = Gtk.TreeView.new_with_model(self._store)
        self._tree.set_headers_visible(False)
        self._tree.set_activate_on_single_click(True)

        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn.new()
        col.pack_start(renderer, True)
        col.add_attribute(renderer, "text", 0)
        self._tree.append_column(col)

        self._tree.connect("row-activated", self._on_row_activated)
        self.set_child(self._tree)
        self._populate_roots()

    def _populate_roots(self):
        self._store.clear()
        for root in self._roots:
            if root.exists():
                parent = self._store.append(None, [root.name or str(root), str(root), True])
                self._lazy_load(parent, root)

    def _lazy_load(self, tree_iter: Gtk.TreeIter, path: Path):
        try:
            items = sorted(
                [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")],
                key=lambda p: p.name.lower(),
            )
        except (PermissionError, OSError):
            return
        for item in items:
            child = self._store.append(tree_iter, [item.name, str(item), False])
            self._lazy_placeholder(child, item)

    def _lazy_placeholder(self, tree_iter: Gtk.TreeIter, path: Path):
        try:
            has_children = any(
                p.is_dir() and not p.name.startswith(".")
                for p in path.iterdir()
            )
        except (PermissionError, OSError):
            return
        if has_children:
            self._store.append(tree_iter, ["", "", False])

    def _on_row_activated(self, tree: Gtk.TreeView, path: Gtk.TreePath, col):
        store_iter = self._store.get_iter(path)
        full_path = self._store.get_value(store_iter, 1)
        if not full_path:
            return
        p = Path(full_path)
        if not p.exists():
            return
        self._active_path = p
        parent_iter = self._store.iter_parent(store_iter)
        if parent_iter:
            self._expand_and_load(store_iter, p)
        self.emit("row_activated", p)

    def _expand_and_load(self, tree_iter: Gtk.TreePath, path: Path):
        self._store.remove(self._store.iter_nth_child(tree_iter, 0))
        self._lazy_load(tree_iter, path)

    def set_active_path(self, path: Path):
        self._active_path = path
