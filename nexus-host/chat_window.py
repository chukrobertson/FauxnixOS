"""Nexus Admin Chat — chat interface with model selection and system access."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor

from ollama_client import OllamaStreamThread, get_models, ADMIN_MODEL


class ChatWindow(QWidget):
    """Chat interface for Nexus Admin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nexus Admin")
        self.setMinimumSize(500, 400)
        self.resize(600, 500)
        self._model = ADMIN_MODEL
        self._thread = None
        self._first_token = True
        self._building_response = False
        self._build_ui()
        QTimer.singleShot(500, self._load_models)

    def _build_ui(self):
        self.setStyleSheet("background: #0d0e12;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("Nexus Admin")
        title.setStyleSheet("color: #ff7800; font-size: 14px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(200)
        self._model_combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 3px 6px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; "
            "selection-background-color: #ff7800; }"
        )
        self._model_combo.currentTextChanged.connect(lambda m: setattr(self, "_model", m))
        header.addWidget(self._model_combo)
        layout.addLayout(header)

        # Chat output
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit { background: #080909; color: #d4d4d4; border: 1px solid #1e1e24; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        layout.addWidget(self._output, 1)

        # Input row
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask Nexus Admin...")
        self._input.setStyleSheet(
            "QLineEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 6px; padding: 8px 12px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #ff7800; }"
        )
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(
            "QPushButton { background: #ff7800; color: #080909; border: none; "
            "border-radius: 6px; padding: 8px 16px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #ff9940; }"
        )
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

    def _load_models(self):
        models = get_models()
        if models:
            self._model_combo.clear()
            self._model_combo.addItems(models)
            if ADMIN_MODEL in models:
                self._model_combo.setCurrentText(ADMIN_MODEL)
                self._model = ADMIN_MODEL
            elif models:
                self._model = models[0]

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._output.append(f'<b style="color:#ff7800;">You:</b> {text}')
        self._output.append(f'<i style="color:#666;">Nexus ({self._model}):</i> <span style="color:#888;">loading model...</span>')

        self._thread = OllamaStreamThread(text, self._model)
        self._thread.token.connect(self._on_token)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_token(self, token: str):
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Clear "loading model..." on first token
        if not getattr(self, '_first_token', True):
            pass
        else:
            self._first_token = False
            # Remove last line (loading indicator)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
        cursor.insertText(token)
        self._output.ensureCursorVisible()

    def _on_finished(self, full: str):
        self._thread = None
        self._first_token = True

    def _on_error(self, err: str):
        self._output.append(f'<span style="color:#ff4444;">Error: {err}</span>')
        self._thread = None
