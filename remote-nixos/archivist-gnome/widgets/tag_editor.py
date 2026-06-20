"""Tag editor — add/remove tags from files."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, GObject, Gio


class TagEditor(Gtk.Box):
    __gsignals__ = {
        "tag_added": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "tag_removed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        header = Gtk.Label(label="Tags")
        header.add_css_class("heading")
        header.set_halign(Gtk.Align.START)
        self.append(header)

        self._flow = Gtk.FlowBox()
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_max_children_per_line(6)
        self._flow.set_min_children_per_line(1)
        self._flow.set_column_spacing(4)
        self._flow.set_row_spacing(4)
        self.append(self._flow)

        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("Add tag...")
        self._entry.set_hexpand(True)
        self._entry.connect("activate", self._on_add)
        add_box.append(self._entry)

        self._add_btn = Gtk.Button(label="Add")
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.connect("clicked", self._on_add)
        add_box.append(self._add_btn)

        self.append(add_box)

    def _on_add(self, *args):
        tag = self._entry.get_text().strip()
        if not tag:
            return
        self.emit("tag_added", tag)
        self._add_tag_chip(tag)
        self._entry.set_text("")

    def load_file_tags(self, file_id: int | None, bridge=None):
        self._flow.remove_all()
        if not file_id or not bridge:
            return
        try:
            tags = bridge.list_tags()
            for t in tags:
                self._add_tag_chip(t["name"])
        except Exception:
            pass

    def _add_tag_chip(self, tag: str):
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        chip.set_margin_start(4)
        chip.set_margin_end(4)
        chip.set_margin_top(2)
        chip.set_margin_bottom(2)
        chip.add_css_class("tag-chip")

        label = Gtk.Label(label=tag)
        chip.append(label)

        remove = Gtk.Button(icon_name="window-close-symbolic")
        remove.add_css_class("flat")
        remove.add_css_class("circular")
        remove.set_tooltip_text(f"Remove tag '{tag}'")
        remove.connect("clicked", self._on_remove, tag)
        chip.append(remove)

        self._flow.insert(chip, -1)

    def _on_remove(self, btn, tag: str):
        parent = btn.get_parent()
        self._flow.remove(parent)
        self.emit("tag_removed", tag)

    def clear(self):
        self._flow.remove_all()
