from __future__ import annotations

try:
    from PyQt6.QtWidgets import (
        QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QScrollArea, QCheckBox,
        QLineEdit, QListWidget, QListWidgetItem, QFrame, QSplitter,
        QMessageBox, QFileDialog,
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QFont, QColor, QPalette
    HAS_QT = True
except ImportError:
    HAS_QT = False

from membrie.chat import answer_query, list_conversations, get_conversation
from membrie.awareness.drift import get_drift_status, get_drift_history, set_intention, get_intention, get_focus_state
from membrie.awareness.process import _categorize_process, category_color
from membrie.session import get_active_session, list_sessions, start_session, end_session
from membrie.services import ServicesManager


class MembrieWindow(QMainWindow):
    def __init__(self, services: ServicesManager):
        super().__init__()
        self._services = services
        self.setWindowTitle("Membrie — FauxnixOS Companion")
        self.resize(800, 600)
        self._setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(5000)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        tabs = QTabWidget()
        tabs.addTab(self._activity_tab(), "Activity")
        tabs.addTab(self._chat_tab(), "Chat")
        tabs.addTab(self._sessions_tab(), "Sessions")
        tabs.addTab(self._settings_tab(), "Settings")
        layout.addWidget(tabs)

    def _activity_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        status_layout = QVBoxLayout(status_frame)

        self._status_label = QLabel("Status: Initializing...")
        self._status_label.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        status_layout.addWidget(self._status_label)

        intention_layout = QHBoxLayout()
        intention_layout.addWidget(QLabel("Intention:"))
        self._intention_input = QLineEdit()
        self._intention_input.setPlaceholderText("What are you working on?")
        self._intention_input.returnPressed.connect(self._set_intention)
        intention_layout.addWidget(self._intention_input)
        set_btn = QPushButton("Set")
        set_btn.clicked.connect(self._set_intention)
        intention_layout.addWidget(set_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_intention)
        intention_layout.addWidget(clear_btn)
        status_layout.addLayout(intention_layout)

        layout.addWidget(status_frame)

        session_layout = QHBoxLayout()
        self._session_btn = QPushButton("Start Session")
        self._session_btn.clicked.connect(self._toggle_session)
        session_layout.addWidget(self._session_btn)
        self._session_label = QLabel("No active session")
        session_layout.addWidget(self._session_label)
        session_layout.addStretch()
        layout.addLayout(session_layout)

        self._timeline_list = QListWidget()
        layout.addWidget(QLabel("Recent Activity:"))
        layout.addWidget(self._timeline_list)

        focus_frame = QFrame()
        focus_layout = QHBoxLayout(focus_frame)
        self._focus_label = QLabel("Focus: --")
        focus_layout.addWidget(self._focus_label)
        focus_layout.addStretch()
        layout.addWidget(focus_frame)

        return w

    def _chat_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._chat_history = QTextEdit()
        self._chat_history.setReadOnly(True)
        layout.addWidget(self._chat_history)

        input_layout = QHBoxLayout()
        self._chat_input = QTextEdit()
        self._chat_input.setMaximumHeight(80)
        self._chat_input.setPlaceholderText("Ask Membrie something...")
        input_layout.addWidget(self._chat_input)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_chat)
        input_layout.addWidget(send_btn)
        layout.addLayout(input_layout)

        conv_layout = QHBoxLayout()
        conv_layout.addWidget(QLabel("Conversation:"))
        self._conv_list = QListWidget()
        self._conv_list.setMaximumHeight(100)
        self._conv_list.itemClicked.connect(self._load_conversation)
        conv_layout.addWidget(self._conv_list)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new_chat)
        conv_layout.addWidget(new_btn)
        layout.addLayout(conv_layout)

        return w

    def _sessions_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._sessions_list = QListWidget()
        self._sessions_list.itemClicked.connect(self._show_session_detail)
        layout.addWidget(self._sessions_list)

        self._session_detail = QTextEdit()
        self._session_detail.setReadOnly(True)
        self._session_detail.setMaximumHeight(200)
        layout.addWidget(self._session_detail)

        btn_layout = QHBoxLayout()
        new_ws_btn = QPushButton("Create Workspace from Selected")
        new_ws_btn.clicked.connect(self._create_workspace)
        btn_layout.addWidget(new_ws_btn)
        export_btn = QPushButton("Export to File")
        btn_layout.addWidget(export_btn)
        layout.addLayout(btn_layout)

        return w

    def _settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Background Services"))
        for svc_name in ["process_watcher", "clipboard_monitor", "idle_detector",
                          "drift_detector", "focus_tracker", "file_index_checker"]:
            cb = QCheckBox(svc_name.replace("_", " ").title())
            cb.setChecked(self._services.service_running(svc_name))
            cb.toggled.connect(lambda checked, n=svc_name: self._services.toggle_service(n, checked))
            layout.addWidget(cb)

        layout.addStretch()
        return w

    def _set_intention(self):
        text = self._intention_input.text().strip()
        if text:
            set_intention(text)

    def _clear_intention(self):
        from membrie.awareness.drift import clear_intention
        clear_intention()
        self._intention_input.clear()

    def _toggle_session(self):
        active = get_active_session()
        if active:
            result = end_session(active["id"])
            if result.get("ok"):
                self._session_label.setText(f"Ended: {result.get('summary', '')[:100]}")
                self._session_btn.setText("Start Session")
        else:
            result = start_session()
            self._session_label.setText(f"Session started at {result.get('started_ts', '')}")
            self._session_btn.setText("End Session")

    def _send_chat(self):
        text = self._chat_input.toPlainText().strip()
        if not text:
            return
        self._chat_input.clear()
        self._chat_history.append(f"<b>You:</b> {text}")
        self._chat_history.append("<i>Membrie is thinking...</i>")
        try:
            result = answer_query(text)
            reply = result.get("reply", "No response")
        except Exception as e:
            reply = f"Error: {e}"
        self._chat_history.moveCursor(self._chat_history.textCursor().MoveOperation.End)
        self._chat_history.textCursor().deletePreviousChar()
        self._chat_history.textCursor().deletePreviousChar()
        self._chat_history.insertHtml(f"<b>Membrie:</b> {reply}<br><br>")

    def _new_chat(self):
        self._chat_history.clear()
        self._conversation_id = None

    def _load_conversation(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if not conv_id:
            return
        conv = get_conversation(conv_id)
        if not conv:
            return
        self._chat_history.clear()
        for msg in conv.get("messages", []):
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                self._chat_history.append(f"<b>You:</b> {content}")
            else:
                self._chat_history.append(f"<b>Membrie:</b> {content}")
            self._chat_history.append("")

    def _show_session_detail(self, item):
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        from membrie.session import get_session_timeline
        result = get_session_timeline(session_id)
        if not result.get("ok"):
            return
        s = result["session"]
        detail = f"Summary: {s.get('summary', 'N/A')}\n"
        detail += f"Duration: {int(s.get('total_active_seconds', 0) // 60)}m active\n"
        detail += f"Focus: {int(s.get('focus_seconds', 0) // 60)}m\n"
        detail += f"Drifts: {s.get('drift_count', 0)}\n"
        self._session_detail.setPlainText(detail)

    def _create_workspace(self):
        item = self._sessions_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        from membrie.session.workspace import create_workspace_from_session
        result = create_workspace_from_session(session_id)
        if result.get("ok"):
            QMessageBox.information(self, "Workspace Created",
                f"Created '{result['name']}' with {result['node_count']} activity nodes.")

    def _refresh(self):
        if not HAS_QT:
            return

        drift = get_drift_status()
        intention = get_intention()
        focus = get_focus_state()
        state = drift.get("state", "unknown")
        cat = drift.get("category", "")
        color = drift.get("category_color", "#888")
        self._status_label.setText(f"Status: {state} {'('+cat+')' if cat else ''}")
        self._intention_input.setText(intention or "")

        focus_text = f"Focus: {focus.get('total_today_min', 0)}m today"
        if focus.get("in_focus"):
            streak = focus.get("current_streak", 0)
            focus_text += f" — In focus {(streak // 60)}m"
        self._focus_label.setText(focus_text)

        active = get_active_session()
        if active:
            elapsed = active.get("elapsed_seconds", 0)
            self._session_label.setText(f"Session active: {elapsed // 60}m {elapsed % 60}s")
            self._session_btn.setText("End Session")
        else:
            self._session_label.setText("No active session")
            self._session_btn.setText("Start Session")

        history = get_drift_history(hours=1)[:20]
        self._timeline_list.clear()
        for h in history:
            pn = h.get("process_name", "")
            dur = int(h.get("duration_seconds", 0) or 0)
            if pn.startswith("__"):
                continue
            item_text = f"[{h.get('time', '?')}] {pn} ({dur}s)"
            if h.get("window_title"):
                item_text += f" — {h['window_title'][:60]}"
            self._timeline_list.addItem(item_text)

        convs = list_conversations(limit=5)
        self._conv_list.clear()
        for c in convs:
            item = QListWidgetItem(f"{c.get('title', 'Untitled')[:60]}")
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self._conv_list.addItem(item)

        sessions = list_sessions(limit=10)
        self._sessions_list.clear()
        for s in sessions:
            started = s.get("started_ts", 0)
            dur = int(s.get("total_active_seconds", 0) // 60)
            import datetime
            start_str = datetime.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem(f"{start_str} — {dur}m")
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self._sessions_list.addItem(item)
