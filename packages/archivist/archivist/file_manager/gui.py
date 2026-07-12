from __future__ import annotations

import sys

try:
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
        QTreeView, QListView, QTextEdit, QLabel, QLineEdit, QPushButton,
        QToolBar, QStatusBar, QMenu, QFileDialog, QMessageBox,
        QTabWidget, QListWidget, QListWidgetItem, QComboBox,
        QCheckBox, QFrame, QApplication,
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QDir, QFileInfo, QFileSystemModel
    from PyQt6.QtGui import QAction, QFont, QIcon, QColor, QPalette
    HAS_QT = True
except ImportError:
    HAS_QT = False

from archivist.file_manager import browse_directory, browse_indexed, get_file_detail, recent_files, file_statistics
from archivist.file_manager.viewer import preview_file
from archivist.file_manager.daemon import list_watched_directories, add_watched_directory, remove_watched_directory, scan_now
from archivist.smart_actions import auto_classify_file, detect_duplicates, suggest_rename, smart_summarize_directory
from archivist.translation import translate_document, translate_video_subtitles, translation_status
from archivist.organizer import apply_rules_to_file, suggest_organization, list_rules
from archivist.search import search_everything, search_files, search_by_tag, search_duplicates


class ArchivistWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Archivist — FauxnixOS File Manager")
        self.resize(1100, 700)
        self._current_path = str(Path.home())
        self._current_file_id = None
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        toolbar = QToolBar()
        home_action = toolbar.addAction("Home")
        home_action.triggered.connect(lambda: self._navigate(str(Path.home())))
        toolbar.addSeparator()
        self._path_input = QLineEdit(self._current_path)
        self._path_input.returnPressed.connect(lambda: self._navigate(self._path_input.text()))
        toolbar.addWidget(self._path_input)
        go_btn = QPushButton("Go")
        go_btn.clicked.connect(lambda: self._navigate(self._path_input.text()))
        toolbar.addWidget(go_btn)
        layout.addWidget(toolbar)

        search_bar = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search files, tags, faces, content...")
        self._search_input.returnPressed.connect(self._search)
        search_bar.addWidget(self._search_input)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._search)
        search_bar.addWidget(search_btn)
        layout.addLayout(search_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self._file_list = QListWidget()
        self._file_list.setAlternatingRowColors(True)
        self._file_list.itemDoubleClicked.connect(self._on_file_double_click)
        self._file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_list.customContextMenuRequested.connect(self._file_context_menu)
        left_layout.addWidget(self._file_list)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self._preview_tabs = QTabWidget()
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setFont(QFont("monospace", 10))
        self._preview_tabs.addTab(self._preview_text, "Preview")

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._preview_tabs.addTab(self._detail_text, "Details")
        right_layout.addWidget(self._preview_tabs)
        splitter.addWidget(right_panel)

        splitter.setSizes([500, 600])
        layout.addWidget(splitter)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        self._setup_menus()

        self._navigate(self._current_path)

    def _setup_menus(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        add_watch = file_menu.addAction("Add Watched Directory...")
        add_watch.triggered.connect(self._add_watched_dir)
        file_menu.addSeparator()
        file_menu.addAction("Exit").triggered.connect(self.close)

        tools_menu = mb.addMenu("Tools")
        tools_menu.addAction("Scan All Watched Dirs").triggered.connect(self._scan_all)
        tools_menu.addAction("Find Duplicates").triggered.connect(self._find_dupes)
        tools_menu.addAction("Statistics").triggered.connect(self._show_stats)

        org_menu = mb.addMenu("Organize")
        org_menu.addAction("Organize Current File").triggered.connect(self._organize_file)
        org_menu.addAction("Suggest Organization").triggered.connect(self._suggest_org)
        org_menu.addAction("AI Classify").triggered.connect(self._ai_classify)
        org_menu.addAction("Detect Duplicates").triggered.connect(self._check_dup)

        trans_menu = mb.addMenu("Translate")
        for lang in ["English", "Spanish", "French", "German", "Chinese", "Japanese", "Korean", "Russian", "Arabic"]:
            action = trans_menu.addAction(f"To {lang}")
            action.triggered.connect(lambda checked, l=lang.lower(): self._translate(l))

    def _navigate(self, path: str):
        self._current_path = path
        self._path_input.setText(path)
        self._file_list.clear()
        self._status_bar.showMessage(f"Loading {path}...")

        result = browse_directory(path)
        if not result.get("ok"):
            QMessageBox.warning(self, "Error", result.get("error", "Unknown error"))
            return

        dirs = []
        files = []
        for entry in result.get("entries", []):
            prefix = "[DIR] " if entry.get("is_dir") else f"[{entry.get('category', '?')}] "
            item_text = f"{prefix}{entry['name']}"
            if not entry.get("is_dir") and entry.get("size"):
                item_text += f"  ({_human_size(entry['size'])})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            if entry.get("is_dir"):
                item.setForeground(QColor("#64b5f6"))
                dirs.append(item)
            else:
                files.append(item)

        for item in dirs + files:
            self._file_list.addItem(item)

        self._status_bar.showMessage(f"{result.get('total', 0)} entries in {path}")

    def _on_file_double_click(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        if entry.get("is_dir"):
            self._navigate(entry["path"])
        else:
            self._preview_file(entry["path"])
            self._show_details(entry["path"])

    def _preview_file(self, path: str):
        self._preview_text.clear()
        self._status_bar.showMessage("Loading preview...")
        result = preview_file(path)
        if result.get("ok"):
            self._preview_text.setPlainText(result.get("preview", ""))
            self._status_bar.showMessage(f"Preview: {result.get('size_human', '')} | {result.get('preview_type', '')}")

            if result.get("preview_type") == "video" and result.get("thumbnails"):
                text = f"Video: {result.get('duration_human', '?')}\nCodec: {result.get('codec', '?')}\n\n[Thumbnails generated: {len(result['thumbnails'])} frames]"
                self._preview_text.setPlainText(text)

    def _show_details(self, path: str):
        self._detail_text.clear()
        try:
            from fauxnix_tools.db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, path, name, ext, category, mime_type, size_bytes, sha256, summary, extracted_text, indexed_ts FROM files WHERE path = ?", (path,))
            row = cur.fetchone()
            conn.close()
            if row:
                d = dict(row)
                self._current_file_id = d.get("id")
                detail = f"Name: {d.get('name', '?')}\n"
                detail += f"Path: {d.get('path', '?')}\n"
                detail += f"Type: {d.get('mime_type', '?')} | Category: {d.get('category', '?')}\n"
                detail += f"Size: {_human_size(d.get('size_bytes', 0))} | Hash: {d.get('sha256', '?')[:16]}...\n"
                detail += f"Summary: {d.get('summary', 'N/A')}\n"
                if d.get("extracted_text"):
                    detail += f"Extracted text: {len(d.get('extracted_text', ''))} chars"
                self._detail_text.setPlainText(detail)
            else:
                self._detail_text.setPlainText(f"File not yet indexed: {path}")
        except Exception as e:
            self._detail_text.setPlainText(f"Error: {e}")

    def _file_context_menu(self, pos):
        item = self._file_list.itemAt(pos)
        if not item:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or entry.get("is_dir"):
            return

        menu = QMenu()
        menu.addAction("Preview").triggered.connect(lambda: self._preview_file(entry["path"]))
        menu.addAction("Details").triggered.connect(lambda: self._show_details(entry["path"]))
        menu.addSeparator()
        menu.addAction("Organize").triggered.connect(lambda: self._organize_file_path(entry["path"]))
        menu.addAction("AI Classify").triggered.connect(lambda: self._classify_file_path(entry["path"]))
        menu.addAction("Detect Duplicates").triggered.connect(lambda: self._dup_file_path(entry["path"]))
        menu.addAction("Suggest Rename").triggered.connect(lambda: self._rename_file_path(entry["path"]))
        menu.addSeparator()
        menu.addAction("Translate").triggered.connect(lambda: self._translate_file_path(entry["path"]))
        menu.exec(self._file_list.viewport().mapToGlobal(pos))

    def _search(self):
        query = self._search_input.text().strip()
        if not query:
            return
        self._file_list.clear()
        self._status_bar.showMessage(f"Searching: {query}...")
        results = browse_indexed(query=query)
        for f in results.get("files", []):
            item_text = f"[{f.get('category', '?')}] {f['name']} — {f.get('summary', '')[:40]}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, {"path": f["path"], "is_dir": False, "category": f.get("category")})
            self._file_list.addItem(item)
        self._status_bar.showMessage(f"Found {results.get('total', 0)} files for '{query}'")

    def _add_watched_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Directory to Watch")
        if path:
            add_watched_directory(path)

    def _scan_all(self):
        result = scan_now()
        QMessageBox.information(self, "Scan Complete", f"Scanned {result.get('scanned', 0)} directories.")

    def _find_dupes(self):
        self._file_list.clear()
        result = search_duplicates()
        for dup in result.get("duplicate_groups", []):
            item_text = f"[DUP] {dup['count']} files — {_human_size(dup['potential_waste'])} wasted"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, {"paths": dup["paths"]})
            self._file_list.addItem(item)
        self._status_bar.showMessage(f"Found {result.get('total_groups', 0)} duplicate groups")

    def _show_stats(self):
        stats = file_statistics()
        msg = f"Total files: {stats.get('total_files', 0)}\n"
        msg += f"Total size: {_human_size(stats.get('total_bytes', 0))}\n"
        msg += f"Faces: {stats.get('total_faces', 0)} ({stats.get('named_faces', 0)} named)\n"
        msg += f"Tags: {stats.get('total_tags', 0)}\n\n"
        msg += "By category:\n"
        for cat, count in stats.get("by_category", {}).items():
            msg += f"  {cat}: {count}\n"
        QMessageBox.information(self, "File Statistics", msg)

    def _organize_file(self):
        item = self._file_list.currentItem()
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and not entry.get("is_dir"):
                self._organize_file_path(entry["path"])

    def _organize_file_path(self, path: str):
        result = apply_rules_to_file(path)
        if result.get("action") != "none":
            QMessageBox.information(self, "Organized", f"Moved to: {result.get('dest', '?')}")
        else:
            suggest = suggest_organization(path)
            suggestions = [f"→ {s['folder']} ({s['reason']})" for s in suggest.get("suggestions", [])]
            QMessageBox.information(self, "Suggestions", "\n".join(suggestions[:3]) or "No suggestions.")

    def _suggest_org(self):
        item = self._file_list.currentItem()
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and not entry.get("is_dir"):
                self._organize_file_path(entry["path"])

    def _ai_classify(self):
        item = self._file_list.currentItem()
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and not entry.get("is_dir"):
                self._classify_file_path(entry["path"])

    def _classify_file_path(self, path: str):
        self._status_bar.showMessage("Classifying with AI...")
        result = auto_classify_file(path)
        if result.get("ok"):
            c = result.get("classification", {})
            msg = f"Category: {c.get('category', '?')}\nTitle: {c.get('title', '?')}\nTags: {', '.join(c.get('tags', []))}\nSummary: {c.get('summary', '?')}"
            QMessageBox.information(self, "AI Classification", msg)

    def _check_dup(self):
        item = self._file_list.currentItem()
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and not entry.get("is_dir"):
                self._dup_file_path(entry["path"])

    def _dup_file_path(self, path: str):
        result = detect_duplicates(path)
        msg = "No duplicates found."
        if result.get("has_exact_dupes"):
            dupes = result.get("exact_duplicates", [])
            msg = f"Found {len(dupes)} exact duplicates:\n" + "\n".join(d["path"] for d in dupes[:5])
        elif result.get("similar"):
            sim = result.get("similar", [])
            msg = f"Found {len(sim)} similar files:\n" + "\n".join(s["name"] for s in sim[:5])
        QMessageBox.information(self, "Duplicate Check", msg)

    def _rename_file_path(self, path: str):
        self._status_bar.showMessage("Generating rename suggestion...")
        result = suggest_rename(path)
        if result.get("ok"):
            msg = f"Current: {result.get('current_name', '?')}\nSuggested: {result.get('suggested_name', '?')}\nReason: {result.get('reason', '?')}"
            QMessageBox.information(self, "Rename Suggestion", msg)

    def _translate(self, target_lang: str):
        item = self._file_list.currentItem()
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and not entry.get("is_dir"):
                self._translate_file_path(entry["path"], target_lang)

    def _translate_file_path(self, path: str, target_lang: str = "english"):
        self._status_bar.showMessage(f"Translating to {target_lang}...")
        ext = Path(path).suffix.lower()
        if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
            result = translate_video_subtitles(path, target_lang)
        else:
            result = translate_document(path, target_lang)

        if result.get("ok"):
            text = result.get("translated_text", "")[:3000]
            self._preview_text.setPlainText(text)
            self._status_bar.showMessage(f"Translated {result.get('translated_chars', 0)} chars to {target_lang}")
        else:
            QMessageBox.warning(self, "Translation Error", result.get("error", "Unknown error"))


def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
