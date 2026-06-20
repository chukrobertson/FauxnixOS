"""Search bar — keyword and semantic search with mode toggle."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, GObject


class SearchBar(Gtk.Box):
    __gsignals__ = {
        "search": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.set_hexpand(True)
        self.set_halign(Gtk.Align.FILL)

        self._entry = Gtk.SearchEntry()
        self._entry.set_placeholder_text("Search files by name, content, or describe what you need...")
        self._entry.set_hexpand(True)
        self._entry.connect("activate", self._on_search)
        self._entry.connect("search_changed", self._on_search)
        self.append(self._entry)

        self._mode_stack = Gtk.Stack()
        self._mode_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._keyword_label = Gtk.Label(label="Keyword")
        self._keyword_label.add_css_class("accent")
        self._mode_stack.add_child(self._keyword_label)

        self._semantic_label = Gtk.Label(label="Semantic")
        self._semantic_label.add_css_class("accent")
        self._mode_stack.add_child(self._semantic_label)

        self._mode_btn = Gtk.ToggleButton()
        self._mode_btn.set_child(self._mode_stack)
        self._mode_btn.set_tooltip_text("Toggle between keyword and semantic search")
        self._mode_btn.connect("toggled", self._on_mode_toggle)
        self.append(self._mode_btn)

        self._clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        self._clear_btn.set_tooltip_text("Clear search")
        self._clear_btn.connect("clicked", self._on_clear)
        self.append(self._clear_btn)

        self._mode = "keyword"

    def _on_search(self, *args):
        query = self._entry.get_text().strip()
        if query:
            self.emit("search", query, self._mode)

    def _on_mode_toggle(self, btn):
        if btn.get_active():
            self._mode_stack.set_visible_child(self._semantic_label)
            self._mode = "semantic"
            self._entry.set_placeholder_text(
                "Describe the file you're looking for..."
            )
        else:
            self._mode_stack.set_visible_child(self._keyword_label)
            self._mode = "keyword"
            self._entry.set_placeholder_text(
                "Search files by name, content..."
            )

    def _on_clear(self, *args):
        self._entry.set_text("")
        self._entry.grab_focus()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def query(self) -> str:
        return self._entry.get_text().strip()
