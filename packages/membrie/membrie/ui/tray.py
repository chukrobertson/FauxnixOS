from __future__ import annotations

import os
import sys
import threading

try:
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QWidget
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont, QFontDatabase
    HAS_QT = True
except ImportError:
    HAS_QT = False

from membrie.services import ServicesManager
from membrie.db import init_membrie_db


class MembrieTray:
    def __init__(self):
        self.app = QApplication(sys.argv) if HAS_QT else None
        self._tray = None
        self._services = ServicesManager()
        self._otg_running = False
        self._window = None

    def run(self):
        if not HAS_QT:
            print("PyQt6 not installed. Running headless services only.")
            self._services.start()
            return

        self._setup_tray()
        self._services.start()
        self._start_otg()
        QTimer.singleShot(500, self._maybe_open_window)
        self.app.exec()

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self._gen_icon())
        self._tray.setToolTip("Membrie — FauxnixOS Companion")

        menu = QMenu()

        open_action = menu.addAction("Open Membrie")
        open_action.triggered.connect(self._toggle_window)

        menu.addSeparator()

        otg_action = menu.addAction("Start OTG Server")
        otg_action.setCheckable(True)
        otg_action.triggered.connect(lambda checked: self._toggle_otg(checked))

        menu.addSeparator()

        status_menu = menu.addMenu("Status")
        self._drift_action = status_menu.addAction("Drift: --")
        self._drift_action.setEnabled(False)

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        self._tray.setContextMenu(menu)
        self._tray.show()

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(10000)

    def _gen_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#4caf50"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Sans", 30, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "M")
        painter.end()
        return QIcon(pixmap)

    def _update_status(self):
        from membrie.awareness.drift import get_drift_status, get_focus_state
        drift = get_drift_status()
        focus = get_focus_state()
        state = drift.get("state", "unknown")
        cat = drift.get("category", "")
        status_text = f"Status: {state}"
        if cat:
            status_text += f" ({cat})"
        if focus.get("in_focus"):
            streak = focus.get("current_streak", 0)
            status_text += f" 🔵{(streak // 60)}m focus"
        if self._drift_action:
            self._drift_action.setText(status_text)

    def _toggle_window(self):
        if self._window is None:
            from membrie.ui.window import MembrieWindow
            self._window = MembrieWindow(self._services)
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _maybe_open_window(self):
        pass

    def _toggle_otg(self, enabled: bool):
        if enabled and not self._otg_running:
            self._start_otg()
        elif not enabled and self._otg_running:
            self._otg_running = False

    def _start_otg(self):
        if self._otg_running:
            return
        self._otg_running = True
        t = threading.Thread(target=self._run_otg, daemon=True, name="otg_server")
        t.start()

    def _run_otg(self):
        from membrie.web.otg_server import run_otg_server
        run_otg_server()

    def _quit(self):
        self._services.stop()
        self._otg_running = False
        if self.app:
            self.app.quit()


def run_tray():
    init_membrie_db()
    tray = MembrieTray()
    tray.run()
