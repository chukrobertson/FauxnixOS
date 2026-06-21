"""Fauxnix Nexus Host — Windows desktop app for the Nexus compute provider.

System tray app with:
- Chat window (Nexus Admin with gemma4)
- Status dashboard (network, models, connections)
- Configuration settings
- Ollama model access for connected Fauxnix nodes
"""

import sys
import os
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QSystemTrayIcon, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction

# Ensure local imports work
sys.path.insert(0, os.path.dirname(__file__))

from ollama_client import get_models, ollama_health
from chat_window import ChatWindow
from coder_window import CoderWindow
from status_dashboard import StatusDashboard

APP_NAME = "Fauxnix Nexus Host"


class MainWindow(QWidget):
    """Main window with tabs: Chat, Coder, Status."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(800, 600)
        self.resize(860, 650)
        self.setStyleSheet("background: #0d0e12;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #0d0e12; }
            QTabBar::tab { background: #141518; color: #888; border: 1px solid #1e1e24;
                padding: 6px 18px; margin-right: 2px; border-top-left-radius: 6px;
                border-top-right-radius: 6px; font-size: 12px; }
            QTabBar::tab:selected { background: #1c1e23; color: #ff7800; }
            QTabBar::tab:hover:!selected { color: #b0b0b0; }
        """)

        self._chat = ChatWindow()
        self._coder = CoderWindow()
        self._status = StatusDashboard()

        self._tabs.addTab(self._chat, "Chat")
        self._tabs.addTab(self._coder, "Coder")
        self._tabs.addTab(self._status, "Status")
        layout.addWidget(self._tabs)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Tray icon
    tray = QSystemTrayIcon()
    # Use a simple colored icon (16x16 orange square)
    from PyQt6.QtGui import QPixmap, QPainter, QColor
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setBrush(QColor("#ff7800"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 12, 12, 3, 3)
    painter.end()
    tray.setIcon(QIcon(pix))
    tray.setToolTip(APP_NAME)

    # Main window — must exist before tray menu references it
    window = MainWindow()
    window.show()

    # Tray menu
    tray_menu = QMenu()
    show_action = QAction("Show", tray_menu)
    show_action.triggered.connect(window.show)
    tray_menu.addAction(show_action)

    quit_action = QAction("Quit", tray_menu)
    quit_action.triggered.connect(app.quit)
    tray_menu.addAction(quit_action)

    tray.setContextMenu(tray_menu)
    tray.show()

    _NW = subprocess.CREATE_NO_WINDOW

    # Launch faux-pass provider (check if already running first)
    def _launch_provider():
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        provider_exe = os.path.join(app_dir, "FauxnixFauxPass.exe")
        if os.path.exists(provider_exe):
            existing = None
            try:
                existing = subprocess.run(
                    ["powershell.exe", "-Command",
                     "Get-CimInstance Win32_Process -Filter \"Name='FauxnixFauxPass.exe'\" | Select-Object -ExpandProperty ProcessId"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=_NW,
                )
            except Exception:
                pass
            if not (existing and existing.stdout.strip()):
                subprocess.Popen(
                    [provider_exe, "--host", "100.126.117.60", "--port", "4433"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_NW,
                )

    # Status check on startup
    def _startup_check():
        health = ollama_health()
        if health:
            models = get_models()
            tray.setToolTip(f"{APP_NAME}\nOllama online — {len(models)} models")
        else:
            tray.setToolTip(f"{APP_NAME}\nOllama offline")
    QTimer.singleShot(1000, _startup_check)
    QTimer.singleShot(2000, _launch_provider)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
