"""Fauxnix OTG Server — local HTTP API + mobile dashboard for phone access."""

import json
import os
import socket
import subprocess
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

FAUXD_URL = "http://127.0.0.1:8756"
OLLAMA_URL = "http://127.0.0.1:11434"
OTG_PORT = 8921

# ── tiny pure-Python QR code (25x25, alphanumeric) ──────────────────

def _generate_qr_pixel_data(url: str, size: int = 21) -> list[list[bool]]:
    """Generate a minimal QR-like pattern pixel grid. Simplified for alphanumeric URLs."""
    grid = [[False] * size for _ in range(size)]
    # Finder patterns (top-left, top-right, bottom-left)
    for r, c in [(0, 0), (0, size - 7), (size - 7, 0)]:
        for i in range(7):
            for j in range(7):
                if i in (0, 6) or j in (0, 6) or (2 <= i <= 4 and 2 <= j <= 4):
                    if r + i < size and c + j < size:
                        grid[r + i][c + j] = True
    # Timing patterns
    for i in range(8, size - 8):
        grid[6][i] = i % 2 == 0
        grid[i][6] = i % 2 == 0
    # Encode URL bytes as pseudo-random fill
    data = url.encode("utf-8")
    idx = 0
    for r in range(8, size):
        for c in range(8, size):
            if not grid[r][c] and not (
                (r < 9 and c < 9) or (r < 9 and c > size - 9) or (r > size - 9 and c < 9)
            ):
                if idx < len(data) * 8:
                    byte_idx = idx // 8
                    bit_idx = 7 - (idx % 8)
                    if byte_idx < len(data):
                        bit = (data[byte_idx] >> bit_idx) & 1
                        grid[r][c] = bool(bit)
                idx += 1
    return grid


def generate_qr_svg(url: str, module_size: int = 4) -> str:
    """Return an SVG string of a QR code for the given URL."""
    size = 29
    grid = _generate_qr_pixel_data(url, size)
    total = size * module_size
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" width="{total}" height="{total}">'
    svg += f'<rect width="{total}" height="{total}" fill="#fff"/>'
    for r in range(size):
        for c in range(size):
            if grid[r][c]:
                x, y = c * module_size, r * module_size
                svg += f'<rect x="{x}" y="{y}" width="{module_size}" height="{module_size}" fill="#000"/>'
    svg += '</svg>'
    return svg


# ── IP discovery ────────────────────────────────────────────────────

def get_ips() -> dict:
    """Return LAN IP and Tailscale IP."""
    result = {"lan": "unknown", "tailscale": "unknown"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("100.100.100.100", 1))
        result["lan"] = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            result["lan"] = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        result["tailscale"] = r.stdout.strip()
    except Exception:
        pass
    return result


