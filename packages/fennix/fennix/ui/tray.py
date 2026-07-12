from __future__ import annotations

import sys
import threading

try:
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont
    HAS_QT = True
except ImportError:
    HAS_QT = False

from fennix.services import ServicesManager
from fennix.db import init_fennix_db


class FennixTray:
    def __init__(self, thread_name: str = "workspace"):
        self.app = QApplication(sys.argv) if HAS_QT else None
        self._tray: QSystemTrayIcon | None = None
        self._services = ServicesManager(thread_name)
        self._window = None
        self._quickbar = None

    def run(self):
        if not HAS_QT:
            print("PyQt6 not installed. Running headless services only.")
            self._services.start()
            import time
            import signal
            running = True
            def _shutdown(signum, frame):
                nonlocal running
                running = False
            signal.signal(signal.SIGINT, _shutdown)
            signal.signal(signal.SIGTERM, _shutdown)
            while running:
                time.sleep(1)
            self._services.stop()
            return

        _apply_profile_theme(self.app)
        self._setup_tray()
        self._services.start()
        self.app.exec()

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self._gen_icon())
        self._tray.setToolTip("Fennix — FauxnixOS Assistant")

        menu = QMenu()

        quick_action = menu.addAction("Quick Ask (Alt+Space)")
        quick_action.triggered.connect(self._toggle_quickbar)

        menu.addSeparator()

        open_action = menu.addAction("Open Fennix")
        open_action.triggered.connect(self._toggle_window)

        ingest_action = menu.addAction("Ingest File...")
        ingest_action.triggered.connect(self._ingest_file_dialog)

        menu.addSeparator()

        status_menu = menu.addMenu("Services")
        self._status_actions: dict[str, QAction] = {}
        for svc_name in ["clipboard_watcher", "open_files_tracker",
                          "system_state_logger", "auto_ingestion_scanner",
                          "file_change_reconciler", "context_streamer",
                          "git_watcher", "terminal_watcher", "browser_watcher"]:
            action = status_menu.addAction(svc_name.replace("_", " ").title())
            action.setCheckable(True)
            action.triggered.connect(lambda checked, n=svc_name: self._services.toggle_service(n, checked))
            self._status_actions[svc_name] = action

        menu.addSeparator()

        recall_action = menu.addAction("Recall Context")
        recall_action.triggered.connect(self._show_recall_context)

        menu.addSeparator()

        quit_action = menu.addAction("Quit Fennix")
        quit_action.triggered.connect(self._quit)

        self._tray.setContextMenu(menu)
        self._tray.show()

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(5000)

        self._register_hotkey()

    def _gen_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2196f3"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Sans", 30, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "F")
        painter.end()
        return QIcon(pixmap)

    def _update_status(self):
        if not self._status_actions:
            return
        for svc_name, action in self._status_actions.items():
            action.setChecked(self._services.service_running(svc_name))

    def _toggle_window(self):
        if self._window is None:
            from fennix.ui.window import FennixWindow
            self._window = FennixWindow(self._services)
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _toggle_quickbar(self):
        if self._quickbar is None:
            from fennix.ui.quickbar import QuickBar
            self._quickbar = QuickBar()
        if self._quickbar.isVisible():
            self._quickbar.hide()
        else:
            self._quickbar.show()
            self._quickbar.raise_()
            self._quickbar.activateWindow()
            self._quickbar.focus_input()

    def _ingest_file_dialog(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Select File to Ingest", "",
            "All Files (*);;Text Files (*.txt *.md *.py *.js *.ts *.rs *.go *.json *.yaml *.yml *.toml *.html *.css *.csv *.log *.sh);;PDF Files (*.pdf)"
        )
        if not path:
            return

        def _ingest():
            from fennix.ingestion.__init__ import ingest_content
            from fauxnix_tools.utils import sha256_file
            from pathlib import Path

            p = Path(path)
            if not p.exists():
                return
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return
            file_hash = sha256_file(p)
            ingest_content(
                file_path=str(p),
                file_hash=file_hash,
                content=content,
                source="manual",
            )
            from fennix.ui.window import FennixWindow
            if self._window is not None:
                self._window.update_ingested_list()

        t = threading.Thread(target=_ingest, daemon=True)
        t.start()

    def _show_recall_context(self):
        from fennix.assistant.__init__ import recall_context_for_query

        def _recall():
            from PyQt6.QtWidgets import QMessageBox
            results = recall_context_for_query("recent context overview")
            if not results:
                return
            lines = []
            for r in results[:5]:
                src = r.get("source", "?")
                content = (r.get("content") or "")[:200]
                score = r.get("score", 0)
                lines.append(f"[{src}] ({score:.2f}) {content}")
            if self._tray:
                self._tray.showMessage(
                    "Fennix Recall",
                    "\n\n".join(lines),
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )

        t = threading.Thread(target=_recall, daemon=True)
        t.start()

    def _register_hotkey(self):
        pass

    def _quit(self):
        self._services.stop()
        if self.app:
            self.app.quit()


def run_tray(thread_name: str = "workspace"):
    init_fennix_db()
    tray = FennixTray(thread_name)
    tray.run()


def _apply_profile_theme(app) -> None:
    try:
        from fennix.profile import read_profile_from_manifest
        from fennix.ui.themes import apply_theme
        profile = read_profile_from_manifest("/var/lib/workspaces")
        if profile and profile != "headless":
            apply_theme(app, profile)
    except Exception:
        pass
