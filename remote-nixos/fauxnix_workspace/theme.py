"""Fauxnix glass visual language — shared colour palette and QSS."""

from PyQt6.QtGui import QColor

# ── background & surface ──────────────────────────────────────────
CANVAS_BG = QColor("#080909")
CANVAS_DOT = QColor("#1a1a2a")
CANVAS_DOT_ALT = QColor("#222a3a")

# ── glass cards ───────────────────────────────────────────────────
NODE_BG = QColor("#141518")
NODE_BORDER = QColor("#2a2d33")
NODE_TITLE_BG = QColor("#1c1e23")
NODE_TITLE_FG = QColor("#d4d4d4")

# ── accent colours ────────────────────────────────────────────────
ORANGE = QColor("#ff7800")
ORANGE_DIM = QColor("#cc6600")
CYAN = QColor("#00c8ff")
CYAN_DIM = QColor("#0099cc")
WHITE = QColor("#e8e8e8")
GREEN = QColor("#00cc66")
RED = QColor("#ff4444")
YELLOW = QColor("#ffd54f")
PURPLE = QColor("#b366ff")

# ── selection ─────────────────────────────────────────────────────
SELECT_COLOR = ORANGE
SELECT_GLOW = QColor("#ff7800")

# ── data type colours (for sockets / wires) ──────────────────────
DATA_TYPE_COLORS: dict[str, QColor] = {
    "data":    QColor("#ffb74d"),
    "text":    QColor("#b0b0c0"),
    "command": QColor("#81c784"),
    "file":    QColor("#4fc3f7"),
    "url":     QColor("#ce93d8"),
    "event":   QColor("#ef5350"),
    "image":   QColor("#ef5350"),   # red
    "audio":   QColor("#4fc3f7"),   # blue
}

# ── wire defaults ─────────────────────────────────────────────────
WIRE_COLOR = ORANGE
WIRE_HOVER = YELLOW

# ── typography ────────────────────────────────────────────────────
try:
    TITLE_FONT = ("Inter", 10)
    BODY_FONT = ("Inter", 9)
except Exception:
    TITLE_FONT = ("Cantarell", 10)
    BODY_FONT = ("Cantarell", 9)

# ── application QSS ──────────────────────────────────────────────
APP_QSS = """
QMainWindow {
    background: #080909;
}
QToolBar {
    background: #0d0e12;
    border-bottom: 1px solid #1e1e24;
    spacing: 4px;
    padding: 4px;
}
QToolBar QPushButton {
    background: #1c1e23;
    color: #d4d4d4;
    border: 1px solid #2a2d33;
    border-radius: 4px;
    padding: 4px 10px;
    font-family: Inter, Cantarell;
    font-size: 12px;
}
QToolBar QPushButton:hover {
    background: #2a2d33;
    border-color: #ff7800;
}
QToolBar QPushButton:pressed {
    background: #141518;
}
QTabWidget::pane {
    border: none;
    background: #080909;
}
QTabBar::tab {
    background: #141518;
    color: #888;
    border: 1px solid #1e1e24;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-family: Inter, Cantarell;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #1c1e23;
    color: #ff7800;
    border-color: #2a2d33;
}
QTabBar::tab:hover:!selected {
    color: #b0b0b0;
}
QStatusBar {
    background: #0d0e12;
    color: #666;
    border-top: 1px solid #1e1e24;
    font-family: Inter, Cantarell;
    font-size: 11px;
}
QDialog {
    background: #141518;
    color: #d4d4d4;
}
QListWidget {
    background: #0d0e12;
    color: #d4d4d4;
    border: 1px solid #2a2d33;
    border-radius: 4px;
    outline: none;
}
QListWidget::item:selected {
    background: #ff7800;
    color: #080909;
}
QListWidget::item:hover {
    background: #1c1e23;
}
QInputDialog QLineEdit {
    background: #0d0e12;
    color: #d4d4d4;
    border: 1px solid #2a2d33;
    border-radius: 4px;
    padding: 4px 8px;
}
QMenu {
    background: #141518;
    color: #d4d4d4;
    border: 1px solid #2a2d33;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #1c1e23;
    color: #ff7800;
}
QMenu::separator {
    height: 1px;
    background: #2a2d33;
    margin: 4px 8px;
}
QScrollBar:horizontal, QScrollBar:vertical {
    background: transparent;
    border: none;
    width: 6px;
    height: 6px;
}
QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
    background: #2a2d33;
    border-radius: 3px;
    min-width: 20px;
    min-height: 20px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
    width: 0px;
}
QMessageBox {
    background: #141518;
    color: #d4d4d4;
}
QMessageBox QPushButton {
    background: #1c1e23;
    color: #d4d4d4;
    border: 1px solid #2a2d33;
    border-radius: 4px;
    padding: 6px 20px;
}
QMessageBox QPushButton:hover {
    background: #2a2d33;
    border-color: #ff7800;
}
"""
