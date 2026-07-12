from __future__ import annotations

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QTextEdit, QLabel, QApplication,
        QGraphicsDropShadowEffect, QFrame,
    )
    from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QPoint
    from PyQt6.QtGui import QFont, QColor, QPalette, QKeyEvent, QPainter, QBrush, QPen, QPainterPath
    HAS_QT = True
except ImportError:
    HAS_QT = False


class QuickBar(QWidget):
    def __init__(self):
        super().__init__()
        if not HAS_QT:
            return
        self._conversation_id: str | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(620, 480)

        self._setup_ui()
        self._center_on_screen()

    def _setup_ui(self):
        container = QWidget(self)
        container.setObjectName("container")
        container.setGeometry(0, 0, 620, 480)
        container.setStyleSheet("""
            #container {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 16px;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Fennix")
        title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Sans", 11))
        self._output.setStyleSheet("""
            QTextEdit {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        self._output.setMaximumHeight(260)
        self._output.setPlaceholderText("Answers will appear here...")
        layout.addWidget(self._output)

        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #181825;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
            QFrame:focus-within {
                border: 1px solid #89b4fa;
            }
        """)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(4, 4, 4, 4)

        self._input = QTextEdit()
        self._input.setFont(QFont("Sans", 13))
        self._input.setMaximumHeight(60)
        self._input.setMinimumHeight(40)
        self._input.setPlaceholderText("Ask Fennix anything... (Enter to send, Esc to close)")
        self._input.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: #cdd6f4;
                border: none;
                padding: 6px;
            }
        """)
        input_layout.addWidget(self._input)

        hint = QLabel("Enter: ask  |  Shift+Enter: new line  |  Esc: close")
        hint.setFont(QFont("Sans", 9))
        hint.setStyleSheet("color: #585b70; padding: 2px 8px;")
        input_layout.addWidget(hint)

        layout.addWidget(input_frame)

        self._status = QLabel("Ready")
        self._status.setFont(QFont("Sans", 9))
        self._status.setStyleSheet("color: #585b70;")
        layout.addWidget(self._status)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        container.setGraphicsEffect(shadow)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            center = screen.availableGeometry().center()
            self.move(center.x() - 310, center.y() - 350)

    def focus_input(self):
        self._input.setFocus()
        self._input.selectAll()

    def keyPressEvent(self, event: QKeyEvent | None):
        if event is None:
            return

        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self._ask()
            return

        super().keyPressEvent(event)

    def _ask(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        self._input.clear()
        self._input.setEnabled(False)
        self._output.append(f"<b style='color: #89b4fa;'>You:</b> {text}")
        self._output.append(f"<i style='color: #585b70;'>Fennix is thinking...</i>")
        self._status.setText("Thinking...")
        self._status.setStyleSheet("color: #f9e2af;")

        def _do():
            try:
                from fennix.assistant.__init__ import answer
                result = answer(text, self._conversation_id)
                self._conversation_id = result.get("conversation_id")
                reply = result.get("reply", "No response")
            except Exception as e:
                reply = f"Error: {e}"

            cursor = self._output.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._output.setTextCursor(cursor)
            block = self._output.document().lastBlock()
            if "thinking" in block.text():
                cursor.select(cursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deletePreviousChar()

            self._output.append(f"<b style='color: #a6e3a1;'>Fennix:</b> {reply}<br>")
            self._status.setText("Ready")
            self._status.setStyleSheet("color: #585b70;")
            self._input.setEnabled(True)
            self._input.setFocus()

        import threading
        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._output.clear()
        self._status.setText("Ready")
        self._status.setStyleSheet("color: #585b70;")
        self._input.setEnabled(True)
        QTimer.singleShot(100, self.focus_input)
