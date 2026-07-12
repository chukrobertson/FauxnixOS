from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

try:
    from fastapi import FastAPI, Request, UploadFile, File, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from fauxnix_tools.config import config

OTG_PORT = int(os.getenv("MEMBRIE_OTG_PORT", "8920"))


def _find_free_port(start: int = 8920, max_attempts: int = 20) -> int:
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


OTG_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Membrie OTG</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; max-width: 600px; margin: 0 auto; padding: 16px; }
        .card { background: #16213e; border-radius: 12px; padding: 20px; margin: 12px 0; }
        h1 { color: #4caf50; font-size: 1.5em; margin-bottom: 16px; }
        h2 { font-size: 1.1em; color: #81c784; margin-bottom: 8px; }
        input, textarea { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: 1px solid #333; background: #0f3460; color: #eee; font-size: 16px; }
        button { background: #4caf50; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-size: 16px; cursor: pointer; width: 100%; margin: 4px 0; }
        button:hover { background: #388e3c; }
        .response { background: #0f3460; border-radius: 8px; padding: 12px; margin: 8px 0; white-space: pre-wrap; font-size: 14px; }
        .status { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; }
        .status.on_track { background: #4caf50; }
        .status.drifted { background: #ef5350; }
        .status.neutral { background: #ffd54f; color: #333; }
    </style>
</head>
<body>
    <h1>Membrie OTG</h1>

    <div class="card" id="drift-card">
        <h2>Current Status</h2>
        <div id="drift-status">Loading...</div>
        <div id="focus-status"></div>
    </div>

    <div class="card">
        <h2>Chat</h2>
        <textarea id="chat-input" placeholder="Ask Membrie..." rows="3"></textarea>
        <button onclick="sendChat()">Send</button>
        <div id="chat-response"></div>
    </div>

    <div class="card">
        <h2>Set Intention</h2>
        <input id="intention-input" placeholder="What are you working on?">
        <button onclick="setIntention()">Set</button>
    </div>

    <div class="card">
        <h2>Memories</h2>
        <input id="memory-search" placeholder="Search memories...">
        <button onclick="searchMemories()">Search</button>
        <div id="memory-results"></div>
    </div>

    <div class="card">
        <h2>Sessions</h2>
        <button onclick="loadSessions()">Load Sessions</button>
        <div id="sessions-list"></div>
    </div>

    <script>
        const API = '/api';

        async function api(method, data) {
            try {
                const res = await fetch(API, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({method, data}),
                });
                return await res.json();
            } catch(e) {
                return {error: e.toString()};
            }
        }

        async function sendChat() {
            const text = document.getElementById('chat-input').value;
            const el = document.getElementById('chat-response');
            el.innerHTML = '<i>Thinking...</i>';
            const r = await api('chat', {text});
            el.innerHTML = `<div class="response">${r.reply || r.error || 'No response'}</div>`;
        }

        async function setIntention() {
            const text = document.getElementById('intention-input').value;
            const r = await api('set_intention', {text});
            document.getElementById('intention-input').value = '';
            loadStatus();
        }

        async function loadStatus() {
            const r = await api('status', {});
            if (r.drift) {
                const d = r.drift;
                document.getElementById('drift-status').innerHTML =
                    `<span class="status ${d.state}">${d.state}</span> ${d.process || '--'} ${d.category ? '('+d.category+')' : ''}`;
            }
            if (r.focus) {
                document.getElementById('focus-status').innerHTML =
                    `Focus: ${r.focus.total_today_min || 0}m today` +
                    (r.focus.in_focus ? ` — In focus ${r.focus.current_streak ? Math.floor(r.focus.current_streak/60) : 0}m` : '');
            }
        }

        async function searchMemories() {
            const query = document.getElementById('memory-search').value;
            const el = document.getElementById('memory-results');
            el.innerHTML = '<i>Searching...</i>';
            const r = await api('search_memories', {query});
            if (r.memories && r.memories.length) {
                el.innerHTML = r.memories.map(m => `<div class="response">${m.content}</div>`).join('');
            } else {
                el.innerHTML = '<div class="response">No memories found.</div>';
            }
        }

        async function loadSessions() {
            const el = document.getElementById('sessions-list');
            el.innerHTML = '<i>Loading...</i>';
            const r = await api('list_sessions', {});
            if (r.sessions && r.sessions.length) {
                el.innerHTML = r.sessions.map(s =>
                    `<div class="response"><b>${s.summary || 'Session'}</b><br>${s.total_active_seconds ? Math.floor(s.total_active_seconds/60) : 0}m active</div>`
                ).join('');
            } else {
                el.innerHTML = '<div class="response">No past sessions.</div>';
            }
        }

        setInterval(loadStatus, 10000);
        loadStatus();
    </script>
</body>
</html>"""


def create_otg_app() -> FastAPI:
    app = FastAPI(title="Membrie OTG")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return OTG_HTML

    @app.post("/api")
    async def api_handler(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        method = body.get("method")
        data = body.get("data", {})

        if method == "status":
            from membrie.awareness.drift import get_drift_status, get_focus_state
            drift = get_drift_status()
            focus = get_focus_state()
            return {"drift": drift, "focus": focus}

        elif method == "chat":
            from membrie.chat import answer_query
            text = data.get("text", "")
            if not text:
                return {"error": "No text provided"}
            return answer_query(text)

        elif method == "set_intention":
            from membrie.awareness.drift import set_intention
            text = data.get("text", "")
            if text:
                set_intention(text)
            return {"ok": True}

        elif method == "search_memories":
            from membrie.chat.memory import search_memories
            query = data.get("query", "")
            memories = search_memories(query, limit=10)
            return {"memories": memories}

        elif method == "list_sessions":
            from membrie.session import list_sessions
            sessions = list_sessions(limit=10)
            return {"sessions": sessions}

        elif method == "get_session":
            from membrie.session import get_session_timeline
            sid = data.get("session_id", "")
            return get_session_timeline(sid)

        elif method == "start_session":
            from membrie.session import start_session
            return start_session()

        elif method == "end_session":
            from membrie.session import end_session
            sid = data.get("session_id", "")
            if not sid:
                from membrie.session import get_active_session
                active = get_active_session()
                sid = active["id"] if active else ""
            return end_session(sid) if sid else {"ok": False, "error": "no_active_session"}

        elif method == "workspace":
            from membrie.session.workspace import create_workspace_from_session, browse_workspaces
            sid = data.get("session_id", "")
            if sid:
                return create_workspace_from_session(sid, data.get("name"))
            return {"workspaces": browse_workspaces()}

        elif method == "drift_history":
            from membrie.awareness.drift import get_drift_history
            return {"history": get_drift_history(hours=int(data.get("hours", 24)))}

        return {"error": f"Unknown method: {method}"}

    return app


def run_otg_server(port: int | None = None):
    if not HAS_FASTAPI:
        print("FastAPI not installed. OTG server unavailable.")
        return

    port = port or _find_free_port(OTG_PORT)
    app = create_otg_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    try:
        server.run()
    except Exception:
        pass
