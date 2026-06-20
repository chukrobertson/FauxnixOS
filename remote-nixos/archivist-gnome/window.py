"""Main Archivist window — three-pane file manager layout."""

from __future__ import annotations

import os
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, Gio, GLib, GdkPixbuf

from .config import APP_NAME, WATCHED_ROOTS, DATA_DIR, PREVIEW_DIR, THUMBS_DIR
from .widgets.directory_tree import DirectoryTreeWidget
from .widgets.file_list import FileListWidget
from .widgets.preview_pane import PreviewPane
from .widgets.search_bar import SearchBar
from .services.archivist_bridge import ArchivistBridge


class ArchivistWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1200, 800)
        self._bridge = ArchivistBridge(DATA_DIR)

        self._build_header()
        self._build_main()
        self._connect_signals()
        self._init_bridge()

    def _build_header(self):
        header = Adw.HeaderBar()
        self._search_bar = SearchBar()
        header.set_title_widget(self._search_bar)

        self._index_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self._index_btn.set_tooltip_text("Index watched directories")
        header.pack_start(self._index_btn)

        menu = Gio.Menu()
        menu.append("About", "app.about")
        menu.append("Help", "app.help")
        popover = Gtk.PopoverMenu()
        popover.set_menu_model(menu)
        self._menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        self._menu_btn.set_popover(popover)
        header.pack_end(self._menu_btn)

        self._stats_label = Gtk.Label(label="")
        self._stats_label.add_css_class("subtitle")
        header.pack_end(self._stats_label)

        self.set_titlebar(header)

    def _build_main(self):
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(240)
        paned.set_wide_handle(True)

        self._sidebar = DirectoryTreeWidget()
        scrolled_sidebar = Gtk.ScrolledWindow()
        scrolled_sidebar.set_child(self._sidebar)
        scrolled_sidebar.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC
        )
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack = Adw.ViewSwitcher(
            stack=self._sidebar_stack(),
            policy=Adw.ViewSwitcherPolicy.WIDE,
        )
        sidebar_box.append(self._view_stack)
        sidebar_box.append(scrolled_sidebar)
        paned.set_start_child(sidebar_box)

        content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content_paned.set_position(700)

        self._file_list = FileListWidget()
        scrolled_list = Gtk.ScrolledWindow()
        scrolled_list.set_child(self._file_list)
        scrolled_list.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        content_paned.set_start_child(scrolled_list)

        self._preview = PreviewPane()
        scrolled_preview = Gtk.ScrolledWindow()
        scrolled_preview.set_child(self._preview)
        content_paned.set_end_child(scrolled_preview)

        paned.set_end_child(content_paned)
        self.set_content(paned)

    def _sidebar_stack(self):
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(
            Gtk.Label(label="Directory Tree"),
            "folders", "Folders", "folder-symbolic",
        )
        stack.add_titled_with_icon(
            Gtk.Label(label="Tags"),
            "tags", "Tags", "tag-symbolic",
        )
        stack.add_titled_with_icon(
            Gtk.Label(label="Sources"),
            "sources", "Sources", "drive-harddisk-symbolic",
        )
        return stack

    def _connect_signals(self):
        self._search_bar.connect("search", self._on_search)
        self._sidebar.connect("row_activated", self._on_directory_selected)
        self._file_list.connect("file_selected", self._on_file_selected)
        self._preview.connect("apply_tag", self._on_apply_tag)
        self._preview.connect("remove_tag", self._on_remove_tag)
        self._index_btn.connect("clicked", self._on_index)

    def _init_bridge(self):
        if not self._bridge.initialize():
            self._show_error(
                "Archivist Core Unavailable",
                f"Cannot load archivist modules. {self._bridge.error or ''}",
            )
            return
        self._refresh_stats()

    def _show_error(self, heading: str, body: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=heading,
            body=body,
        )
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def _on_search(self, search_bar, query: str, mode: str):
        if not query.strip():
            return
        results = []
        if mode == "semantic":
            results = self._bridge.search(query)
        else:
            results = self._bridge.search_keyword(query)
        self._file_list.show_search_results(results, query)

    def _on_directory_selected(self, tree, path: Path):
        self._file_list.load_directory(path, self._bridge)
        self._sidebar.set_active_path(path)

    def _on_file_selected(self, file_list, file_info: dict):
        self._preview.show_file(file_info, self._bridge)

    def _on_apply_tag(self, preview, file_id: int, tag: str):
        self._bridge.apply_tag([file_id], tag)
        self._refresh_stats()

    def _on_remove_tag(self, preview, file_id: int, tag: str):
        self._bridge.remove_tag([file_id], tag)
        self._refresh_stats()

    def _on_index(self, _btn):
        GLib.idle_add(self._run_index)

    def _run_index(self):
        from .widgets.index_progress import IndexProgressDialog
        dialog = IndexProgressDialog(self, self._bridge, WATCHED_ROOTS)
        dialog.run()

    def _refresh_stats(self):
        stats = self._bridge.stats()
        self._stats_label.set_label(
            f"{stats.get('files', 0)} files  ·  {stats.get('tags', 0)} tags"
        )
