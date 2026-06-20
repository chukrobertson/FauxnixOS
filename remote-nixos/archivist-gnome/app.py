import os, sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, Adw, Gio, GLib

from .config import APP_ID, APP_NAME, DATA_DIR, DB_PATH
from .window import ArchivistWindow


class ArchivistApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.set_resource_base_path("/org/fauxnix/archivist")

        self._window: ArchivistWindow | None = None
        self._setup_actions()

    def _setup_actions(self):
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        help_action = Gio.SimpleAction.new("help", None)
        help_action.connect("activate", self._on_help)
        self.add_action(help_action)

    def _on_about(self, *args):
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="org.fauxnix.Archivist",
            version="0.1.0",
            developer_name="FauxnixOS",
            license_type=Gtk.License.MIT_X11,
            comments="Semantic file manager with AI-powered search, OCR, transcription, and archive management.",
            developers=["Fauxnix Team"],
        )
        dialog.present(self._window)

    def _on_help(self, *args):
        dialog = Adw.MessageDialog(
            transient_for=self._window,
            heading="Fauxnix Archivist",
            body=(
                "Browse, search, and manage your files with semantic understanding.\n\n"
                "• Type in the search bar for keyword or natural-language queries\n"
                "• Browse files by directory in the sidebar\n"
                "• View file previews and metadata in the detail pane\n"
                "• Tag files for organization\n"
                "• Index watched directories for full-text and semantic search"
            ),
        )
        dialog.add_response("ok", "OK")
        dialog.present(self._window)

    def do_activate(self):
        if self._window:
            self._window.present()
            return
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        self._window = ArchivistWindow(application=self)
        self._window.present()