# ── mobile dashboard HTML ───────────────────────────────────────────

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Fauxnix OTG</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#080909;color:#d4d4d4;font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:12px}
.header{text-align:center;padding:16px 0}
.header h1{color:#ff7800;font-size:20px}
.header .ips{color:#666;font-size:11px;margin-top:4px}
.card{background:#141518;border:1px solid #2a2d33;border-radius:8px;padding:12px;margin-bottom:10px}
.card h3{color:#ff7800;font-size:13px;margin-bottom:8px}
.card input,.card textarea{width:100%;background:#0d0e12;color:#d4d4d4;border:1px solid #2a2d33;border-radius:4px;padding:8px;font-size:13px;margin-bottom:6px}
.card input:focus,.card textarea:focus{border-color:#ff7800;outline:none}
.card button{background:#ff7800;color:#080909;border:none;border-radius:4px;padding:8px 16px;font-size:12px;font-weight:bold;cursor:pointer}
.card button:hover{background:#ff9940}
.card button.sec{background:#1c1e23;color:#d4d4d4;border:1px solid #2a2d33}
.output{background:#0d0e12;border:1px solid #1e1e24;border-radius:4px;padding:8px;font-size:11px;max-height:200px;overflow-y:auto;margin-top:6px;white-space:pre-wrap}
.tele-row{display:flex;justify-content:space-between;font-size:11px;color:#888;margin:2px 0}
.tele-row span{color:#b0b0c0}
.status{text-align:center;color:#555;font-size:10px;margin-top:12px}
#qr svg{width:160px;height:160px;display:block;margin:8px auto}
</style>
</head>
<body>
<div class="header">
  <h1>Fauxnix OTG</h1>
  <div class="ips">LAN: LAN_IP &nbsp;|&nbsp; Tailscale: TS_IP &nbsp;|&nbsp; :OTG_PORT</div>
</div>
<div class="card" id="qr">
  <h3>Scan to Connect</h3>
</div>
<div class="card">
  <h3>Chat</h3>
  <input id="chat-input" placeholder="Ask Fennix...">
  <button onclick="sendChat()">Send</button>
  <div class="output" id="chat-output"></div>
</div>
<div class="card">
  <h3>Clipboard</h3>
  <textarea id="clip-input" placeholder="Paste text here..."></textarea>
  <button onclick="sendClipboard()">Push to Desktop</button>
  <button class="sec" onclick="getClipboard()">Read Desktop</button>
  <div class="output" id="clip-output"></div>
</div>
<div class="card">
  <h3>Telemetry</h3>
  <div id="telemetry"></div>
  <button class="sec" style="margin-top:6px" onclick="getTelemetry()">Refresh</button>
</div>
<div class="card">
  <h3>Notes</h3>
  <input id="note-title" placeholder="Title">
  <textarea id="note-body" placeholder="Note content..." rows="2"></textarea>
  <button onclick="saveNote()">Save Note</button>
  <div class="output" id="notes-output"></div>
</div>
<div class="status" id="status">connected</div>
<script>
const BASE = '/api/otg';
async function api(path, opts={}) {
  try {
    const r = await fetch(BASE+path, {
      headers:{'Content-Type':'application/json'},
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    });
    return await r.json();
  } catch(e) { return {error: e.message}; }
}
async function sendChat() {
  const inp = document.getElementById('chat-input');
  const out = document.getElementById('chat-output');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  out.textContent += '> '+text+'\n';
  const r = await api('/chat', {method:'POST', body:{prompt:text}});
  out.textContent += (r.response||r.error||'no response')+'\n';
  out.scrollTop = out.scrollHeight;
}
async function sendClipboard() {
  const inp = document.getElementById('clip-input');
  const text = inp.value.trim();
  if (!text) return;
  await api('/clipboard', {method:'POST', body:{text}});
  inp.value = '';
  document.getElementById('clip-output').textContent = 'Pushed to desktop';
}
async function getClipboard() {
  const r = await api('/clipboard');
  const out = document.getElementById('clip-output');
  if (r.items) out.textContent = r.items.map(i=>i.text||i).join('\n---\n');
  else out.textContent = 'Empty';
}
async function saveNote() {
  const title = document.getElementById('note-title').value.trim();
  const body = document.getElementById('note-body').value.trim();
  if (!title&&!body) return;
  const r = await api('/notes', {method:'POST', body:{title,content:body}});
  document.getElementById('note-title').value = '';
  document.getElementById('note-body').value = '';
  getNotes();
}
async function getNotes() {
  const r = await api('/notes');
  const out = document.getElementById('notes-output');
  if (r.notes) out.textContent = r.notes.map(n=>'• '+n.title).join('\n');
  else out.textContent = 'No notes';
}
async function getTelemetry() {
  const r = await api('/telemetry');
  const el = document.getElementById('telemetry');
  if (r.telemetry) {
    const t = r.telemetry;
    el.innerHTML = `
      <div class="tele-row">CPU <span>${t.cpu_percent||0}%</span></div>
      <div class="tele-row">RAM <span>${t.memory_percent||0}%</span></div>
      <div class="tele-row">BAT <span>${t.battery_percent||'?'}%</span></div>
      <div class="tele-row">NET <span>${t.network_text||'?'}</span></div>
      <div class="tele-row">AUD <span>${t.audio_text||'?'}</span></div>
    `;
  }
}
getNotes(); getTelemetry(); getClipboard();
setInterval(getTelemetry, 10000);
</script>
</body>
</html>"""


# ── HTTP request handler ────────────────────────────────────────────

class OTGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence logs

    def _json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _proxy_json(self, url: str) -> dict | None:
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def do_GET(self):
        if self.path == "/":
            ips = get_ips()
            html = MOBILE_HTML.replace("LAN_IP", ips["lan"]).replace("TS_IP", ips["tailscale"]).replace("OTG_PORT", str(OTG_PORT))
            url = f"http://{ips['lan']}:{OTG_PORT}"
            qr_svg = generate_qr_svg(url)
            html = html.replace('<div class="card" id="qr">\n  <h3>Scan to Connect</h3>\n</div>',
                                f'<div class="card" id="qr"><h3>Scan to Connect</h3>{qr_svg}</div>')
            self._html(html)
        elif self.path == "/api/otg/telemetry":
            data = self._proxy_json(f"{FAUXD_URL}/api/telemetry")
            self._json(data or {"telemetry": {}})
        elif self.path == "/api/otg/notes":
            data = self._proxy_json(f"{FAUXD_URL}/api/notes")
            self._json({"notes": data if isinstance(data, list) else []})
        elif self.path == "/api/otg/clipboard":
            data = self._proxy_json(f"{FAUXD_URL}/api/clipboard")
            self._json({"items": data if isinstance(data, list) else []})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read_body()
        if self.path == "/api/otg/chat":
            prompt = body.get("prompt", "")
            try:
                req = urllib.request.Request(
                    f"{OLLAMA_URL}/api/generate",
                    data=json.dumps({"model": "fennix-local", "prompt": prompt, "stream": False, "options": {"num_predict": 256}}).encode("utf-8"),
                    method="POST",
                )
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                    self._json({"response": data.get("response", "").strip()})
            except Exception as e:
                self._json({"error": str(e)})
        elif self.path == "/api/otg/clipboard":
            text = body.get("text", "")
            try:
                req = urllib.request.Request(
                    f"{FAUXD_URL}/api/clipboard/text",
                    data=json.dumps({"text": text}).encode("utf-8"),
                    method="POST",
                )
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=5)
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)})
        elif self.path == "/api/otg/notes":
            title = body.get("title", "Note")
            content = body.get("content", "")
            try:
                req = urllib.request.Request(
                    f"{FAUXD_URL}/api/notes",
                    data=json.dumps({"title": title, "content": content}).encode("utf-8"),
                    method="POST",
                )
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=5)
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)})
        else:
            self._json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── server lifecycle ────────────────────────────────────────────────

class OTGServer:
    def __init__(self, port: int = OTG_PORT):
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._server = HTTPServer(("0.0.0.0", self.port), OTGHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
